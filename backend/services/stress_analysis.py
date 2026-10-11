"""
Shuhul Ecological Stress and greening priority.

Generates a zone-level GeoJSON layer. It does not change route planning.

Stress dimensions:
  low NDVI       -> higher stress
  low canopy     -> higher stress
  high LST       -> higher stress (when LST exists)
  high buildings -> higher stress
  low NDWI       -> higher stress

Indicators are normalized relative to the analysed district using the
10th/90th percentiles. This is a screening/index layer, not a claim that
the resulting score is an absolute ecological measurement.

Greening priority ranks the same zones for planting: little tree canopy,
a hot surface, busy roads and dense building push a zone up. Busy roads
stand in for traffic pollution, because the air quality data available
here is one modelled value for the whole district.
"""

from pathlib import Path
import json
import sys

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from shapely.geometry import box, mapping
from shapely.ops import transform as shapely_transform
from pyproj import Transformer

try:
    from ..config import PROCESSED_ROOT, OUTPUT_ROOT
    from .jsonsafe import finite as json_safe
except ImportError:
    from config import PROCESSED_ROOT, OUTPUT_ROOT
    from jsonsafe import finite as json_safe


ZONE_SIZE_M = 500.0
MIN_VALID_PIXELS = 25

WEIGHTS = {
    "ndvi": 0.25,
    "canopy": 0.20,
    "lst": 0.25,
    "buildings": 0.20,
    "ndwi": 0.10,
}

# What a high score on each indicator means, in a planner's words.
DRIVER_LABELS = {
    "ndvi": "Low vegetation",
    "canopy": "Low tree canopy",
    "lst": "High surface temperature",
    "buildings": "High built-up density",
    "ndwi": "Low surface moisture",
}
DRIVER_MIN_SCORE = 0.5
MAX_DRIVERS = 3

# Roads that carry through traffic. Their share of a zone stands in for
# exposure to traffic pollution.
MAIN_ROADS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
}

# WorldCover classes where planting is not the answer: open water and wetland.
WATER_CLASSES = (80, 90)
BUILT_CLASS = 50
MOSTLY_WATER_PCT = 50.0

# Flood index at or above this is the high and very high classes.
FLOOD_PRONE_FROM = 0.65

# Greening priority: (zone property, weight, True when a high value raises
# priority, what it means in a planner's words).
# Buildings where heat matters more because of who uses them, by the tag
# they carry on the named buildings layer.
SENSITIVE_KINDS = {
    "school": "education",
    "kindergarten": "education",
    "college": "education",
    "university": "education",
    "hospital": "health",
    "clinic": "health",
}
MAX_SITE_NAMES = 4

# The highest-ranked 15% of zones are "high", the next 35% "moderate".
GREENING_HIGH_SHARE = 0.15
GREENING_MODERATE_SHARE = 0.50
# A factor is named as a reason when the zone beats this share of zones on it.
GREENING_REASON_MIN = 0.7

GREENING_FACTORS = {
    "canopy": ("canopy_cover_pct", 0.35, False, "Little tree canopy"),
    "heat": ("mean_lst", 0.25, True, "Hot surface"),
    "roads": ("main_road_pct", 0.25, True, "Busy roads"),
    "built": ("built_up_density_pct", 0.15, True, "Densely built"),
}


def find_raster(directory, *names):
    for name in names:
        for suffix in (".tif", ".tiff"):
            path = directory / f"{name}{suffix}"
            if path.exists():
                return path
    return None


def find_buildings(directory):
    for name in ("buildings.gpkg", "building.gpkg", "buildings.geojson"):
        path = directory / name
        if path.exists():
            return path
    return None


def read_master(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float32")
        return arr, src.transform, src.crs, src.nodata


def read_aligned(path, shape, transform, crs):
    with rasterio.open(path) as src:
        with WarpedVRT(
            src,
            crs=crs,
            transform=transform,
            width=shape[1],
            height=shape[0],
            resampling=Resampling.bilinear,
        ) as vrt:
            data = vrt.read(1).astype("float32")
            if vrt.nodata is not None:
                data[data == vrt.nodata] = np.nan
            return data


def finite(arr):
    return np.isfinite(arr)


def percentile_bounds(arr):
    vals = arr[np.isfinite(arr)]
    if vals.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(vals, [10, 90])
    return float(lo), float(hi if hi > lo else lo + 1e-6)


def low_is_stress(arr, lo, hi):
    return np.clip((hi - arr) / (hi - lo), 0, 1)


def high_is_stress(arr, lo, hi):
    return np.clip((arr - lo) / (hi - lo), 0, 1)


def building_grid(path, shape, transform, crs):
    if path is None:
        return np.full(shape, np.nan, dtype="float32")

    try:
        gdf = gpd.read_file(path)
        if gdf.empty:
            return np.zeros(shape, dtype="float32")
        if gdf.crs is None:
            gdf = gdf.set_crs(crs)
        gdf = gdf.to_crs(crs)
        gdf = gdf[gdf.geometry.notna()]
        if gdf.empty:
            return np.zeros(shape, dtype="float32")

        return rasterize(
            [(geom, 1) for geom in gdf.geometry],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype("float32")
    except Exception:
        return np.full(shape, np.nan, dtype="float32")


def main_road_grid(path, shape, transform, crs):
    """1 where a main road passes, on the district grid."""
    if path is None:
        return np.full(shape, np.nan, dtype="float32")

    try:
        roads = gpd.read_file(path)
        if roads.crs is None:
            roads = roads.set_crs(crs)
        roads = roads.to_crs(crs)
        roads = roads[roads["highway"].isin(MAIN_ROADS) & roads.geometry.notna()]
        if roads.empty:
            return np.zeros(shape, dtype="float32")

        return rasterize(
            [(geom, 1) for geom in roads.geometry],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype("float32")
    except Exception:
        return np.full(shape, np.nan, dtype="float32")


def class_grid(path, shape, transform, crs):
    """Land cover classes on the district grid, or None without the layer."""
    if path is None:
        return None

    with rasterio.open(path) as src:
        with WarpedVRT(
            src, crs=crs, transform=transform,
            width=shape[1], height=shape[0],
            resampling=Resampling.nearest,
        ) as vrt:
            return vrt.read(1)


def water_grid(classes, water_path, shape, transform, crs):
    """1 where the land is open water or wetland."""
    if classes is not None:
        return np.isin(classes, WATER_CLASSES).astype("float32")

    if water_path is not None:
        water = read_aligned(water_path, shape, transform, crs)
        return (np.nan_to_num(water) > 0.5).astype("float32")

    return np.zeros(shape, dtype="float32")


def standing(values, value, high_raises):
    """
    Where a zone stands among the district's zones on one factor, 0 to 1:
    the share of zones it beats. `values` is sorted ascending.
    """
    others = len(values) - 1
    if others < 1:
        return 0.0
    if high_raises:
        beaten = np.searchsorted(values, value, side="left")
    else:
        beaten = len(values) - np.searchsorted(values, value, side="right")
    return float(beaten) / others


def add_greening_priority(features):
    """
    Rank zones for planting. Each factor is the zone's standing among the
    district's zones, and the factors are combined by weight. Zones that
    are mostly water are left out. Levels are shares of the ranking, so
    "high" always means the top of this district's list.
    """
    for feature in features:
        zone = feature["properties"]
        zone["greening_priority"] = None
        zone["greening_level"] = "NOT_APPLICABLE"
        zone["greening_rank"] = None
        zone["greening_factors"] = {}
        zone["greening_reasons"] = []

    # Canopy is the point of the index: no canopy figure, no priority.
    candidates = [
        feature["properties"]
        for feature in features
        if (feature["properties"].get("water_pct") or 0.0) < MOSTLY_WATER_PCT
        and feature["properties"].get("canopy_cover_pct") is not None
    ]

    spread = {}
    for key, (field, _, _, _) in GREENING_FACTORS.items():
        values = np.sort(np.array(
            [zone[field] for zone in candidates if zone.get(field) is not None],
            dtype="float64",
        ))
        # A factor that is the same everywhere cannot rank anything.
        if values.size >= 2 and values[-1] > values[0]:
            spread[key] = values

    if "canopy" not in spread:
        return 0

    for zone in candidates:
        parts = {}
        for key, (field, weight, high_raises, _) in GREENING_FACTORS.items():
            if key in spread and zone.get(field) is not None:
                parts[key] = (standing(spread[key], zone[field], high_raises), weight)

        score = float(np.average(
            [value for value, _ in parts.values()],
            weights=[weight for _, weight in parts.values()],
        ))
        ranked = sorted(
            parts.items(), key=lambda item: item[1][0] * item[1][1], reverse=True
        )

        zone["greening_priority"] = round(score, 3)
        zone["greening_factors"] = {
            key: round(value, 3) for key, (value, _) in parts.items()
        }
        zone["greening_reasons"] = [
            GREENING_FACTORS[key][3]
            for key, (value, _) in ranked
            if value >= GREENING_REASON_MIN
        ][:MAX_DRIVERS]

    scored = sorted(candidates, key=lambda zone: zone["greening_priority"], reverse=True)
    for rank, zone in enumerate(scored, start=1):
        share = rank / len(scored)
        zone["greening_rank"] = rank
        zone["greening_level"] = (
            "HIGH" if share <= GREENING_HIGH_SHARE
            else "MODERATE" if share <= GREENING_MODERATE_SHARE
            else "LOW"
        )

    return len(scored)


def sensitive_sites(path, transform, crs, step_x, step_y):
    """
    Schools, colleges, hospitals and clinics among the named buildings,
    grouped by the zone each stands in: {(zone row, zone column): counts}.
    """
    by_zone = {}
    if path is None:
        return by_zone

    try:
        frame = gpd.read_file(path)
    except Exception:
        return by_zone

    if "amenity" not in frame.columns or "building" not in frame.columns:
        return by_zone
    if frame.crs is None:
        frame = frame.set_crs(crs)
    frame = frame.to_crs(crs)

    for _, row in frame.iterrows():
        group = SENSITIVE_KINDS.get(row["amenity"]) or SENSITIVE_KINDS.get(row["building"])
        if group is None or row.geometry is None or row.geometry.is_empty:
            continue

        centre = row.geometry.centroid
        col, line = ~transform * (centre.x, centre.y)
        if col < 0 or line < 0:
            continue

        entry = by_zone.setdefault(
            (int(line) // step_y, int(col) // step_x),
            {"education": 0, "health": 0, "names": []},
        )
        entry[group] += 1

        name = row.get("name")
        if isinstance(name, str) and name.strip() and name not in entry["names"]:
            entry["names"].append(name.strip())

    return by_zone


def zone_polygon(row0, row1, col0, col1, transform, crs):
    """Return the zone polygon in WGS84 for Leaflet/GeoJSON display."""
    x0, y1 = transform * (col0, row0)
    x1, y0 = transform * (col1, row1)
    polygon = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    if crs is not None and str(crs) != "EPSG:4326":
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        polygon = shapely_transform(transformer.transform, polygon)

    return polygon


def generate_stress_data(district, zone_size_m=ZONE_SIZE_M):
    directory = Path(PROCESSED_ROOT) / district

    ndvi_path = find_raster(directory, "ndvi")
    ndwi_path = find_raster(directory, "ndwi")
    canopy_path = find_raster(directory, "tree_height", "canopy", "chm")
    roof_path = find_raster(directory, "buildings")
    lst_path = find_raster(directory, "lst", "land_surface_temperature")
    buildings_path = find_buildings(directory)
    roads_path = directory / "roads.gpkg"

    if ndvi_path is None:
        raise FileNotFoundError(f"NDVI raster not found for district '{district}'.")
    if ndwi_path is None:
        raise FileNotFoundError(f"NDWI raster not found for district '{district}'.")

    ndvi, transform, crs, nodata = read_master(ndvi_path)
    shape = ndvi.shape

    if nodata is not None:
        ndvi = np.where(ndvi == nodata, np.nan, ndvi)

    ndwi = read_aligned(ndwi_path, shape, transform, crs)
    canopy = (
        read_aligned(canopy_path, shape, transform, crs)
        if canopy_path else np.full(shape, np.nan, dtype="float32")
    )
    lst = (
        read_aligned(lst_path, shape, transform, crs)
        if lst_path else np.full(shape, np.nan, dtype="float32")
    )
    # Share of each cell under a roof where that layer exists, otherwise
    # the named footprints, which cover only a fraction of real buildings.
    buildings = (
        read_aligned(roof_path, shape, transform, crs)
        if roof_path
        else building_grid(buildings_path, shape, transform, crs)
    )

    main_roads = main_road_grid(
        roads_path if roads_path.exists() else None, shape, transform, crs
    )
    classes = class_grid(find_raster(directory, "landcover"), shape, transform, crs)
    water = water_grid(classes, find_raster(directory, "water"), shape, transform, crs)

    # Layers that say what building on a zone would cost. Each is optional.
    def optional(name):
        path = find_raster(directory, name)
        return read_aligned(path, shape, transform, crs) if path else None

    flood = optional("flood")
    slope = optional("slope")
    sensitivity = optional("heat_sensitivity")
    any_road = optional("roads")
    heritage = optional("heritage")
    forest = optional("forest")
    cell_ha = abs(float(transform.a) * float(transform.e)) / 10_000.0

    base_valid = finite(ndvi) & finite(ndwi)

    canopy_cover = np.where(finite(canopy), canopy > 0, np.nan).astype("float32")

    # Indicator stress rasters.
    ndvi_lo, ndvi_hi = percentile_bounds(ndvi[base_valid])
    ndwi_lo, ndwi_hi = percentile_bounds(ndwi[base_valid])

    stress = {
        "ndvi": low_is_stress(ndvi, ndvi_lo, ndvi_hi),
        "ndwi": low_is_stress(ndwi, ndwi_lo, ndwi_hi),
    }

    if np.isfinite(canopy_cover).sum():
        c_lo, c_hi = percentile_bounds(canopy_cover[np.isfinite(canopy_cover)])
        stress["canopy"] = low_is_stress(canopy_cover, c_lo, c_hi)

    if np.isfinite(buildings).sum():
        b_lo, b_hi = percentile_bounds(buildings[np.isfinite(buildings)])
        stress["buildings"] = high_is_stress(buildings, b_lo, b_hi)

    lst_available = np.isfinite(lst).sum() >= MIN_VALID_PIXELS
    if lst_available:
        l_lo, l_hi = percentile_bounds(lst[np.isfinite(lst)])
        stress["lst"] = high_is_stress(lst, l_lo, l_hi)

    pixel_x = abs(float(transform.a))
    pixel_y = abs(float(transform.e))
    step_x = max(1, int(round(zone_size_m / pixel_x)))
    step_y = max(1, int(round(zone_size_m / pixel_y)))

    sites_by_zone = sensitive_sites(buildings_path, transform, crs, step_x, step_y)

    features = []
    zone_number = 1

    for row0 in range(0, shape[0], step_y):
        row1 = min(shape[0], row0 + step_y)
        for col0 in range(0, shape[1], step_x):
            col1 = min(shape[1], col0 + step_x)

            valid = base_valid[row0:row1, col0:col1]
            if int(valid.sum()) < MIN_VALID_PIXELS:
                continue

            scores = []
            weights = []
            parts = {}

            for key, weight in WEIGHTS.items():
                if key not in stress:
                    continue
                values = stress[key][row0:row1, col0:col1]
                usable = values[valid & np.isfinite(values)]
                if usable.size:
                    scores.append(float(np.mean(usable)))
                    weights.append(weight)
                    parts[key] = (scores[-1], weight)

            if not scores:
                continue

            score = float(np.average(scores, weights=weights))

            # The indicators that push this zone's score up the most.
            ranked = sorted(
                parts.items(),
                key=lambda item: item[1][0] * item[1][1],
                reverse=True,
            )
            drivers = [
                {"key": key, "label": DRIVER_LABELS[key], "score": round(value, 3)}
                for key, (value, _) in ranked
                if value >= DRIVER_MIN_SCORE
            ][:MAX_DRIVERS]

            if score >= 0.67:
                level = "HIGH"
            elif score >= 0.34:
                level = "MODERATE"
            else:
                level = "LOW"

            def mean_in(arr):
                vals = arr[row0:row1, col0:col1]
                usable = vals[valid & np.isfinite(vals)]
                return float(np.mean(usable)) if usable.size else None

            canopy_vals = canopy_cover[row0:row1, col0:col1]
            canopy_valid = canopy_vals[valid & np.isfinite(canopy_vals)]
            canopy_pct = float(canopy_valid.mean() * 100) if canopy_valid.size else None

            building_vals = buildings[row0:row1, col0:col1]
            building_valid = building_vals[valid & np.isfinite(building_vals)]
            building_pct = float(building_valid.mean() * 100) if building_valid.size else None

            road_share = mean_in(main_roads)
            water_share = mean_in(water)

            def share_in(arr, test):
                """Percent of the zone's cells that pass a test, or None without the layer."""
                if arr is None:
                    return None
                vals = arr[row0:row1, col0:col1]
                usable = vals[valid & np.isfinite(vals)]
                return round(float(test(usable).mean()) * 100, 2) if usable.size else None

            # Open land: not water, not built-up, not under trees.
            open_ha = None
            if classes is not None and np.isfinite(canopy_vals).any():
                block = classes[row0:row1, col0:col1]
                open_cells = (
                    valid
                    & ~np.isin(block, WATER_CLASSES + (BUILT_CLASS,))
                    & (np.nan_to_num(canopy_vals, nan=1.0) == 0)
                )
                open_ha = round(float(open_cells.sum()) * cell_ha, 2)
            sites = sites_by_zone.get((row0 // step_y, col0 // step_x), {})

            polygon = zone_polygon(row0, row1, col0, col1, transform, crs)

            features.append({
                "type": "Feature",
                "geometry": mapping(polygon),
                "properties": {
                    "zone_id": f"Zone {zone_number}",
                    "stress_level": level,
                    "stress_score": round(score, 3),
                    "drivers": drivers,
                    "indicator_scores": {
                        key: round(value, 3) for key, (value, _) in parts.items()
                    },
                    "mean_ndvi": round(mean_in(ndvi), 4) if mean_in(ndvi) is not None else None,
                    "mean_ndwi": round(mean_in(ndwi), 4) if mean_in(ndwi) is not None else None,
                    "canopy_cover_pct": round(canopy_pct, 2) if canopy_pct is not None else None,
                    "built_up_density_pct": round(building_pct, 2) if building_pct is not None else None,
                    # A zone can lack a temperature reading: cloud or snow in every look.
                    "mean_lst": (
                        round(mean_in(lst), 2)
                        if lst_available and mean_in(lst) is not None else None
                    ),
                    "main_road_pct": round(road_share * 100, 2) if road_share is not None else None,
                    "water_pct": round(water_share * 100, 2) if water_share is not None else None,
                    "zone_ha": round(float(valid.sum()) * cell_ha, 2),
                    "open_land_ha": open_ha,
                    "flood_prone_pct": share_in(flood, lambda v: v >= FLOOD_PRONE_FROM),
                    "mean_slope_deg": round(mean_in(slope), 2) if slope is not None and mean_in(slope) is not None else None,
                    "warming_if_paved_c": (
                        round(mean_in(sensitivity), 2)
                        if sensitivity is not None and mean_in(sensitivity) is not None else None
                    ),
                    "road_pct": share_in(any_road, lambda v: v > 0.5),
                    "heritage_pct": share_in(heritage, lambda v: v > 0.5),
                    "forest_pct": share_in(forest, lambda v: v > 0.5),
                    "education_buildings": sites.get("education", 0),
                    "health_buildings": sites.get("health", 0),
                    "sensitive_names": sites.get("names", [])[:MAX_SITE_NAMES],
                },
            })
            zone_number += 1

    # The plain canopy height layer carries a height on every vegetated cell, so
    # only the tree cover layer can say where trees are missing.
    tree_cover_known = canopy_path is not None and canopy_path.stem == "tree_height"
    zones_ranked = add_greening_priority(features) if tree_cover_known else 0
    if not zones_ranked:
        for feature in features:
            feature["properties"].update(
                greening_priority=None, greening_level="NOT_APPLICABLE",
                greening_rank=None, greening_factors={}, greening_reasons=[],
            )

    return {
        "type": "FeatureCollection",
        "district": district,
        "zone_size_m": zone_size_m,
        "features": features,
        "methodology": {
            "weights": WEIGHTS,
            "normalization": "District-relative 10th–90th percentile scaling",
            "classification": {"LOW": "< 0.34", "MODERATE": "0.34–0.66", "HIGH": ">= 0.67"},
            "purpose": "Screening areas for ecological stress before development planning.",
        },
        "greening": {
            "available": bool(zones_ranked),
            "unavailable_reason": (
                None if zones_ranked
                else "No tree cover data for this district."
            ),
            "zones_ranked": zones_ranked,
            "weights": {key: factor[1] for key, factor in GREENING_FACTORS.items()},
            "labels": {key: factor[3] for key, factor in GREENING_FACTORS.items()},
            "scoring": (
                "Each factor is the share of the district's zones that the zone beats "
                "on it, from 0 to 1. The factors are combined by weight."
            ),
            "levels": (
                f"High is the top {GREENING_HIGH_SHARE:.0%} of ranked zones, moderate "
                f"the next {GREENING_MODERATE_SHARE - GREENING_HIGH_SHARE:.0%}, low the rest."
            ),
            "left_out": f"Zones that are {MOSTLY_WATER_PCT:.0f}% or more open water or wetland.",
            "air_note": (
                "Air quality here is one modelled value for the whole district, so it "
                "cannot tell zones apart. The share of each zone taken up by main roads "
                "stands in for exposure to traffic pollution. It is not a measurement."
            ),
            "sensitive_note": (
                "Schools, colleges, hospitals and clinics are the buildings tagged as "
                "such on OpenStreetMap. Many are not mapped, so a zone shown without "
                "one may still have one."
            ),
            "confidence": "Low. A screening index for comparing zones inside one district.",
        },
    }


def cached_stress(district):
    """
    Return the district stress layer as GeoJSON text, computing it only
    when it has not been built yet or an input layer has changed since.
    """
    directory = Path(PROCESSED_ROOT) / district
    cache = Path(OUTPUT_ROOT) / "stress" / f"{district}.geojson"

    inputs = [
        path
        for path in (
            find_raster(directory, "ndvi"),
            find_raster(directory, "ndwi"),
            find_raster(directory, "tree_height", "canopy", "chm"),
            find_raster(directory, "lst", "land_surface_temperature"),
            find_raster(directory, "buildings"),
            find_raster(directory, "landcover"),
            find_raster(directory, "flood"),
            find_raster(directory, "heat_sensitivity"),
            find_raster(directory, "forest"),
            find_raster(directory, "heritage"),
            find_raster(directory, "roads"),
            find_buildings(directory),
            directory / "roads.gpkg" if (directory / "roads.gpkg").exists() else None,
            Path(__file__),
        )
        if path is not None
    ]

    if cache.exists() and all(
        cache.stat().st_mtime >= path.stat().st_mtime for path in inputs
    ):
        return cache.read_text(encoding="utf-8")

    text = json.dumps(json_safe(generate_stress_data(district)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def register_stress_routes(app):
    @app.get("/api/stress/<district>")
    def ecological_stress(district):
        try:
            return app.response_class(
                response=cached_stress(district),
                status=200,
                mimetype="application/geo+json",
            )
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404
        except Exception as exc:
            return {"error": f"Ecological stress analysis failed: {exc}"}, 500


if __name__ == "__main__":
    district = sys.argv[1] if len(sys.argv) > 1 else "sxr"
    result = generate_stress_data(district)
    out = Path(OUTPUT_ROOT) / "stress"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{district}_stress.geojson"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Generated {path}")
    print(f"Zones: {len(result['features'])}")
