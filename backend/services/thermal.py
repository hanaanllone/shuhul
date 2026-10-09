"""
Shuhul thermal scenarios.

Turns a change on the ground into an estimated change in summer surface
temperature, using the district model fitted by
backend/scripts/build_thermal_model.py.

A scenario is a list of changes. Each change is a shape and the surface
it becomes:

    road        new paved road
    built       buildings
    tree        tree canopy at maturity
    shrub       shrubs or grass
    crop        cropland or orchard floor
    green_roof  planted roof on an existing building

Every result is a modelled estimate. The model's error on parts of the
district it was not trained on is returned with each result and has to
be shown next to it.
"""

from functools import lru_cache
from pathlib import Path
import json

import joblib
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds
from scipy import ndimage
from shapely.geometry import box
from shapely.ops import unary_union

try:
    from ..config import PROCESSED_ROOT
except ImportError:
    from config import PROCESSED_ROOT


IMPACT_ZONE_M = 300.0
NOTICEABLE_CHANGE_C = 0.25
COVERAGE_SUPERSAMPLE = 3

# Surface features a change overwrites. Everything else about a cell
# (terrain, distance to water) stays as it is.
SURFACE_FEATURES = [
    "ndvi", "canopy_share", "canopy_height", "roof_share",
    "built_share", "tree_share", "crop_share", "grass_share",
]

# A green roof changes how green the roof is, not what the cell is.
GREEN_ROOF_FEATURES = ["ndvi"]


class ThermalUnavailable(Exception):
    """No fitted thermal model covers the requested place."""


# ------------------------------------------------------------
# MODEL LOADING
# ------------------------------------------------------------

@lru_cache(maxsize=8)
def _load(district):
    folder = Path(PROCESSED_ROOT) / district / "thermal"
    summary = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    model = joblib.load(folder / "model.joblib")
    return folder, summary, model


def _covering_district(bounds, district=None):
    """
    Find a fitted model whose grid contains the bounds. The district that
    was asked for is tried first, then any other, so a city nested inside
    a larger district can use that district's model.
    """
    candidates = []
    if district:
        candidates.append(Path(PROCESSED_ROOT) / district)
    candidates.extend(sorted(Path(PROCESSED_ROOT).glob("*")))

    for folder in candidates:
        features = folder / "thermal" / "features.tif"
        if not features.exists():
            continue
        with rasterio.open(features) as src:
            if box(*src.bounds).contains(box(*bounds)):
                return folder.name

    raise ThermalUnavailable("No thermal model covers this location.")


def model_summary(district):
    """Model description for the 'how was this calculated' panel."""
    _, summary, _ = _load(district)
    return {
        "target": summary["target"],
        "features": summary["features"],
        "directions": summary["directions"],
        "metrics": summary["metrics"],
        "typical_surfaces": summary["typical_surfaces"],
    }


# ------------------------------------------------------------
# GRID HELPERS
# ------------------------------------------------------------

def _read_window(folder, summary, bounds):
    """Read every feature band and the observed temperature for a window."""
    with rasterio.open(folder / "features.tif") as src:
        window = from_bounds(*bounds, transform=src.transform)
        window = window.round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, src.width, src.height))

        stack = src.read(window=window).astype("float32")
        stack[stack == src.nodata] = np.nan
        transform = src.window_transform(window)
        crs = src.crs

    features = {name: stack[i] for i, name in enumerate(summary["features"])}

    with rasterio.open(folder.parent / "yearly" / "lst_current.tif") as src:
        observed = src.read(1, window=window).astype("float32")
        observed[observed == src.nodata] = np.nan

    return features, observed, transform, crs


def _coverage(geometry, shape, transform):
    """Share of each cell covered by a geometry, 0-1."""
    n = COVERAGE_SUPERSAMPLE
    fine = rasterize(
        [(geometry, 1)],
        out_shape=(shape[0] * n, shape[1] * n),
        transform=transform * Affine.scale(1 / n),
        fill=0,
        dtype="uint8",
    )
    return fine.reshape(shape[0], n, shape[1], n).mean(axis=(1, 3)).astype("float32")


def _neighbourhood_mean(array, cells):
    valid = np.isfinite(array)
    total = ndimage.uniform_filter(np.where(valid, array, 0.0), cells, mode="nearest")
    weight = ndimage.uniform_filter(valid.astype("float32"), cells, mode="nearest")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = total / weight
    out[weight < 0.05] = np.nan
    return out.astype("float32")


def _predict(model, summary, features):
    shape = next(iter(features.values())).shape
    X = np.column_stack([features[name].ravel() for name in summary["features"]])
    return model.predict(X).reshape(shape).astype("float32")


def _apply(features, summary, changes, transform):
    """Return a copy of the features with the changes painted in."""
    shape = features["ndvi"].shape
    changed = {name: array.copy() for name, array in features.items()}
    typical = summary["typical_surfaces"]

    for geometry, surface in changes:
        if surface not in typical:
            raise ValueError(f"Unknown surface type: {surface}")

        share = _coverage(geometry, shape, transform)
        names = GREEN_ROOF_FEATURES if surface == "green_roof" else SURFACE_FEATURES

        for name in names:
            target = typical[surface][name]
            changed[name] = (1 - share) * changed[name] + share * target

    for name, (source, cells) in summary["neighbourhood"].items():
        changed[name] = _neighbourhood_mean(changed[source], int(cells))

    return changed


# ------------------------------------------------------------
# SCENARIOS
# ------------------------------------------------------------

def _zone_stats(zone, observed, baseline, scenario, features, cell_ha):
    delta = (scenario - baseline)[zone]
    delta = delta[np.isfinite(delta)]

    if delta.size == 0:
        return None

    observed_mean = float(np.nanmean(observed[zone])) if np.isfinite(observed[zone]).any() else None
    mean_delta = float(delta.mean())

    return {
        "area_ha": round(float(zone.sum()) * cell_ha, 2),
        "observed_lst_c": None if observed_mean is None else round(observed_mean, 2),
        "estimated_lst_c": None if observed_mean is None else round(observed_mean + mean_delta, 2),
        "mean_change_c": round(mean_delta, 2),
        "max_change_c": round(float(delta.max()), 2),
        "min_change_c": round(float(delta.min()), 2),
        "heat_added_degree_ha": round(float(delta[delta > 0].sum()) * cell_ha, 2),
        "heat_removed_degree_ha": round(abs(float(delta[delta < 0].sum())) * cell_ha, 2),
        "area_noticeably_warmer_ha": round(float((delta >= NOTICEABLE_CHANGE_C).sum()) * cell_ha, 2),
        "area_noticeably_cooler_ha": round(float((delta <= -NOTICEABLE_CHANGE_C).sum()) * cell_ha, 2),
        "canopy_pct": round(100 * float(np.nanmean(features["canopy_share"][zone])), 1),
        "ndvi": round(float(np.nanmean(features["ndvi"][zone])), 3),
        "built_up_pct": round(100 * float(np.nanmean(features["built_share"][zone])), 1),
    }


def run_scenarios(scenarios, district=None, focus=None):
    """
    Estimate the thermal effect of one or more scenarios over the same area.

    scenarios: {name: [(geometry, surface), ...]} with geometries in the
               district's projected CRS (EPSG:32643).
    focus:     geometry whose surroundings are reported on. Defaults to
               everything any scenario touches.

    Returns per-scenario statistics for the footprint and for the
    surrounding impact zone, plus the grids needed to map the change.
    """
    geometries = [geometry for changes in scenarios.values() for geometry, _ in changes]
    if not geometries:
        raise ValueError("A scenario needs at least one change.")

    footprint = focus if focus is not None else unary_union(geometries)
    zone_geometry = footprint.buffer(IMPACT_ZONE_M)

    # The far neighbourhood window has to be complete around the zone.
    probe = _covering_district(zone_geometry.bounds, district)
    folder, summary, model = _load(probe)
    cell = float(summary["cell_size_m"])
    margin = (max(int(c) for _, c in summary["neighbourhood"].values()) // 2 + 2) * cell

    everything = unary_union(geometries + [zone_geometry]).buffer(margin)
    features, observed, transform, crs = _read_window(folder, summary, everything.bounds)

    shape = observed.shape
    cell_ha = cell * cell / 10_000.0
    in_footprint = _coverage(footprint, shape, transform) > 0
    in_zone = _coverage(zone_geometry, shape, transform) > 0

    baseline = _predict(model, summary, features)

    results = {
        "existing": {
            "footprint": _zone_stats(in_footprint, observed, baseline, baseline, features, cell_ha),
            "impact_zone": _zone_stats(in_zone, observed, baseline, baseline, features, cell_ha),
        }
    }
    grids = {}

    for name, changes in scenarios.items():
        changed = _apply(features, summary, changes, transform)
        predicted = _predict(model, summary, changed)

        results[name] = {
            "footprint": _zone_stats(in_footprint, observed, baseline, predicted, changed, cell_ha),
            "impact_zone": _zone_stats(in_zone, observed, baseline, predicted, changed, cell_ha),
        }
        grids[name] = np.where(in_zone, predicted - baseline, np.nan).astype("float32")

    return {
        "model_district": probe,
        "impact_zone_m": IMPACT_ZONE_M,
        "scenarios": results,
        "method": {
            "what": (
                "Modelled change in mid-morning summer surface temperature. "
                "Not air temperature, and not a measurement."
            ),
            "model": "Gradient-boosted model of Landsat surface temperature on land cover, canopy, buildings, water and terrain",
            "held_out_error_c": summary["metrics"]["rmse_c"],
            "held_out_mean_error_c": summary["metrics"]["mae_c"],
            "validation": summary["metrics"]["validation"],
            "tree_note": "Tree planting is credited at mature canopy, which takes years to reach.",
            "degree_ha": "Temperature change in deg C multiplied by the area it applies to, in hectares.",
        },
        "grid": {"transform": transform, "crs": crs, "change_c": grids},
    }


def construction_scenarios(corridor, mitigation=None, district=None, construction="road"):
    """
    Existing / after construction / after mitigation for one corridor.

    corridor:   polygon of the construction corridor, projected CRS.
    mitigation: [(geometry, surface)] for planned green infrastructure.
    """
    surface = "road" if construction in {"road", "bridge", "flyover"} else "built"
    scenarios = {"after_construction": [(corridor, surface)]}

    if mitigation:
        scenarios["after_mitigation"] = [(corridor, surface)] + list(mitigation)

    return run_scenarios(scenarios, district=district, focus=corridor)


def write_change_raster(result, name, path):
    """Save one scenario's temperature change as a GeoTIFF for mapping."""
    grid = result["grid"]
    change = grid["change_c"][name]
    data = np.where(np.isfinite(change), change, -9999.0).astype("float32")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        dtype="float32",
        count=1,
        width=data.shape[1],
        height=data.shape[0],
        crs=grid["crs"],
        transform=grid["transform"],
        nodata=-9999.0,
        compress="deflate",
    ) as dst:
        dst.write(data, 1)

    return path


def public(result):
    """Drop the grids, leaving only what can be sent as JSON."""
    return {key: value for key, value in result.items() if key != "grid"}
