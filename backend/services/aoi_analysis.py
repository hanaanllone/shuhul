"""
Tshaai AOI / district environmental analysis.

Calculates real spatial indicators from the already processed district data:

    AREA
    MEAN NDVI
    MEAN NDWI
    CANOPY COVER
    BUILT-UP DENSITY
    WATER COVER

AOI input:
    - GeoJSON geometry / Feature / FeatureCollection
    - or Leaflet-style bounds:
        [[south, west], [north, east]]

All calculations are performed in the district's processed CRS
(EPSG:32643 in the current Tshaai pipeline).

Expected processed structure:

    processed/
        <district>/
            ndvi.tif
            ndwi.tif
            water.tif
            canopy.tif OR chm.tif
            buildings.gpkg

The module can:
    1. Precompute district_metrics.json for every available district.
    2. Analyse an arbitrary AOI sent to POST /api/aoi/analyse.
    3. Return the same metric structure to the frontend.

This module does not modify the existing route-planning / impact /
mitigation / report pipeline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask as raster_mask
from shapely.geometry import box, shape, mapping
from shapely.ops import unary_union
from pyproj import Transformer


NDWI_WATER_THRESHOLD = 0.20
CANOPY_THRESHOLD = 0.0


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    # backend/services/aoi_analysis.py -> project root is two levels up.
    return Path(__file__).resolve().parents[2]


def _processed_root() -> Path:
    try:
        from ..config import PROCESSED_ROOT
        return Path(PROCESSED_ROOT)
    except Exception:
        return _project_root() / "processed"


def _output_root() -> Path:
    try:
        from ..config import OUTPUT_ROOT
        return Path(OUTPUT_ROOT)
    except Exception:
        return _project_root() / "outputs"


PROCESSED_ROOT = _processed_root()
OUTPUT_ROOT = _output_root()


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _first_existing(folder: Path, names, required=False):
    for name in names:
        path = folder / name
        if path.exists():
            return path

    # Also support files whose names contain the requested stem.
    for path in folder.glob("*"):
        if not path.is_file():
            continue
        stem = path.stem.lower()
        for name in names:
            wanted = Path(name).stem.lower()
            if stem == wanted:
                return path

    if required:
        raise FileNotFoundError(
            f"Required AOI dataset not found in {folder}: {names}"
        )

    return None


def district_paths(district: str) -> Dict[str, Optional[Path]]:
    district_dir = PROCESSED_ROOT / district

    if not district_dir.exists():
        raise FileNotFoundError(
            f"Processed district directory does not exist: {district_dir}"
        )

    return {
        "ndvi": _first_existing(
            district_dir, ["ndvi.tif", "ndvi.tiff", "ndvi"], required=True
        ),
        "ndwi": _first_existing(
            district_dir, ["ndwi.tif", "ndwi.tiff", "ndwi"]
        ),
        "water": _first_existing(
            district_dir, ["water.tif", "water.tiff", "water"]
        ),
        "canopy": _first_existing(
            district_dir,
            [
                "canopy.tif",
                "canopy.tiff",
                "chm.tif",
                "chm.tiff",
                "canopy",
                "chm",
            ],
        ),
        "buildings": _first_existing(
            district_dir, ["buildings.gpkg", "buildings.geojson", "buildings"]
        ),
    }


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _bounds_to_geometry(bounds):
    """
    Convert Leaflet bounds:
        [[south, west], [north, east]]
    to a WGS84 Polygon.
    """
    if (
        not isinstance(bounds, (list, tuple))
        or len(bounds) != 2
        or len(bounds[0]) != 2
        or len(bounds[1]) != 2
    ):
        raise ValueError(
            "bounds must be [[south, west], [north, east]]"
        )

    south, west = float(bounds[0][0]), float(bounds[0][1])
    north, east = float(bounds[1][0]), float(bounds[1][1])

    if south > north:
        south, north = north, south
    if west > east:
        west, east = east, west

    return box(west, south, east, north)


def _extract_geometry(payload: Dict[str, Any]):
    """
    Accept several convenient AOI formats.

    Preferred:
        {"geometry": <GeoJSON geometry>}

    Also:
        {"geojson": <GeoJSON Feature/Geometry>}
        {"aoi": <GeoJSON Feature/Geometry>}
        {"bounds": [[south, west], [north, east]]}
    """
    candidate = (
        payload.get("geometry")
        or payload.get("geojson")
        or payload.get("aoi")
    )

    if candidate is not None:
        if candidate.get("type") == "Feature":
            return shape(candidate["geometry"])

        if candidate.get("type") == "FeatureCollection":
            geometries = [
                shape(feature["geometry"])
                for feature in candidate.get("features", [])
                if feature.get("geometry")
            ]
            if not geometries:
                raise ValueError("GeoJSON FeatureCollection contains no geometry.")
            return unary_union(geometries)

        if candidate.get("type"):
            return shape(candidate)

    if payload.get("bounds") is not None:
        return _bounds_to_geometry(payload["bounds"])

    raise ValueError(
        "AOI geometry is required. Send GeoJSON geometry/feature or bounds."
    )


def _geometry_to_wgs84(gdf):
    if gdf.crs is None:
        raise ValueError("AOI geometry has no CRS.")
    return gdf.to_crs("EPSG:4326")


def _project_geometry(geom_wgs84, target_crs):
    transformer = Transformer.from_crs(
        "EPSG:4326",
        target_crs,
        always_xy=True,
    )
    return _transform_geometry(geom_wgs84, transformer)


def _transform_geometry(geom, transformer):
    """
    Transform a Shapely geometry without requiring shapely 2.x.
    """
    from shapely.ops import transform as shapely_transform

    return shapely_transform(
        lambda x, y, z=None: transformer.transform(x, y),
        geom,
    )


# ---------------------------------------------------------------------------
# Raster metrics
# ---------------------------------------------------------------------------

def _read_raster_for_geometry(path: Path, geometry_projected):
    """
    Read only the raster window covering the AOI and mask it exactly.
    Returns array, transform, valid AOI mask.
    """
    with rasterio.open(path) as src:
        clipped, transform = raster_mask(
            src,
            [mapping(geometry_projected)],
            crop=True,
            filled=False,
        )

        array = clipped[0].astype("float64")
        mask = np.ma.getmaskarray(clipped[0])

        data = np.ma.filled(array, np.nan)
        data[mask] = np.nan
        data[~np.isfinite(data)] = np.nan

        return data, transform, src.crs


def _mean_raster(path: Optional[Path], geometry_projected):
    if path is None:
        return None

    data, _, _ = _read_raster_for_geometry(path, geometry_projected)

    valid = np.isfinite(data)
    if not valid.any():
        return None

    return float(np.nanmean(data[valid]))


def _area_from_mask(mask: np.ndarray, transform) -> float:
    """
    Area in m² for pixels selected by mask.

    The current Tshaai master grid is 10 m, but we derive pixel area
    from the raster transform rather than assuming it.
    """
    pixel_area = abs(transform.a * transform.e)

    if transform.b != 0 or transform.d != 0:
        # Current datasets are north-up; keep this explicit.
        pixel_area = abs(transform.a * transform.e)

    return float(np.count_nonzero(mask) * pixel_area)


def _cover_from_raster(
    path: Optional[Path],
    geometry_projected,
    predicate,
):
    if path is None:
        return None, None

    data, transform, _ = _read_raster_for_geometry(
        path,
        geometry_projected,
    )

    valid = np.isfinite(data)
    selected = valid & predicate(data)

    area_m2 = _area_from_mask(selected, transform)
    valid_area_m2 = _area_from_mask(valid, transform)

    percentage = (
        (area_m2 / valid_area_m2) * 100.0
        if valid_area_m2 > 0
        else None
    )

    return area_m2, percentage


# ---------------------------------------------------------------------------
# Water = explicit water OR NDWI >= threshold
# ---------------------------------------------------------------------------

def _combined_water_cover(
    water_path,
    ndwi_path,
    geometry_projected,
):
    """
    Tshaai's water interpretation:

        explicit water mask
        OR
        NDWI >= 0.20

    This matches the water logic already used by the impact/map layers.
    """
    if water_path is None and ndwi_path is None:
        return None, None

    arrays = []
    transform = None

    if water_path is not None:
        water, transform, _ = _read_raster_for_geometry(
            water_path,
            geometry_projected,
        )
        arrays.append(
            np.isfinite(water) & (water > 0)
        )

    if ndwi_path is not None:
        ndwi, ndwi_transform, _ = _read_raster_for_geometry(
            ndwi_path,
            geometry_projected,
        )

        if transform is None:
            transform = ndwi_transform

        # All processed rasters are aligned to the common 10 m grid.
        arrays.append(
            np.isfinite(ndwi) & (ndwi >= NDWI_WATER_THRESHOLD)
        )

    if not arrays:
        return None, None

    combined = arrays[0].copy()
    for array in arrays[1:]:
        combined |= array

    area_m2 = _area_from_mask(combined, transform)

    # Use the AOI-covered raster area as denominator.
    valid = np.zeros_like(combined, dtype=bool)

    if water_path is not None:
        water, _, _ = _read_raster_for_geometry(
            water_path,
            geometry_projected,
        )
        valid |= np.isfinite(water)

    if ndwi_path is not None:
        ndwi, _, _ = _read_raster_for_geometry(
            ndwi_path,
            geometry_projected,
        )
        valid |= np.isfinite(ndwi)

    valid_area_m2 = _area_from_mask(valid, transform)

    percentage = (
        area_m2 / valid_area_m2 * 100.0
        if valid_area_m2 > 0
        else None
    )

    return area_m2, percentage


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------

def _read_buildings(path: Optional[Path], target_crs):
    if path is None:
        return None

    gdf = gpd.read_file(path)

    if gdf.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs=target_crs,
        )

    if gdf.crs is None:
        raise ValueError(f"Buildings layer has no CRS: {path}")

    return gdf.to_crs(target_crs)


def _built_up_density(
    buildings_path,
    aoi_projected,
    aoi_area_m2,
):
    """
    Built-up density = unioned building footprint area inside AOI /
    AOI area.

    Unioning avoids double-counting overlapping building polygons.
    """
    if buildings_path is None:
        return None, 0.0

    buildings = _read_buildings(
        buildings_path,
        "EPSG:32643",
    )

    if buildings is None or buildings.empty:
        return 0.0, 0

    # Spatial filter before intersection for speed.
    buildings = buildings[
        buildings.geometry.notna()
        & ~buildings.geometry.is_empty
        & buildings.geometry.intersects(aoi_projected)
    ]

    if buildings.empty:
        return 0.0, 0

    clipped = [
        geom.intersection(aoi_projected)
        for geom in buildings.geometry
    ]
    clipped = [
        geom for geom in clipped
        if geom is not None and not geom.is_empty
    ]

    if not clipped:
        return 0.0, 0

    footprint = unary_union(clipped)
    built_area_m2 = float(footprint.area)

    density = (
        built_area_m2 / aoi_area_m2 * 100.0
        if aoi_area_m2 > 0
        else None
    )

    return density, len(clipped)


# ---------------------------------------------------------------------------
# AOI analysis
# ---------------------------------------------------------------------------

def analyze_aoi(
    district: str,
    aoi_geometry_wgs84,
) -> Dict[str, Any]:
    """
    Calculate all requested environmental indicators for one AOI.
    """
    paths = district_paths(district)

    with rasterio.open(paths["ndvi"]) as ndvi_src:
        target_crs = ndvi_src.crs
        raster_bounds = ndvi_src.bounds

    if target_crs is None:
        raise ValueError("NDVI raster has no CRS.")

    aoi_projected = _project_geometry(
        aoi_geometry_wgs84,
        target_crs,
    )

    if aoi_projected.is_empty:
        raise ValueError("AOI geometry is empty.")

    # Ensure the AOI is inside the district raster coverage.
    district_box = box(
        raster_bounds.left,
        raster_bounds.bottom,
        raster_bounds.right,
        raster_bounds.top,
    )

    clipped_aoi = aoi_projected.intersection(district_box)

    if clipped_aoi.is_empty:
        raise ValueError(
            f"AOI does not overlap processed raster coverage for district '{district}'."
        )

    area_m2 = float(clipped_aoi.area)
    area_km2 = area_m2 / 1_000_000.0

    mean_ndvi = _mean_raster(
        paths["ndvi"],
        clipped_aoi,
    )

    mean_ndwi = _mean_raster(
        paths["ndwi"],
        clipped_aoi,
    )

    canopy_area_m2, canopy_cover_pct = _cover_from_raster(
        paths["canopy"],
        clipped_aoi,
        lambda values: values > CANOPY_THRESHOLD,
    )

    water_area_m2, water_cover_pct = _combined_water_cover(
        paths["water"],
        paths["ndwi"],
        clipped_aoi,
    )

    built_up_density_pct, building_count = _built_up_density(
        paths["buildings"],
        clipped_aoi,
        area_m2,
    )

    result = {
        "district": district,
        "area": {
            "value_km2": round(area_km2, 6),
            "value_m2": round(area_m2, 2),
        },
        "mean_ndvi": (
            round(mean_ndvi, 6)
            if mean_ndvi is not None
            else None
        ),
        "mean_ndwi": (
            round(mean_ndwi, 6)
            if mean_ndwi is not None
            else None
        ),
        "canopy_cover": {
            "percentage": (
                round(canopy_cover_pct, 4)
                if canopy_cover_pct is not None
                else None
            ),
            "area_m2": (
                round(canopy_area_m2, 2)
                if canopy_area_m2 is not None
                else None
            ),
            "definition": "CHM/canopy pixels > 0",
        },
        "built_up_density": {
            "percentage": (
                round(built_up_density_pct, 4)
                if built_up_density_pct is not None
                else None
            ),
            "building_features_intersecting_aoi": int(building_count),
            "definition": "Unioned building footprint area / AOI area",
        },
        "water_cover": {
            "percentage": (
                round(water_cover_pct, 4)
                if water_cover_pct is not None
                else None
            ),
            "area_m2": (
                round(water_area_m2, 2)
                if water_area_m2 is not None
                else None
            ),
            "definition": (
                "Explicit water mask OR NDWI >= "
                f"{NDWI_WATER_THRESHOLD}"
            ),
        },
        "methodology": {
            "crs": str(target_crs),
            "ndwi_water_threshold": NDWI_WATER_THRESHOLD,
            "canopy_threshold": CANOPY_THRESHOLD,
            "area_unit": "km²",
            "coverage_percent_denominator": (
                "Valid raster area within the AOI for raster-derived "
                "cover metrics."
            ),
        },
        "data_sources": {
            key: str(value) if value is not None else None
            for key, value in paths.items()
        },
    }

    return result


# ---------------------------------------------------------------------------
# District-wide metrics
# ---------------------------------------------------------------------------

def _district_geometry_from_boundary_files(district: str):
    """
    Try to find an actual district boundary.

    Supported locations:
        rawdata/districts/
        rawdata/boundaries/
        rawdata/aoi/
        processed/<district>/district_boundary.*
    """
    candidates = []

    root = _project_root()

    for folder in [
        root / "rawdata" / "districts",
        root / "rawdata" / "boundaries",
        root / "rawdata" / "aoi",
        PROCESSED_ROOT / district,
    ]:
        if not folder.exists():
            continue

        for path in folder.glob("*"):
            if path.suffix.lower() not in {".geojson", ".gpkg", ".json"}:
                continue

            stem = path.stem.lower()

            if (
                district.lower() in stem
                or "boundary" in stem
                or "district" in stem
                or stem == "aoi"
            ):
                candidates.append(path)

    if not candidates:
        return None

    path = candidates[0]

    try:
        gdf = gpd.read_file(path)
        if gdf.empty:
            return None

        if gdf.crs is None:
            return None

        gdf = gdf.to_crs("EPSG:4326")
        return unary_union(
            [
                geom
                for geom in gdf.geometry
                if geom is not None and not geom.is_empty
            ]
        )
    except Exception:
        return None


def district_geometry_from_raster(district: str):
    """
    Fallback when no district boundary file exists.

    Uses the NDVI raster's geographic footprint.
    This is explicitly labeled as raster-coverage area, not a
    legal/administrative district boundary.
    """
    paths = district_paths(district)

    with rasterio.open(paths["ndvi"]) as src:
        bounds = src.bounds
        raster_crs = src.crs

    projected = box(
        bounds.left,
        bounds.bottom,
        bounds.right,
        bounds.top,
    )

    transformer = Transformer.from_crs(
        raster_crs,
        "EPSG:4326",
        always_xy=True,
    )

    return _transform_geometry(projected, transformer)


def analyze_district(district: str) -> Dict[str, Any]:
    """
    Calculate the six requested district indicators.

    If an actual district boundary is available it is used.
    Otherwise the processed NDVI raster footprint is used and the
    result is marked as raster-coverage based.
    """
    boundary = _district_geometry_from_boundary_files(district)

    if boundary is None:
        boundary = district_geometry_from_raster(district)
        area_basis = "processed NDVI raster coverage"
    else:
        area_basis = "district boundary geometry"

    result = analyze_aoi(district, boundary)

    result["scope"] = "district"
    result["area_basis"] = area_basis

    return result


# ---------------------------------------------------------------------------
# Precompute all district JSON files
# ---------------------------------------------------------------------------

def discover_districts():
    if not PROCESSED_ROOT.exists():
        return []

    return sorted(
        path.name
        for path in PROCESSED_ROOT.iterdir()
        if path.is_dir()
        and (path / "ndvi.tif").exists()
    )


def generate_district_json(
    districts=None,
    output_path: Optional[Path] = None,
):
    """
    Generate one JSON file containing the six real metrics for every
    processed district.
    """
    if districts is None:
        districts = discover_districts()

    results = {}

    for district in districts:
        try:
            results[district] = analyze_district(district)
            print(f"[AOI] ✓ {district}")
        except Exception as exc:
            print(f"[AOI] ✗ {district}: {exc}")
            results[district] = {
                "district": district,
                "error": str(exc),
            }

    if output_path is None:
        output_path = OUTPUT_ROOT / "aoi" / "district_metrics.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_by": "Tshaai AOI environmental analysis",
        "metrics": [
            "AREA",
            "MEAN NDVI",
            "MEAN NDWI",
            "CANOPY COVER",
            "BUILT-UP DENSITY",
            "WATER COVER",
        ],
        "districts": results,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n[AOI] District metrics written to: {output_path}")

    return payload


# ---------------------------------------------------------------------------
# Flask API
# ---------------------------------------------------------------------------

def register_aoi_routes(app):
    """
    Register:

        GET  /api/aoi/districts
        GET  /api/aoi/district/<district>
        POST /api/aoi/analyse
        POST /api/aoi/districts/generate

    POST /api/aoi/analyse accepts:
        {
          "district": "sxr",
          "bounds": [[34.07, 74.75], [34.10, 74.80]]
        }

    or:
        {
          "district": "sxr",
          "geometry": {
            "type": "Polygon",
            "coordinates": [...]
          }
        }
    """

    from flask import jsonify, request

    @app.get("/api/aoi/districts")
    def aoi_districts():
        path = OUTPUT_ROOT / "aoi" / "district_metrics.json"

        if not path.exists():
            generate_district_json(output_path=path)

        with path.open("r", encoding="utf-8") as f:
            return jsonify(json.load(f))

    @app.get("/api/aoi/district/<district>")
    def aoi_district(district):
        try:
            return jsonify(analyze_district(district))
        except Exception as exc:
            return jsonify({
                "error": str(exc),
                "district": district,
            }), 400

    # @app.post("/api/aoi/analyse")
    # def aoi_analyse():
    #     payload = request.get_json(silent=True) or {}

    #     district = payload.get("district")

    #     if not district:
    #         return jsonify({
    #             "error": "district is required"
    #         }), 400

    #     try:
    #         geometry = _extract_geometry(payload)
    #         result = analyze_aoi(district, geometry)
    #         result["scope"] = "aoi"
    #         return jsonify(result)

    #     except Exception as exc:
    #         return jsonify({
    #             "error": str(exc),
    #             "district": district,
    #         }), 400
    @app.post("/api/aoi/analyse")
    def analyse_aoi():
        payload = request.get_json(silent=True) or {}
    
        district = str(payload.get("district", "")).strip()
    
        if not district:
            return jsonify({"error": "District is required."}), 400
    
        # ---------------------------------------------------------
        # DISTRICT ANALYSIS
        # ---------------------------------------------------------
        # If no geometry is supplied, analyse the actual district
        # boundary instead of requiring an AOI geometry.
        if not payload.get("geometry") and not payload.get("geojson") and not payload.get("aoi") and not payload.get("bounds"):
            try:
                result = analyze_district(district)
                return jsonify(result)
            except Exception as exc:
                return jsonify({
                    "error": f"District analysis failed: {exc}"
                }), 500
    
        # ---------------------------------------------------------
        # CUSTOM AOI ANALYSIS
        # ---------------------------------------------------------
        try:
            geometry = _extract_geometry(payload)
        except Exception as exc:
            return jsonify({
                "error": f"Invalid AOI geometry: {exc}"
            }), 400
    
        if not geometry:
            return jsonify({
                "error": "AOI geometry is required. Send GeoJSON geometry/feature or bounds."
            }), 400
    
        try:
            result = analyze_aoi(district, geometry)
            return jsonify(result)
        except Exception as exc:
            return jsonify({
                "error": f"AOI analysis failed: {exc}"
            }), 500
    @app.post("/api/aoi/districts/generate")
    def aoi_generate_districts():
        try:
            payload = generate_district_json()
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return app


if __name__ == "__main__":
    # Useful for generating the district JSON without starting Flask:
    #
    #     python backend/services/aoi_analysis.py
    #
    generate_district_json()
