"""
Shuhul area environment.

What the map layers say about one area: a whole district, or a shape
drawn inside it. Heat, tree canopy, buildings, land cover, flood and
water history, and how vegetation, built-up cover and surface
temperature have moved year by year.

    POST /api/area/environment   {"district": "sxr", "geometry": <GeoJSON, optional>}

It also answers "what if": how the surface temperature of a drawn area
would move if part of it were planted, given green roofs, paved or built on.

    POST /api/area/what-if       {"district", "geometry", "change", "share"}

And it reads the surroundings of a single point, which is how a news
report is set beside the satellite record of the place it names.

    POST /api/area/around        {"lat", "lng"}
"""

from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import Point, mapping, shape

from ..config import PROCESSED_ROOT, PROJECT_ROOT
from . import thermal

LANDCOVER_NAMES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare or sparse",
    70: "Snow and ice",
    80: "Water",
    90: "Wetland",
    100: "Moss and lichen",
}

FLOOD_CLASSES = [("Low", 0.45), ("Moderate", 0.65), ("High", 0.85), ("Very high", float("inf"))]

# Yearly layers, and how each is summarised over an area.
YEARLY = {
    "ndvi": "Vegetation index",
    "ndbi": "Built-up index",
    "lst_rel": "Temperature against the valley floor, °C",
}


# Changes a planner can try on a drawn area: the surface the thermal model
# paints in, and the kind of land that could take it.
WHAT_IFS = {
    "trees": {"label": "Plant trees", "surface": "tree", "land": "open"},
    "shrubs": {"label": "Plant shrubs and grass", "surface": "shrub", "land": "open"},
    "green_roofs": {"label": "Green the roofs", "surface": "green_roof", "land": "roofs"},
    "pave": {"label": "Pave it", "surface": "road", "land": "unbuilt"},
    "build": {"label": "Build on it", "surface": "built", "land": "unbuilt"},
}

LAND_NAMES = {
    "open": "open land: not water, not built-up and not already under trees",
    "roofs": "roofs",
    "unbuilt": "land that is not water and not already built-up",
}

# How far around a reported place the record is read.
AROUND_RADIUS_M = 500.0

# Smaller movements than these between the early and late years are
# treated as no change: vegetation in percent, the built-up index in its
# own units. Yearly temperature is too uneven to read a trend at one place.
STEADY_VEGETATION_PCT = 5.0
STEADY_BUILT_UP = 0.03

# Over water the vegetation index follows weeds and water level, not land.
MOSTLY_WATER_PCT = 50.0

WHAT_IF_MAX_KM2 = 25.0
WATER_CODES = (80, 90)
BUILT_CODE = 50


class AreaError(Exception):
    """The area could not be read: unknown district or a shape outside it."""


def _district_shape(district, crs):
    path = Path(PROJECT_ROOT) / "districts-geojson" / f"{district}.geojson"
    if not path.exists():
        raise AreaError(f"Unknown district: {district}")

    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    return frame.to_crs(crs).geometry.union_all()


def _area_shape(district, geometry, crs):
    """The area to summarise, in the district CRS."""
    if not geometry:
        return _district_shape(district, crs)

    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry")

    drawn = gpd.GeoSeries([shape(geometry)], crs="EPSG:4326").to_crs(crs).iloc[0]
    if drawn.is_empty or drawn.area <= 0:
        raise AreaError("The drawn area is empty.")
    return drawn


def _values(path, area):
    """Cells of a raster inside the area, without no-data, and the cell area in m²."""
    if not path.exists():
        return None, 0.0

    with rasterio.open(path) as src:
        try:
            data, _ = mask(src, [area], crop=True, filled=False)
        except ValueError:
            return None, 0.0

        values = data[0].compressed().astype("float32")
        values = values[np.isfinite(values)]
        return values, abs(src.transform.a * src.transform.e)


def _yearly_folder(district, area):
    """
    The folder of yearly composites that covers the area. A district
    nested inside another reads the larger district's composites.
    """
    candidates = [Path(PROCESSED_ROOT) / district] + sorted(Path(PROCESSED_ROOT).glob("*"))

    # A district's grid is a rectangle that runs past its boundary into its
    # neighbours, where it is empty. The folder with the most readings over
    # the area is the one that covers it; the district asked for wins a tie.
    best, most, seen = None, 0, set()

    for folder in candidates:
        probe = folder / "yearly" / "lst_current.tif"
        if folder.name in seen or not probe.exists():
            continue
        seen.add(folder.name)

        values, _ = _values(probe, area)
        found = 0 if values is None else int(values.size)
        if found > most:
            best, most = folder / "yearly", found

    return best


def _round(value, digits=2):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def summarise(district, geometry=None):
    folder = Path(PROCESSED_ROOT) / district
    master = folder / "ndvi.tif"
    if not master.exists():
        raise AreaError(f"No data for district: {district}")

    with rasterio.open(master) as src:
        crs = src.crs

    area = _area_shape(district, geometry, crs)
    reference, cell_m2 = _values(master, area)

    if reference is None or reference.size == 0:
        raise AreaError("The area is outside this district's data.")

    area_m2 = float(reference.size) * cell_m2
    result = {
        "district": district,
        "scope": "drawn area" if geometry else "district",
        "area_km2": round(area_m2 / 1e6, 2),
        "vegetation": {"mean_ndvi": _round(reference.mean(), 3)},
    }

    # ---------- Heat ----------
    lst, _ = _values(folder / "lst.tif", area)
    if lst is not None and lst.size:
        result["heat"] = {
            "mean_lst_c": _round(lst.mean(), 1),
            "p90_lst_c": _round(np.percentile(lst, 90), 1),
            "max_lst_c": _round(lst.max(), 1),
            "note": "Mid-morning summer surface temperature, latest three years. Not air temperature.",
        }

    sensitivity, _ = _values(folder / "heat_sensitivity.tif", area)
    if sensitivity is not None and sensitivity.size:
        result.setdefault("heat", {})["mean_warming_if_paved_c"] = _round(sensitivity.mean(), 2)

    # ---------- Trees and buildings ----------
    trees, tree_cell = _values(folder / "tree_height.tif", area)
    if trees is not None and trees.size:
        canopy = trees > 0
        result["trees"] = {
            "canopy_pct": _round(100 * canopy.mean(), 1),
            "canopy_km2": _round(canopy.sum() * tree_cell / 1e6, 2),
            "mean_height_m": _round(trees[canopy].mean(), 1) if canopy.any() else None,
        }

    roofs, _ = _values(folder / "buildings.tif", area)
    if roofs is not None and roofs.size:
        result["buildings"] = {
            "roof_cover_pct": _round(100 * roofs.mean(), 1),
            "note": "Share of the area under a detected roof.",
        }

    # ---------- Land cover ----------
    cover, _ = _values(folder / "landcover.tif", area)
    if cover is not None and cover.size:
        codes, counts = np.unique(cover.astype("int32"), return_counts=True)
        shares = sorted(
            (
                {"name": LANDCOVER_NAMES.get(int(code), str(code)), "pct": round(100 * count / cover.size, 1)}
                for code, count in zip(codes, counts)
                if code != 0
            ),
            key=lambda item: -item["pct"],
        )
        result["landcover"] = [item for item in shares if item["pct"] >= 0.5]

    # ---------- Water and flood ----------
    flood, flood_cell = _values(folder / "flood.tif", area)
    if flood is not None and flood.size:
        classes = []
        lower = -float("inf")
        for name, upper in FLOOD_CLASSES:
            classes.append({
                "name": name,
                "pct": round(100 * float(((flood >= lower) & (flood < upper)).mean()), 1),
            })
            lower = upper

        result["flood"] = {
            "classes": classes,
            "flood_prone_pct": round(classes[2]["pct"] + classes[3]["pct"], 1),
            "note": "Screening index. Flood-prone means the high and very high classes.",
        }

    # Water today, from the district water layer.
    water_now, _ = _values(folder / "water.tif", area)
    if water_now is not None and water_now.size:
        result["water_now"] = {
            "cover_pct": round(100 * float((water_now > 0).mean()), 1),
            "source": "Satellite water index",
        }

    lost, lost_cell = _values(folder / "water_lost.tif", area)
    occurrence, occurrence_cell = _values(folder / "water_occurrence.tif", area)
    if lost is not None and occurrence is not None:
        result["water"] = {
            "recorded_water_km2": _round((occurrence > 0).sum() * occurrence_cell / 1e6, 2),
            "lost_water_km2": _round((lost > 0).sum() * lost_cell / 1e6, 2),
            "note": "Recorded since 1984. Lost water is water that has become land.",
        }

    # ---------- Change over time ----------
    yearly = _yearly_folder(district, area)
    if yearly is not None:
        years = sorted(int(path.stem.split("_")[1]) for path in yearly.glob("ndvi_*.tif"))
        series = []

        for year in years:
            row = {"year": year}
            for key in YEARLY:
                values, _ = _values(yearly / f"{key}_{year}.tif", area)
                row[key] = _round(values.mean(), 3) if values is not None and values.size else None

            looks, _ = _values(yearly / f"looks_{year}.tif", area)
            row["clear_looks"] = _round(looks.mean(), 1) if looks is not None and looks.size else None
            series.append(row)

        result["change"] = {
            "years": series,
            "labels": YEARLY,
            "note": (
                "Each year is one summer composite at 30 m. A year built from few clear looks "
                "is less reliable; the count is shown with it."
            ),
        }

    return result


def _land_shares(folder, area):
    """How much of the area each kind of land takes up, 0 to 1."""
    landcover, _ = _values(folder / "landcover.tif", area)
    trees, _ = _values(folder / "tree_height.tif", area)
    roofs, _ = _values(folder / "buildings.tif", area)

    if landcover is None or not landcover.size or trees is None or roofs is None:
        raise AreaError("No land cover data for this district.")

    water = float(np.isin(landcover, WATER_CODES).mean())
    built = float((landcover == BUILT_CODE).mean())
    canopy = float((trees > 0).mean()) if trees.size else 0.0
    roof = float(roofs.mean()) if roofs.size else 0.0

    return {
        "open": max(0.0, 1.0 - water - built - canopy),
        "roofs": min(1.0, roof),
        "unbuilt": max(0.0, 1.0 - water - built),
    }


def what_if(district, geometry, change, share):
    """
    Estimate how a change to part of a drawn area moves its surface
    temperature. `share` is how much of the land that could take the
    change actually gets it, 0 to 1.
    """
    if change not in WHAT_IFS:
        raise AreaError(f"Unknown change: {change}")
    if not geometry:
        raise AreaError("Draw an area first.")

    folder = Path(PROCESSED_ROOT) / district
    master = folder / "ndvi.tif"
    if not master.exists():
        raise AreaError(f"No data for district: {district}")

    with rasterio.open(master) as src:
        crs = src.crs

    area = _area_shape(district, geometry, crs)
    if area.area / 1e6 > WHAT_IF_MAX_KM2:
        raise AreaError(f"Draw an area of {WHAT_IF_MAX_KM2:.0f} km² or less for a what-if.")

    option = WHAT_IFS[change]
    share = min(1.0, max(0.0, float(share)))
    available = _land_shares(folder, area)[option["land"]]

    if share <= 0 or available <= 0:
        raise AreaError(f"This area has no {LAND_NAMES[option['land']].split(':')[0]} to change.")

    try:
        # The share is of the land that can take the change, cell by cell.
        result = thermal.run_scenarios(
            {"change": [(area, option["surface"], share, True)]},
            district=district,
            focus=area,
        )
    except thermal.ThermalUnavailable as exc:
        raise AreaError(str(exc)) from exc

    def picked(zone):
        before, after = result["scenarios"]["existing"][zone], result["scenarios"]["change"][zone]
        if before is None or after is None:
            return None
        return {
            "area_ha": after["area_ha"],
            "now_c": before["observed_lst_c"],
            "after_c": after["estimated_lst_c"],
            "change_c": after["mean_change_c"],
            "largest_cooling_c": after["min_change_c"],
            "largest_warming_c": after["max_change_c"],
            "noticeably_cooler_ha": after["area_noticeably_cooler_ha"],
            "noticeably_warmer_ha": after["area_noticeably_warmer_ha"],
            "canopy_pct_now": before["canopy_pct"],
            "canopy_pct_after": after["canopy_pct"],
        }

    inside = picked("footprint")
    if inside is None:
        raise AreaError("No temperature data for this area.")

    return {
        "change": change,
        "label": option["label"],
        "share": round(share, 2),
        "land": LAND_NAMES[option["land"]],
        "available_pct": round(100 * available, 1),
        "changed_ha": round(inside["area_ha"] * share * available, 2),
        "inside": inside,
        "around": picked("impact_zone"),
        "around_m": result["impact_zone_m"],
        "method": {
            **result["method"],
            "spread": (
                "The change is spread evenly over the land that can take it rather "
                "than placed on particular plots, so this is an estimate of scale, "
                "not a design."
            ),
        },
    }


@lru_cache(maxsize=1)
def _district_shapes():
    """Every district outline in WGS84, read once."""
    shapes = {}
    for path in sorted((Path(PROJECT_ROOT) / "districts-geojson").glob("*.geojson")):
        frame = gpd.read_file(path)
        if frame.crs is None:
            frame = frame.set_crs("EPSG:4326")
        shapes[path.stem] = frame.to_crs("EPSG:4326").geometry.union_all()
    return shapes


def _district_at(lat, lng):
    """The district holding a point, preferring one with the full set of layers."""
    point = Point(lng, lat)
    holding = [code for code, outline in _district_shapes().items() if outline.contains(point)]
    holding = [code for code in holding if (Path(PROCESSED_ROOT) / code / "ndvi.tif").exists()]

    for code in holding:
        if (Path(PROCESSED_ROOT) / code / "lst.tif").exists():
            return code
    return holding[0] if holding else None


def _reading(summary):
    """The summary of an area as plain sentences, most telling first."""
    lines = []

    water_pct = sum(
        item["pct"] for item in summary.get("landcover", []) if item["name"] in ("Water", "Wetland")
    )
    mostly_water = water_pct >= MOSTLY_WATER_PCT
    if mostly_water:
        lines.append(
            f"{water_pct:.0f}% of the area is open water or wetland, so the vegetation "
            "index says little about the land here."
        )

    rows = [row for row in summary.get("change", {}).get("years", []) if row.get("ndvi") is not None]
    if len(rows) >= 6 and not mostly_water:
        early, late = rows[:3], rows[-3:]
        then = f"{early[0]['year']} to {early[-1]['year']}"
        now = f"{late[0]['year']} to {late[-1]['year']}"

        def mean(group, key):
            values = [row[key] for row in group if row.get(key) is not None]
            return sum(values) / len(values) if values else None

        before, after = mean(early, "ndvi"), mean(late, "ndvi")
        if before and after and before > 0:
            moved = 100 * (after - before) / before
            figures = f"the summer vegetation index averaged {before:.2f} in {then} and {after:.2f} in {now}"
            if abs(moved) < STEADY_VEGETATION_PCT:
                lines.append(f"Vegetation has held steady: {figures}.")
            else:
                lines.append(f"Vegetation {'fell' if moved < 0 else 'rose'} {abs(moved):.0f}%: {figures}.")

        before, after = mean(early, "ndbi"), mean(late, "ndbi")
        if before is not None and after is not None and abs(after - before) >= STEADY_BUILT_UP:
            lines.append(
                f"The built-up index {'rose' if after > before else 'fell'} between {then} and {now}, "
                f"a sign of {'more' if after > before else 'less'} hard surface."
            )

    heat = summary.get("heat", {})
    if heat.get("mean_lst_c") is not None:
        lines.append(f"Summer surface temperature averages {heat['mean_lst_c']:.1f} °C.")

    trees = summary.get("trees", {})
    if trees.get("canopy_pct") is not None:
        lines.append(f"Tree canopy covers {trees['canopy_pct']:.0f}% of the area.")

    flood = summary.get("flood", {})
    if flood.get("flood_prone_pct"):
        lines.append(f"{flood['flood_prone_pct']:.0f}% is flood-prone on the screening index.")

    lost_ha = 100 * (summary.get("water", {}).get("lost_water_km2") or 0.0)
    if lost_ha >= 0.1:
        lines.append(f"{lost_ha:.1f} ha that was recorded as water since 1984 is now land.")

    return lines


def around(lat, lng, radius_m=AROUND_RADIUS_M):
    """What the layers show within a radius of a point."""
    lat, lng = float(lat), float(lng)
    district = _district_at(lat, lng)
    if district is None:
        raise AreaError("No data for this place.")

    with rasterio.open(Path(PROCESSED_ROOT) / district / "ndvi.tif") as src:
        crs = src.crs

    circle = (
        gpd.GeoSeries([Point(lng, lat)], crs="EPSG:4326")
        .to_crs(crs).buffer(radius_m).to_crs("EPSG:4326").iloc[0]
    )

    summary = summarise(district, mapping(circle))
    summary["scope"] = f"within {radius_m:.0f} m"
    summary["radius_m"] = radius_m
    summary["reading"] = _reading(summary) or [
        "No year-by-year data for this district."
    ]
    summary["caution"] = (
        "This is what the satellite record shows around the place named in the "
        "report. It does not confirm or refute the report, and the place itself "
        "was taken from the text, so it may be off."
    )
    return summary


def register_area_routes(app):
    """Register the /api/area routes: environment, what-if and around."""
    from flask import jsonify, request

    @app.post("/api/area/around")
    def area_around():
        payload = request.get_json(silent=True) or {}

        try:
            return jsonify(around(payload.get("lat"), payload.get("lng")))
        except (AreaError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc) or "A place is required."}), 400

    @app.post("/api/area/what-if")
    def area_what_if():
        payload = request.get_json(silent=True) or {}

        try:
            return jsonify(what_if(
                str(payload.get("district", "")).strip(),
                payload.get("geometry"),
                str(payload.get("change", "")),
                payload.get("share", 0.5),
            ))
        except (AreaError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/area/environment")
    def area_environment():
        payload = request.get_json(silent=True) or {}
        district = str(payload.get("district", "")).strip()

        if not district:
            return jsonify({"error": "District is required."}), 400

        try:
            return jsonify(summarise(district, payload.get("geometry")))
        except AreaError as exc:
            return jsonify({"error": str(exc)}), 400
