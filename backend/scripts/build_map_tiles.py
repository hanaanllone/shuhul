from pathlib import Path
import argparse
import json
import math
import shutil
import sys
import warnings

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window


# ============================================================
# SHUHUL - MAP TILES
# ============================================================
#
# Draws every registered layer once, as ordinary web map tiles, so the
# app never renders a raster while a planner is waiting.
#
# Input:
#
# processed/<district>/<layer files>    see backend/services/layers.py
#
# Output:
#
# processed/<district>/tiles/
#   <layer>/<z>/<x>/<y>.png     256 px tiles, transparent where empty
#   manifest.json               layers, legends, sources, map extent
#
# The same folder is what gets copied to S3 for the live site.
#
# Usage:
#   python backend/scripts/build_map_tiles.py --district sxr
#   python backend/scripts/build_map_tiles.py --district sxr --layers lst flood
#
# ============================================================


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.layers import LAYERS, layer_path, describe  # noqa: E402

PROCESSED_ROOT = PROJECT_ROOT / "processed"

TILE_SIZE = 256
MIN_ZOOM = 9
MAX_ZOOM = 14
WEB_MERCATOR = "EPSG:3857"
EARTH_HALF_CIRCUMFERENCE = 20037508.342789244

LAYER_ALPHA = 205
STRETCH_PERCENTILES = (2, 98)


# ------------------------------------------------------------
# TILE MATHS
# ------------------------------------------------------------

def tile_resolution(zoom):
    return 2 * EARTH_HALF_CIRCUMFERENCE / (TILE_SIZE * 2 ** zoom)


def tile_range(bounds_3857, zoom):
    """Tile columns and rows that cover a Web Mercator extent."""
    left, bottom, right, top = bounds_3857
    span = 2 * EARTH_HALF_CIRCUMFERENCE / 2 ** zoom

    x0 = int(math.floor((left + EARTH_HALF_CIRCUMFERENCE) / span))
    x1 = int(math.floor((right + EARTH_HALF_CIRCUMFERENCE) / span))
    y0 = int(math.floor((EARTH_HALF_CIRCUMFERENCE - top) / span))
    y1 = int(math.floor((EARTH_HALF_CIRCUMFERENCE - bottom) / span))
    return x0, x1, y0, y1


# ------------------------------------------------------------
# COLOUR
# ------------------------------------------------------------

def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def ramp(values, palette):
    """Interpolate 0-1 values along a list of hex colours."""
    stops = np.array([hex_to_rgb(color) for color in palette], dtype="float32")
    position = np.clip(values, 0, 1) * (len(stops) - 1)
    lower = np.floor(position).astype(int)
    upper = np.minimum(lower + 1, len(stops) - 1)
    weight = (position - lower)[..., None]
    return (stops[lower] * (1 - weight) + stops[upper] * weight).astype("uint8")


def colorize(layer, data, domain):
    """Turn a block of layer values into an RGBA image array."""
    rgba = np.zeros((*data.shape, 4), dtype="uint8")
    valid = np.isfinite(data)
    kind = layer["kind"]

    if kind == "continuous":
        low, high = domain
        shown = valid & (data >= layer.get("hide_below", -np.inf))
        scaled = (np.where(shown, data, low) - low) / max(high - low, 1e-9)
        rgba[..., :3] = ramp(scaled, layer["palette"])
        rgba[..., 3] = np.where(shown, LAYER_ALPHA, 0)

    elif kind == "mask":
        shown = valid & (data > 0)
        rgba[shown, :3] = hex_to_rgb(layer["color"])
        rgba[shown, 3] = LAYER_ALPHA

    elif kind == "classes":
        for code, (_, color) in layer["classes"].items():
            shown = valid & (data == code)
            rgba[shown, :3] = hex_to_rgb(color)
            rgba[shown, 3] = LAYER_ALPHA

    elif kind == "thresholds":
        lower = -np.inf
        for upper, _, color in layer["thresholds"]:
            if color is not None:
                shown = valid & (data >= lower) & (data < upper)
                rgba[shown, :3] = hex_to_rgb(color)
                rgba[shown, 3] = LAYER_ALPHA
            lower = upper

    return rgba


def legend_for(layer, domain):
    kind = layer["kind"]

    if kind == "continuous":
        return {
            "type": "ramp",
            "colors": layer["palette"],
            "min": round(float(domain[0]), 2),
            "max": round(float(domain[1]), 2),
            "unit": layer.get("unit"),
        }
    if kind == "mask":
        return {"type": "swatches", "items": [{"label": layer["title"], "color": layer["color"]}]}
    if kind == "classes":
        return {
            "type": "swatches",
            "items": [{"label": label, "color": color} for label, color in layer["classes"].values()],
        }

    return {
        "type": "swatches",
        "items": [
            {"label": label, "color": color}
            for _, label, color in layer["thresholds"]
            if color is not None
        ],
    }


# ------------------------------------------------------------
# TILING
# ------------------------------------------------------------

def read_values(src, band=1):
    data = src.read(band).astype("float32")
    if src.nodata is not None:
        data[data == src.nodata] = np.nan
    return data


def stretch_domain(path, layer):
    if "domain" in layer:
        return layer["domain"]
    if layer["kind"] != "continuous":
        return None

    with rasterio.open(path) as src:
        values = read_values(src)
    values = values[np.isfinite(values)]
    low, high = np.percentile(values, STRETCH_PERCENTILES)
    return [float(low), float(high)]


def build_layer(district, name, tiles_dir):
    layer = LAYERS[name]
    path = layer_path(district, name)
    domain = stretch_domain(path, layer)
    resampling = Resampling.bilinear if layer["kind"] == "continuous" else Resampling.nearest

    output = tiles_dir / name
    if output.exists():
        shutil.rmtree(output)

    written = 0

    with rasterio.open(path) as src:
        bounds_3857 = transform_bounds(src.crs, WEB_MERCATOR, *src.bounds)
        nodata = src.nodata

        for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
            x0, x1, y0, y1 = tile_range(bounds_3857, zoom)
            resolution = tile_resolution(zoom)
            span = resolution * TILE_SIZE

            # One warped view per zoom, laid out exactly on the tile grid,
            # so a tile is a plain slice of it.
            with WarpedVRT(
                src,
                crs=WEB_MERCATOR,
                transform=from_origin(
                    -EARTH_HALF_CIRCUMFERENCE + x0 * span,
                    EARTH_HALF_CIRCUMFERENCE - y0 * span,
                    resolution,
                    resolution,
                ),
                width=(x1 - x0 + 1) * TILE_SIZE,
                height=(y1 - y0 + 1) * TILE_SIZE,
                resampling=resampling,
                src_nodata=nodata,
                nodata=nodata,
            ) as vrt:
                for y in range(y0, y1 + 1):
                    strip = vrt.read(
                        1,
                        window=Window(0, (y - y0) * TILE_SIZE, vrt.width, TILE_SIZE),
                    ).astype("float32")

                    if nodata is not None:
                        strip[strip == nodata] = np.nan

                    if not np.isfinite(strip).any():
                        continue

                    rgba = colorize(layer, strip, domain)

                    for x in range(x0, x1 + 1):
                        tile = rgba[:, (x - x0) * TILE_SIZE:(x - x0 + 1) * TILE_SIZE]
                        if not tile[..., 3].any():
                            continue

                        target = output / str(zoom) / str(x) / f"{y}.png"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        Image.fromarray(tile, mode="RGBA").save(target, format="PNG")
                        written += 1

    entry = describe(name)
    entry["legend"] = legend_for(layer, domain)
    entry["tiles"] = f"{name}/{{z}}/{{x}}/{{y}}.png"
    return entry, written


def build(district, only=None):
    tiles_dir = PROCESSED_ROOT / district / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tiles_dir / "manifest.json"

    manifest = {"district": district, "layers": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    with rasterio.open(PROCESSED_ROOT / district / "ndvi.tif") as src:
        west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)

    manifest.update({
        "district": district,
        "bounds": [[south, west], [north, east]],
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM,
    })

    print("=" * 70)
    print(f"MAP TILES - {district}")
    print("=" * 70)

    for name in LAYERS:
        if only and name not in only:
            continue
        if not layer_path(district, name).exists():
            manifest["layers"].pop(name, None)
            continue

        entry, written = build_layer(district, name, tiles_dir)
        manifest["layers"][name] = entry
        print(f"  {name:18s} {written:5d} tiles", flush=True)

    # Keep the registry's order whatever order layers were built in.
    manifest["layers"] = {
        name: manifest["layers"][name] for name in LAYERS if name in manifest["layers"]
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="Build web map tiles for a district.")
    parser.add_argument("--district", default="sxr")
    parser.add_argument("--layers", nargs="*", help="Only rebuild these layers.")
    args = parser.parse_args()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        build(args.district, args.layers)


if __name__ == "__main__":
    main()
