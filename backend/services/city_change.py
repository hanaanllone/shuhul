"""
Shuhul smart city Srinagar.

How the city's vegetation and surface heat have moved since 2017, block
by block, and how far the two go together: where green cover fell, did
the surface get hotter?

    GET /api/city/change

Reads the yearly summer composites of vegetation index and surface
temperature, cuts the city into square blocks and compares the first
three years with the last three.
"""

from functools import lru_cache

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform as warp_points

from .area_environment import AreaError, _district_shape, _yearly_folder
from .jsonsafe import finite as json_safe

CITY = "sr-c"

# Cells of the yearly grid along one side of a block: 10 cells of 30 m.
BLOCK_CELLS = 10

# A block counts when this share of it lies inside the city with readings.
MIN_BLOCK_COVER = 0.4

# Years averaged at each end of the record. One summer alone is too
# uneven to compare against another.
PERIOD_YEARS = 3

# A cell is counted as green above this vegetation index, and as open
# water above this water index.
GREEN_NDVI = 0.3
WATER_MNDWI = 0.0
MOSTLY_WATER = 0.5

# Smaller movements than these between the two periods count as no change.
STEADY_NDVI = 0.03
STEADY_HEAT_C = 0.3

# Blocks that began between these index values are part green, part built.
MIXED_NDVI = (0.3, 0.6)

KINDS = {
    "lost_hotter": "Lost green, got hotter",
    "lost": "Lost green, no hotter",
    "hotter": "Got hotter, green steady",
    "gained_cooler": "Gained green, got cooler",
    "gained": "Gained green, no cooler",
    "cooler": "Got cooler, green steady",
    "steady": "Little change",
    "water": "Mostly water, left out",
}


def _read(path, area):
    """A yearly layer cut to the city, no-data as NaN, and its transform."""
    with rasterio.open(path) as src:
        data, transform = mask(src, [area], crop=True, filled=False)
        return data[0].astype("float32").filled(np.nan), transform


def _blocks(grid, how=np.nanmean):
    """The grid in blocks of BLOCK_CELLS, as (block rows, block cols, cells)."""
    rows = int(np.ceil(grid.shape[0] / BLOCK_CELLS)) * BLOCK_CELLS
    cols = int(np.ceil(grid.shape[1] / BLOCK_CELLS)) * BLOCK_CELLS

    padded = np.full((rows, cols), np.nan, dtype="float32")
    padded[: grid.shape[0], : grid.shape[1]] = grid

    cells = padded.reshape(rows // BLOCK_CELLS, BLOCK_CELLS, cols // BLOCK_CELLS, BLOCK_CELLS)
    return cells.transpose(0, 2, 1, 3).reshape(rows // BLOCK_CELLS, cols // BLOCK_CELLS, -1)


def _block_mean(grid):
    """Mean of each block, empty where too little of the block has readings."""
    cells = _blocks(grid)
    found = np.isfinite(cells).sum(axis=2)

    with np.errstate(invalid="ignore"):
        total = np.nansum(cells, axis=2)
        mean = np.where(found > 0, total / np.maximum(found, 1), np.nan)

    mean[found < MIN_BLOCK_COVER * BLOCK_CELLS * BLOCK_CELLS] = np.nan
    return mean


def _period_mean(layers):
    """Mean over a few years of block values, ignoring years with no reading."""
    stack = np.stack(layers)
    found = np.isfinite(stack).sum(axis=0)

    with np.errstate(invalid="ignore"):
        return np.where(found > 0, np.nansum(stack, axis=0) / np.maximum(found, 1), np.nan)


def _round(value, digits=2):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def _kind(ndvi_change, heat_change):
    lost, gained = ndvi_change <= -STEADY_NDVI, ndvi_change >= STEADY_NDVI
    hotter, cooler = heat_change >= STEADY_HEAT_C, heat_change <= -STEADY_HEAT_C

    if lost:
        return "lost_hotter" if hotter else "lost"
    if gained:
        return "gained_cooler" if cooler else "gained"
    if hotter:
        return "hotter"
    return "cooler" if cooler else "steady"


def _link(greenness, heat):
    """How closely heat follows greenness, and by how much per 0.1 of the index."""
    if greenness.size < 3 or greenness.std() == 0 or heat.std() == 0:
        return {"blocks": int(greenness.size), "r": None, "heat_per_tenth_ndvi_c": None}

    return {
        "blocks": int(greenness.size),
        "r": _round(np.corrcoef(greenness, heat)[0, 1], 2),
        "heat_per_tenth_ndvi_c": _round(0.1 * float(np.polyfit(greenness, heat, 1)[0]), 2),
    }


def _group(ndvi_change, heat_change, chosen):
    """How many blocks fall in a group and how their heat moved on average."""
    if not chosen.any():
        return {"blocks": 0, "ndvi_change": None, "heat_change_c": None}

    return {
        "blocks": int(chosen.sum()),
        "ndvi_change": _round(ndvi_change[chosen].mean(), 3),
        "heat_change_c": _round(heat_change[chosen].mean(), 2),
    }


@lru_cache(maxsize=1)
def city_change():
    with rasterio.open(_master()) as src:
        crs = src.crs

    area = _district_shape(CITY, crs)
    yearly = _yearly_folder(CITY, area)
    if yearly is None:
        raise AreaError("No yearly record covers the city.")

    years = sorted(
        int(path.stem.split("_")[1])
        for path in yearly.glob("ndvi_*.tif")
        if (yearly / f"lst_rel_{path.stem.split('_')[1]}.tif").exists()
    )
    if len(years) < 2 * PERIOD_YEARS:
        raise AreaError("The yearly record is too short to compare two periods.")

    with rasterio.open(yearly / f"ndvi_{years[0]}.tif") as src:
        crs = src.crs
    area = _district_shape(CITY, crs)

    city, ndvi_blocks, heat_blocks, transform = [], [], [], None
    water = None

    for year in years:
        ndvi, transform = _read(yearly / f"ndvi_{year}.tif", area)
        heat, _ = _read(yearly / f"lst_rel_{year}.tif", area)
        lst, _ = _read(yearly / f"lst_{year}.tif", area) if (yearly / f"lst_{year}.tif").exists() else (None, None)

        seen = np.isfinite(ndvi)
        city.append({
            "year": year,
            "ndvi": _round(np.nanmean(ndvi), 3) if seen.any() else None,
            "green_pct": _round(100.0 * (ndvi[seen] >= GREEN_NDVI).mean(), 1) if seen.any() else None,
            "heat_c": _round(np.nanmean(heat), 2) if np.isfinite(heat).any() else None,
            "lst_c": _round(np.nanmean(lst), 1) if lst is not None and np.isfinite(lst).any() else None,
        })

        ndvi_blocks.append(_block_mean(ndvi))
        heat_blocks.append(_block_mean(heat))

        wet = yearly / f"mndwi_{year}.tif"
        if year == years[-1] and wet.exists():
            mndwi, _ = _read(wet, area)
            water = _block_mean(np.where(np.isfinite(mndwi), (mndwi > WATER_MNDWI).astype("float32"), np.nan))

    then_years, now_years = years[:PERIOD_YEARS], years[-PERIOD_YEARS:]
    ndvi_then, ndvi_now = _period_mean(ndvi_blocks[:PERIOD_YEARS]), _period_mean(ndvi_blocks[-PERIOD_YEARS:])
    heat_then, heat_now = _period_mean(heat_blocks[:PERIOD_YEARS]), _period_mean(heat_blocks[-PERIOD_YEARS:])

    ndvi_change, heat_change = ndvi_now - ndvi_then, heat_now - heat_then
    known = np.isfinite(ndvi_change) & np.isfinite(heat_change)
    wet = known & (water >= MOSTLY_WATER) if water is not None else np.zeros_like(known)
    land = known & ~wet

    # Corners of every block, moved to latitude and longitude in one go.
    rows, cols = np.nonzero(known)
    size = BLOCK_CELLS * transform.a
    left = transform.c + cols * size
    top = transform.f - rows * size
    xs = np.concatenate([left, left + size, left + size, left])
    ys = np.concatenate([top, top, top - size, top - size])
    lngs, lats = warp_points(crs, "EPSG:4326", xs.tolist(), ys.tolist())
    count = rows.size

    features = []
    for index, (row, col) in enumerate(zip(rows.tolist(), cols.tolist())):
        ring = [
            [round(lngs[index + corner * count], 6), round(lats[index + corner * count], 6)]
            for corner in (0, 1, 2, 3, 0)
        ]
        kind = "water" if wet[row, col] else _kind(ndvi_change[row, col], heat_change[row, col])

        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "block_id": f"B{row:02d}-{col:02d}",
                "kind": kind,
                "mixed": bool(land[row, col] and MIXED_NDVI[0] <= ndvi_then[row, col] < MIXED_NDVI[1]),
                "ndvi_then": _round(ndvi_then[row, col], 3),
                "ndvi_now": _round(ndvi_now[row, col], 3),
                "ndvi_change": _round(ndvi_change[row, col], 3),
                "heat_then_c": _round(heat_then[row, col], 2),
                "heat_now_c": _round(heat_now[row, col], 2),
                "heat_change_c": _round(heat_change[row, col], 2),
                "ndvi": [_round(layer[row, col], 3) for layer in ndvi_blocks],
                "heat_c": [_round(layer[row, col], 2) for layer in heat_blocks],
            },
        })

    # How far greenness and heat go together across the land blocks: as
    # they stand today, and in how they have moved.
    x, y = ndvi_change[land], heat_change[land]
    start = ndvi_then[land]

    # Blocks that began part green, part built are where green is lost to
    # buildings. Farmland and wetland lose green to water and wet fields,
    # which cools them, and bare blocks had little to lose.
    mixed = (start >= MIXED_NDVI[0]) & (start < MIXED_NDVI[1])
    lost, gained = x <= -STEADY_NDVI, x >= STEADY_NDVI

    relation = {
        "blocks": int(land.sum()),
        "now": _link(ndvi_now[land], heat_now[land]),
        "change": _link(x, y),
        "mixed": {
            **_link(x[mixed], y[mixed]),
            "ndvi_from": MIXED_NDVI[0],
            "ndvi_to": MIXED_NDVI[1],
            "lost": _group(x, y, mixed & lost),
            "steady": _group(x, y, mixed & ~lost & ~gained),
            "gained": _group(x, y, mixed & gained),
        },
        "lost": _group(x, y, lost),
        "steady": _group(x, y, ~lost & ~gained),
        "gained": _group(x, y, gained),
        "lost_and_hotter_pct": _round(100.0 * (y[lost] >= STEADY_HEAT_C).mean(), 0) if lost.any() else None,
        "gained_and_hotter_pct": _round(100.0 * (y[gained] >= STEADY_HEAT_C).mean(), 0) if gained.any() else None,
    }

    counts = {key: 0 for key in KINDS}
    for feature in features:
        counts[feature["properties"]["kind"]] += 1

    return json_safe({
        "type": "FeatureCollection",
        "features": features,
        "district": CITY,
        "years": years,
        "then_years": then_years,
        "now_years": now_years,
        "block_m": int(round(size)),
        "city": city,
        "relation": relation,
        "kinds": [{"key": key, "label": label, "blocks": counts[key]} for key, label in KINDS.items()],
        "steady": {"ndvi": STEADY_NDVI, "heat_c": STEADY_HEAT_C},
        "green_ndvi": GREEN_NDVI,
        "method": (
            "Summer (June to August) Landsat 8 and 9 composites for each year. Vegetation is the "
            "NDVI index. Heat is the surface temperature of a block against the valley floor in "
            "the same summer, which takes out the difference between a hot year and a cool one. "
            f"Each period is the average of {PERIOD_YEARS} summers."
        ),
        "caution": (
            "Blocks that move together do not prove that one caused the other, and surface "
            "temperature from a satellite is not air temperature. This shows where to look."
        ),
    })


def _master():
    from pathlib import Path

    from ..config import PROCESSED_ROOT

    path = Path(PROCESSED_ROOT) / CITY / "ndvi.tif"
    if not path.exists():
        raise AreaError("No data for the city.")
    return path


def register_city_routes(app):
    """Register GET /api/city/change."""
    from flask import jsonify

    @app.get("/api/city/change")
    def change():
        try:
            return jsonify(city_change())
        except (AreaError, FileNotFoundError) as exc:
            return jsonify({"error": str(exc) or "No data for the city."}), 404
