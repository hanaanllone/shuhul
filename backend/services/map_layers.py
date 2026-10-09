"""
Shuhul map layer service.

Add to app.py:
    from .map_layers import register_map_layer_routes
    register_map_layer_routes(app)

This serves real processed GIS data to the React/Leaflet frontend.
It does not alter the analysis/report pipeline.
"""

from pathlib import Path
import io
import json
import re

from flask import jsonify, send_file

from ..config import PROCESSED_ROOT, OUTPUT_ROOT, TILE_BASE_URL
from .layers import LAYERS

LEGACY_TITLES = {
    "ndvi": "Vegetation",
    "water": "Water",
    "canopy": "Canopy",
    "slope": "Slope",
}


def _valid_district(district):
    return re.fullmatch(r"[a-z0-9_-]+", district) is not None


def _tile_manifest(district):
    """Pre-built tile layers for a district, or None when it has not been tiled."""
    path = PROCESSED_ROOT / district / "tiles" / "manifest.json"

    if not path.exists():
        return None

    manifest = json.loads(path.read_text(encoding="utf-8"))

    for layer in manifest["layers"].values():
        layer["available"] = True
        layer["tiles"] = f"{TILE_BASE_URL}/{district}/{layer['tiles']}"

    return manifest


def _find_raster(district_dir, names, required=False):
    for name in names:
        for candidate in (name, f"{name}.tif", f"{name}.tiff"):
            path = district_dir / candidate
            if path.exists():
                return path
    if required:
        raise FileNotFoundError(
            f"Required raster not found in {district_dir}: {names}"
        )
    return None


def _bounds_wgs84(src):
    from pyproj import Transformer

    transformer = Transformer.from_crs(
        src.crs, "EPSG:4326", always_xy=True
    )

    corners = [
        transformer.transform(src.bounds.left, src.bounds.bottom),
        transformer.transform(src.bounds.right, src.bounds.top),
    ]

    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]

    return [[min(ys), min(xs)], [max(ys), max(xs)]]


def _rgba_for(layer, array):
    """
    Convert a raster to a transparent RGBA image.

    The displayed image is a visualization only; all analysis continues
    to use the original GeoTIFFs.
    """
    import numpy as np

    finite = np.isfinite(array)

    if layer == "water":
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        wet = finite & (array > 0)
        rgba[wet] = [40, 120, 220, 165]
        return rgba

    if layer == "canopy":
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        canopy = finite & (array > 0)
        valid = array[canopy]
        if valid.size:
            # CHM/canopy > 0, visually scaled between 0 and 30m.
            alpha = np.clip(valid / 30.0, 0, 1)
            rgba[canopy, 0] = (25 * alpha).astype(np.uint8)
            rgba[canopy, 1] = (90 + 130 * alpha).astype(np.uint8)
            rgba[canopy, 2] = (35 * (1 - alpha)).astype(np.uint8)
            rgba[canopy, 3] = 150
        return rgba

    if layer == "ndvi":
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        v = np.clip(array, -1, 1)
        t = (v + 1) / 2
        # red -> yellow -> green
        rgba[..., 0] = np.where(
            t < 0.5, 215, (1 - (t - 0.5) * 2) * 215
        ).astype(np.uint8)
        rgba[..., 1] = np.where(
            t < 0.5, t * 2 * 220, 220
        ).astype(np.uint8)
        rgba[..., 2] = np.where(
            t < 0.5, 55 + (1 - t * 2) * 40, 50
        ).astype(np.uint8)
        rgba[..., 3] = np.where(finite, 145, 0).astype(np.uint8)
        return rgba

    if layer == "slope":
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        v = np.clip(array, 0, 35)
        t = v / 35.0
        rgba[..., 0] = (45 + 180 * t).astype(np.uint8)
        rgba[..., 1] = (145 - 95 * t).astype(np.uint8)
        rgba[..., 2] = (65 - 45 * t).astype(np.uint8)
        rgba[..., 3] = np.where(finite, 125, 0).astype(np.uint8)
        return rgba

    raise ValueError(f"Unsupported raster layer: {layer}")


def _render_raster_png(path, layer, max_dim=1600):
    import numpy as np
    import rasterio
    from PIL import Image

    with rasterio.open(path) as src:
        scale = min(1.0, max_dim / max(src.width, src.height))
        out_width = max(1, int(round(src.width * scale)))
        out_height = max(1, int(round(src.height * scale)))

        array = src.read(
            1,
            out_shape=(out_height, out_width),
            resampling=rasterio.enums.Resampling.bilinear
            if layer not in {"water"}
            else rasterio.enums.Resampling.nearest,
        ).astype("float32")

        if src.nodata is not None:
            array[array == src.nodata] = np.nan

        array[~np.isfinite(array)] = np.nan
        rgba = _rgba_for(layer, array)

        image = Image.fromarray(rgba, mode="RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)

        bounds = _bounds_wgs84(src)

    return buffer, bounds


def _build_buildings_geojson(path):
    import geopandas as gpd

    gdf = gpd.read_file(path)

    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Keep geometry and a small attribute subset only.
    keep = ["geometry"]
    for col in ("building", "name", "type", "levels", "height"):
        if col in gdf.columns:
            keep.append(col)

    gdf = gdf[keep].copy()
    return json.loads(gdf.to_json())


def build_project_corridors(project_id, construction, width_m):
    """Buffer a project's own routes into construction corridors."""
    import geopandas as gpd

    route_file = (
        OUTPUT_ROOT / "projects" / str(project_id)
        / f"routes_{construction}.geojson"
    )
    empty = {"type": "FeatureCollection", "features": []}

    if not route_file.exists():
        return empty

    routes = gpd.read_file(route_file)
    if routes.empty:
        return empty

    if routes.crs is None:
        routes = routes.set_crs("EPSG:4326")

    # Buffer in a metric CRS. Project data uses UTM 43N.
    metric = routes.to_crs("EPSG:32643")
    metric["geometry"] = metric.geometry.buffer(float(width_m) / 2.0)

    return json.loads(metric.to_crs("EPSG:4326").to_json())


def _render_combined_water_png(water_path, ndwi_path, max_dim=1600, threshold=0.20):
    import numpy as np
    import rasterio
    from PIL import Image

    # Use water.tif as the explicit mask and NDWI >= threshold as a
    # complementary water signal. The processed datasets share the master grid.
    reference = water_path or ndwi_path

    with rasterio.open(reference) as ref:
        scale = min(1.0, max_dim / max(ref.width, ref.height))
        out_width = max(1, int(round(ref.width * scale)))
        out_height = max(1, int(round(ref.height * scale)))

        def read(path, resampling):
            if path is None:
                return None
            with rasterio.open(path) as src:
                arr = src.read(
                    1,
                    out_shape=(out_height, out_width),
                    resampling=resampling,
                ).astype("float32")
                if src.nodata is not None:
                    arr[arr == src.nodata] = np.nan
                arr[~np.isfinite(arr)] = np.nan
                return arr

        water = read(water_path, rasterio.enums.Resampling.nearest)
        ndwi = read(ndwi_path, rasterio.enums.Resampling.bilinear)

        wet = np.zeros((out_height, out_width), dtype=bool)
        if water is not None:
            wet |= np.isfinite(water) & (water > 0)
        if ndwi is not None:
            wet |= np.isfinite(ndwi) & (ndwi >= threshold)

        rgba = np.zeros((out_height, out_width, 4), dtype=np.uint8)
        rgba[wet] = [40, 120, 220, 170]

        image = Image.fromarray(rgba, mode="RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)

        bounds = _bounds_wgs84(ref)

    return buffer, bounds


def register_map_layer_routes(app):
    """
    Register:
      GET /api/layers/<district>/manifest
      GET /api/tiles/<district>/<layer>/<z>/<x>/<y>.png
      GET /api/layers/<district>/<layer>.png
      GET /api/layers/<district>/buildings
    """

    @app.get("/api/layers/<district>/manifest")
    def map_layer_manifest(district):
        if not _valid_district(district):
            return jsonify({"error": "Unknown district"}), 404

        # Districts with pre-built tiles are served from files. The rest
        # fall back to rendering one image per layer on request.
        tiled = _tile_manifest(district)
        if tiled is not None:
            return jsonify(tiled)

        district_dir = PROCESSED_ROOT / district

        rasters = {
            "ndvi": _find_raster(district_dir, ["ndvi"]),
            "water": _find_raster(district_dir, ["water", "ndwi"]),
            "canopy": _find_raster(
                district_dir, ["canopy", "chm"]
            ),
            "slope": _find_raster(district_dir, ["slope"]),
        }

        layers = {}
        for name, path in rasters.items():
            if path is None:
                continue

            import rasterio

            with rasterio.open(path) as src:
                bounds = _bounds_wgs84(src)

            layers[name] = {
                "available": True,
                "title": LEGACY_TITLES[name],
                "url": f"/api/layers/{district}/{name}.png",
                "bounds": bounds,
            }

        return jsonify({
            "district": district,
            "layers": layers,
        })

    @app.get("/api/tiles/<district>/<layer>/<int:z>/<int:x>/<int:y>.png")
    def map_tile(district, layer, z, x, y):
        if not _valid_district(district) or layer not in LAYERS:
            return "", 404

        path = (
            PROCESSED_ROOT / district / "tiles" / layer
            / str(z) / str(x) / f"{y}.png"
        )

        # Empty tiles are not stored. No content keeps the map quiet.
        if not path.is_file():
            return "", 204

        return send_file(path, mimetype="image/png", max_age=86400)

    @app.get("/api/layers/<district>/<layer>.png")
    def map_layer_png(district, layer):
        allowed = {"ndvi", "water", "canopy", "slope"}
        if layer not in allowed:
            return jsonify({"error": "Unknown raster layer"}), 404

        district_dir = PROCESSED_ROOT / district
        path = {
            "ndvi": _find_raster(district_dir, ["ndvi"]),
            "water": _find_raster(district_dir, ["water", "ndwi"]),
            "canopy": _find_raster(district_dir, ["canopy", "chm"]),
            "slope": _find_raster(district_dir, ["slope"]),
        }[layer]

        if path is None:
            return jsonify({
                "error": f"{layer} raster is not available for district {district}"
            }), 404

        if layer == "water":
            water_path = _find_raster(district_dir, ["water"])
            ndwi_path = _find_raster(district_dir, ["ndwi"])
            buffer, _ = _render_combined_water_png(water_path, ndwi_path)
        else:
            buffer, _ = _render_raster_png(path, layer)
        return send_file(
            buffer,
            mimetype="image/png",
            max_age=300,
        )

    @app.get("/api/layers/<district>/buildings")
    def map_layer_buildings(district):
        district_dir = PROCESSED_ROOT / district
        buildings_path = district_dir / "buildings.gpkg"

        if not buildings_path.exists():
            return jsonify({
                "type": "FeatureCollection",
                "features": [],
            })

        try:
            return jsonify(_build_buildings_geojson(buildings_path))
        except Exception as exc:
            return jsonify({"error": f"Could not load buildings: {exc}"}), 500
