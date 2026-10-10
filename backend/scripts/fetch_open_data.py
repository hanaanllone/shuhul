from pathlib import Path
import argparse
import csv
import io
import json
import math
import shutil
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds


# ============================================================
# SHUHUL - OPEN DATA FETCH
# ============================================================
#
# Pulls the global open datasets Shuhul needs for one district.
# The district extent comes from processed/<district>/ndvi.tif,
# so any district that has been preprocessed can be fetched.
#
# Output:
#
# rawdata/
#   landsat/<district>/<scene_id>/
#       qa_pixel.tif  lwir11.tif  red.tif  nir08.tif
#       green.tif     swir16.tif
#   landsat/<district>/scenes.json
#   worldcover/<district>_worldcover_2021.tif
#   jrc_gsw/occurrence_<tile>.tif
#   jrc_gsw/transitions_<tile>.tif
#   ms_buildings/<quadkey>.csv.gz
#
# Landsat clips are raw windows (original digital numbers, original
# 30 m grid). Scaling, cloud masking and compositing happen in
# preprocessing, so the season or mask can change without a re-download.
#
# Usage:
#   python backend/scripts/fetch_open_data.py --district sxr
#   python backend/scripts/fetch_open_data.py --district sxr --what landsat --years 2017-2025
#
# ============================================================


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = PROJECT_ROOT / "processed"
RAW_ROOT = PROJECT_ROOT / "rawdata"

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2"

LANDSAT_ASSETS = ["qa_pixel", "lwir11", "red", "nir08", "green", "swir16"]
LANDSAT_SEASON = ("05-01", "09-30")
LANDSAT_MAX_SCENE_CLOUD = 70
LANDSAT_MIN_COVERAGE = 0.01
LANDSAT_BUFFER_M = 300
LANDSAT_WORKERS = 8

WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)

JRC_URL = (
    "https://storage.googleapis.com/global-surface-water/downloads2021/"
    "{layer}/{layer}_{tile}v1_4_2021.tif"
)
JRC_LAYERS = ["occurrence", "transitions"]

MS_BUILDINGS_INDEX = (
    "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
)
MS_BUILDINGS_ZOOM = 9

# Lakes, wetlands and rivers as mapped on OpenStreetMap, from the
# Geofabrik extract for northern India. Mapped outlines take in the parts
# of a lake under weed or algae, which a satellite water index reads as
# land. Only the two water layers are read out of the remote archive.
OSM_EXTRACT = (
    "/vsizip//vsicurl/https://download.geofabrik.de/asia/india/"
    "northern-zone-latest-free.shp.zip/{layer}.shp"
)
OSM_WATER_AREAS = "gis_osm_water_a_free_1"
OSM_WATERWAYS = "gis_osm_waterways_free_1"

# How the extract's classes are read: standing water, wetland, or flowing.
OSM_AREA_KINDS = {"water": "lake", "reservoir": "lake", "wetland": "wetland", "river": "river"}
OSM_LINE_KINDS = {"river": "river", "canal": "river"}

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "GDAL_HTTP_TIMEOUT": "90",
    "VSI_CACHE": "TRUE",
}

USER_AGENT = "Mozilla/5.0 (Shuhul open-data fetch)"


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def log(message):
    print(message, flush=True)


def http_open(url, payload=None, timeout=120):
    data = None
    headers = {"User-Agent": USER_AGENT}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def http_json(url, payload=None):
    last_error = None

    for attempt in range(4):
        try:
            with http_open(url, payload) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"Request failed: {url}: {last_error}")


def download_file(url, destination):
    if destination.exists() and destination.stat().st_size > 0:
        log(f"  exists  {destination.relative_to(PROJECT_ROOT)}")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    with http_open(url, timeout=300) as response, open(partial, "wb") as f:
        shutil.copyfileobj(response, f, length=1024 * 1024)

    partial.replace(destination)
    size_mb = destination.stat().st_size / 1048576
    log(f"  saved   {destination.relative_to(PROJECT_ROOT)} ({size_mb:.1f} MB)")
    return destination


def district_extent(district):
    """Return (crs, projected bounds, WGS84 bounds) of the district master grid."""
    master = PROCESSED_ROOT / district / "ndvi.tif"

    if not master.exists():
        raise FileNotFoundError(f"Master raster not found: {master}")

    with rasterio.open(master) as src:
        bounds = tuple(src.bounds)
        wgs84 = transform_bounds(src.crs, "EPSG:4326", *bounds)
        return src.crs, bounds, wgs84


def parse_years(text):
    if "-" in text:
        first, last = text.split("-", 1)
        return list(range(int(first), int(last) + 1))
    return [int(part) for part in text.split(",")]


# ------------------------------------------------------------
# LANDSAT COLLECTION 2 LEVEL 2
# ------------------------------------------------------------

class SasToken:
    """Short-lived read token for the Planetary Computer Landsat container."""

    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._fetched = 0.0

    def get(self, force=False):
        with self._lock:
            if force or self._token is None or time.time() - self._fetched > 1500:
                self._token = http_json(SAS_TOKEN)["token"]
                self._fetched = time.time()
            return self._token


def search_landsat(wgs84_bounds, year):
    payload = {
        "collections": ["landsat-c2-l2"],
        "bbox": list(wgs84_bounds),
        "datetime": (
            f"{year}-{LANDSAT_SEASON[0]}T00:00:00Z/"
            f"{year}-{LANDSAT_SEASON[1]}T23:59:59Z"
        ),
        "query": {
            "eo:cloud_cover": {"lt": LANDSAT_MAX_SCENE_CLOUD},
            "platform": {"in": ["landsat-8", "landsat-9"]},
        },
        "limit": 100,
    }

    items = []
    url = STAC_SEARCH

    while True:
        page = http_json(url, payload)
        items.extend(page.get("features", []))

        next_link = next(
            (link for link in page.get("links", []) if link.get("rel") == "next"),
            None,
        )
        if not next_link:
            break

        url = next_link["href"]
        payload = next_link.get("body", payload)

    return items


def read_window(href, token, bounds, crs):
    """Read the district window from a remote scene band without resampling."""
    with rasterio.open(f"{href}?{token.get()}") as src:
        if src.crs != crs:
            bounds = transform_bounds(crs, src.crs, *bounds)

        window = from_bounds(*bounds, transform=src.transform)
        window = window.round_offsets().round_lengths()

        try:
            window = window.intersection(Window(0, 0, src.width, src.height))
        except rasterio.errors.WindowError:
            return None, None

        if window.width < 1 or window.height < 1:
            return None, None

        data = src.read(1, window=window)
        profile = {
            "driver": "GTiff",
            "dtype": src.dtypes[0],
            "count": 1,
            "width": int(window.width),
            "height": int(window.height),
            "crs": src.crs,
            "transform": src.window_transform(window),
            "nodata": src.nodata,
            "compress": "deflate",
            "predictor": 2,
            "tiled": True,
        }
        return data, profile


def read_window_with_retry(href, token, bounds, crs):
    last_error = None

    for attempt in range(3):
        try:
            return read_window(href, token, bounds, crs)
        except Exception as exc:
            last_error = exc
            token.get(force=True)
            time.sleep(3 * (attempt + 1))

    raise RuntimeError(f"Could not read {href.rsplit('/', 1)[-1]}: {last_error}")


def fetch_scene(item, scene_dir, token, bounds, crs):
    """
    Download one scene's bands. Returns the fraction of the window that
    holds real observations (0 when the scene misses the district).
    """
    no_coverage = scene_dir / ".nocoverage"
    qa_path = scene_dir / "qa_pixel.tif"

    if no_coverage.exists():
        return 0.0

    scene_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.Env(**GDAL_ENV):
        if qa_path.exists():
            with rasterio.open(qa_path) as src:
                qa = src.read(1)
        else:
            qa, profile = read_window_with_retry(
                item["assets"]["qa_pixel"]["href"], token, bounds, crs
            )

        # QA_PIXEL bit 0 marks fill, and 0 is outside the scene footprint.
        coverage = 0.0 if qa is None else float(np.mean((qa != 0) & (qa != 1)))

        if coverage < LANDSAT_MIN_COVERAGE:
            no_coverage.write_text("scene does not cover the district window\n")
            return 0.0

        if not qa_path.exists():
            with rasterio.open(qa_path, "w", **profile) as dst:
                dst.write(qa, 1)

        for asset in LANDSAT_ASSETS:
            path = scene_dir / f"{asset}.tif"
            if path.exists():
                continue

            data, profile = read_window_with_retry(
                item["assets"][asset]["href"], token, bounds, crs
            )
            partial = path.with_suffix(".part")
            with rasterio.open(partial, "w", **profile) as dst:
                dst.write(data, 1)
            partial.replace(path)

    return coverage


def fetch_landsat(district, years):
    crs, bounds, wgs84 = district_extent(district)
    bounds = (
        bounds[0] - LANDSAT_BUFFER_M,
        bounds[1] - LANDSAT_BUFFER_M,
        bounds[2] + LANDSAT_BUFFER_M,
        bounds[3] + LANDSAT_BUFFER_M,
    )

    output_dir = RAW_ROOT / "landsat" / district
    output_dir.mkdir(parents=True, exist_ok=True)

    log("=" * 70)
    log(f"LANDSAT C2 L2 - {district} - {years[0]}..{years[-1]}")
    log("=" * 70)

    items = []
    for year in years:
        found = search_landsat(wgs84, year)
        log(f"  {year}: {len(found)} scenes under {LANDSAT_MAX_SCENE_CLOUD}% cloud")
        items.extend(found)

    token = SasToken()
    manifest = []
    done = 0

    with ThreadPoolExecutor(max_workers=LANDSAT_WORKERS) as pool:
        futures = {
            pool.submit(
                fetch_scene, item, output_dir / item["id"], token, bounds, crs
            ): item
            for item in items
        }

        for future in as_completed(futures):
            item = futures[future]
            props = item["properties"]
            done += 1

            try:
                coverage = future.result()
                error = None
            except Exception as exc:
                coverage = 0.0
                error = str(exc)

            manifest.append({
                "id": item["id"],
                "datetime": props.get("datetime"),
                "platform": props.get("platform"),
                "cloud_cover": props.get("eo:cloud_cover"),
                "wrs_path": props.get("landsat:wrs_path"),
                "wrs_row": props.get("landsat:wrs_row"),
                "coverage": round(coverage, 4),
                "used": coverage >= LANDSAT_MIN_COVERAGE,
                "error": error,
            })

            status = "ERROR " + error if error else f"coverage {coverage:.0%}"
            log(f"  [{done}/{len(items)}] {item['id']}  {status}")

    manifest.sort(key=lambda scene: scene["datetime"] or "")
    manifest_path = output_dir / "scenes.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    used = [scene for scene in manifest if scene["used"]]
    failed = [scene for scene in manifest if scene["error"]]

    log("-" * 70)
    log(f"Scenes found:  {len(manifest)}")
    log(f"Scenes saved:  {len(used)}")
    log(f"Scenes failed: {len(failed)}")
    for year in years:
        count = sum(1 for scene in used if (scene["datetime"] or "").startswith(str(year)))
        log(f"  {year}: {count} usable scenes")
    log(f"Manifest: {manifest_path}")


# ------------------------------------------------------------
# ESA WORLDCOVER 2021
# ------------------------------------------------------------

def worldcover_tiles(wgs84):
    """WorldCover tiles are 3 x 3 degrees, named by their south-west corner."""
    west, south, east, north = wgs84
    tiles = []

    for lat in range(int(math.floor(south / 3) * 3), int(math.ceil(north / 3) * 3), 3):
        for lon in range(int(math.floor(west / 3) * 3), int(math.ceil(east / 3) * 3), 3):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            tiles.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")

    return tiles


def fetch_worldcover(district):
    _, _, wgs84 = district_extent(district)
    destination = RAW_ROOT / "worldcover" / f"{district}_worldcover_2021.tif"

    log("=" * 70)
    log(f"ESA WORLDCOVER 2021 - {district}")
    log("=" * 70)

    if destination.exists():
        log(f"  exists  {destination.relative_to(PROJECT_ROOT)}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    tiles = worldcover_tiles(wgs84)
    log(f"  tiles: {', '.join(tiles)}")

    with rasterio.Env(**GDAL_ENV):
        sources = [rasterio.open(WORLDCOVER_URL.format(tile=tile)) for tile in tiles]
        try:
            mosaic, transform = merge(sources, bounds=wgs84)
            profile = {
                "driver": "GTiff",
                "dtype": mosaic.dtype,
                "count": 1,
                "width": mosaic.shape[2],
                "height": mosaic.shape[1],
                "crs": sources[0].crs,
                "transform": transform,
                "nodata": 0,
                "compress": "deflate",
                "tiled": True,
            }
        finally:
            for src in sources:
                src.close()

    with rasterio.open(destination, "w", **profile) as dst:
        dst.write(mosaic[0], 1)

    size_mb = destination.stat().st_size / 1048576
    log(f"  saved   {destination.relative_to(PROJECT_ROOT)} ({size_mb:.1f} MB)")


# ------------------------------------------------------------
# JRC GLOBAL SURFACE WATER
# ------------------------------------------------------------

def jrc_tiles(wgs84):
    """JRC tiles are 10 x 10 degrees, named by their north-west corner."""
    west, south, east, north = wgs84
    tiles = []

    for lat in range(int(math.ceil(north / 10) * 10), int(math.floor(south / 10) * 10), -10):
        for lon in range(int(math.floor(west / 10) * 10), int(math.ceil(east / 10) * 10), 10):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            tiles.append(f"{abs(lon)}{ew}_{abs(lat)}{ns}")

    return tiles


def fetch_jrc(district):
    _, _, wgs84 = district_extent(district)

    log("=" * 70)
    log(f"JRC GLOBAL SURFACE WATER - {district}")
    log("=" * 70)

    for tile in jrc_tiles(wgs84):
        for layer in JRC_LAYERS:
            download_file(
                JRC_URL.format(layer=layer, tile=tile),
                RAW_ROOT / "jrc_gsw" / f"{layer}_{tile}.tif",
            )


# ------------------------------------------------------------
# MICROSOFT ML BUILDING FOOTPRINTS
# ------------------------------------------------------------

def tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def quadkey(x, y, zoom):
    key = ""
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        key += str(digit)
    return key


def fetch_ms_buildings(district):
    _, _, wgs84 = district_extent(district)
    west, south, east, north = wgs84

    log("=" * 70)
    log(f"MICROSOFT ML BUILDING FOOTPRINTS - {district}")
    log("=" * 70)

    x0, y0 = tile_xy(north, west, MS_BUILDINGS_ZOOM)
    x1, y1 = tile_xy(south, east, MS_BUILDINGS_ZOOM)
    wanted = {
        quadkey(x, y, MS_BUILDINGS_ZOOM)
        for x in range(x0, x1 + 1)
        for y in range(y0, y1 + 1)
    }
    log(f"  quadkeys: {', '.join(sorted(wanted))}")

    with http_open(MS_BUILDINGS_INDEX) as response:
        rows = list(csv.DictReader(io.TextIOWrapper(response, encoding="utf-8")))

    matches = [row for row in rows if row["QuadKey"] in wanted]
    if not matches:
        log("  no footprint files cover this district")
        return

    for row in matches:
        log(f"  {row['Location']} {row['QuadKey']} ({row['Size']})")
        download_file(
            row["Url"],
            RAW_ROOT / "ms_buildings" / f"{row['QuadKey']}.csv.gz",
        )


# ------------------------------------------------------------
# OPENSTREETMAP WATER
# ------------------------------------------------------------

def fetch_osm_water(district):
    import geopandas as gpd
    import pandas as pd

    log("\nOpenStreetMap lakes, wetlands and rivers")

    destination = RAW_ROOT / "osm" / f"{district}_water.gpkg"
    if destination.exists() and destination.stat().st_size > 0:
        log(f"  exists  {destination.relative_to(PROJECT_ROOT)}")
        return destination

    _, _, wgs84 = district_extent(district)

    with rasterio.Env(**GDAL_ENV):
        areas = gpd.read_file(OSM_EXTRACT.format(layer=OSM_WATER_AREAS), bbox=wgs84)
        lines = gpd.read_file(OSM_EXTRACT.format(layer=OSM_WATERWAYS), bbox=wgs84)

    areas["kind"] = areas["fclass"].map(OSM_AREA_KINDS)
    lines["kind"] = lines["fclass"].map(OSM_LINE_KINDS)
    # A river or canal mapped only as a line keeps its class, for its width.
    lines["line"] = lines["fclass"]
    areas["line"] = None

    found = pd.concat([areas, lines], ignore_index=True)
    found = found[found["kind"].notna()][["osm_id", "kind", "line", "name", "geometry"]]

    destination.parent.mkdir(parents=True, exist_ok=True)
    found.to_file(destination, driver="GPKG")
    log(f"  {len(found)} features -> {destination.relative_to(PROJECT_ROOT)}")
    log(f"  {found['kind'].value_counts().to_dict()}")
    return destination


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

FETCHERS = ["worldcover", "jrc", "buildings", "osm_water", "landsat"]


def main():
    parser = argparse.ArgumentParser(description="Fetch open datasets for a district.")
    parser.add_argument("--district", default="sxr")
    parser.add_argument("--what", nargs="+", choices=FETCHERS, default=FETCHERS)
    parser.add_argument("--years", default="2017-2025")
    args = parser.parse_args()

    if "worldcover" in args.what:
        fetch_worldcover(args.district)
    if "jrc" in args.what:
        fetch_jrc(args.district)
    if "buildings" in args.what:
        fetch_ms_buildings(args.district)
    if "osm_water" in args.what:
        fetch_osm_water(args.district)
    if "landsat" in args.what:
        fetch_landsat(args.district, parse_years(args.years))


if __name__ == "__main__":
    main()
