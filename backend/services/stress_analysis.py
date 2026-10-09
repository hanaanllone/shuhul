"""
Tshaai Ecological Stress — identification only.

Generates a zone-level GeoJSON layer. It does not recommend interventions
and does not change route planning.

Stress dimensions:
  low NDVI       -> higher stress
  low canopy     -> higher stress
  high LST       -> higher stress (when LST exists)
  high buildings -> higher stress
  low NDWI       -> higher stress

Indicators are normalized relative to the analysed district using the
10th/90th percentiles. This is a screening/index layer, not a claim that
the resulting score is an absolute ecological measurement.
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
except ImportError:
    from config import PROCESSED_ROOT, OUTPUT_ROOT


ZONE_SIZE_M = 500.0
MIN_VALID_PIXELS = 25

WEIGHTS = {
    "ndvi": 0.25,
    "canopy": 0.20,
    "lst": 0.25,
    "buildings": 0.20,
    "ndwi": 0.10,
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
            return vrt.read(1).astype("float32")


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
    canopy_path = find_raster(directory, "canopy", "chm")
    lst_path = find_raster(directory, "lst", "land_surface_temperature")
    buildings_path = find_buildings(directory)

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
    buildings = building_grid(buildings_path, shape, transform, crs)

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

            for key, weight in WEIGHTS.items():
                if key not in stress:
                    continue
                values = stress[key][row0:row1, col0:col1]
                usable = values[valid & np.isfinite(values)]
                if usable.size:
                    scores.append(float(np.mean(usable)))
                    weights.append(weight)

            if not scores:
                continue

            score = float(np.average(scores, weights=weights))

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

            polygon = zone_polygon(row0, row1, col0, col1, transform, crs)

            features.append({
                "type": "Feature",
                "geometry": mapping(polygon),
                "properties": {
                    "zone_id": f"Zone {zone_number}",
                    "stress_level": level,
                    "stress_score": round(score, 3),
                    "mean_ndvi": round(mean_in(ndvi), 4) if mean_in(ndvi) is not None else None,
                    "mean_ndwi": round(mean_in(ndwi), 4) if mean_in(ndwi) is not None else None,
                    "canopy_cover_pct": round(canopy_pct, 2) if canopy_pct is not None else None,
                    "built_up_density_pct": round(building_pct, 2) if building_pct is not None else None,
                    "mean_lst": round(mean_in(lst), 2) if lst_available else None,
                },
            })
            zone_number += 1

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
    }


def register_stress_routes(app):
    @app.get("/api/stress/<district>")
    def ecological_stress(district):
        try:
            return app.response_class(
                response=json.dumps(generate_stress_data(district)),
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
