from pathlib import Path
import argparse
import gzip
import json
import shutil
import warnings

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import reproject, Resampling, transform_bounds
from scipy import ndimage
from shapely.geometry import box, shape


# ============================================================
# SHUHUL - STATIC DISTRICT LAYERS
# ============================================================
#
# Builds the layers that do not change from year to year, all on the
# district's 10 m master grid (processed/<district>/ndvi.tif).
#
# Input:
#
# processed/<district>/  ndvi.tif dem.tif slope.tif water.tif canopy.tif
#                        buildings.gpkg roads.gpkg heritage.gpkg
# rawdata/worldcover/<district>_worldcover_2021.tif
# rawdata/jrc_gsw/occurrence_*.tif  transitions_*.tif
# rawdata/ms_buildings/*.csv.gz
#
# Output:
#
# processed/<district>/
#   landcover.tif          ESA WorldCover 2021 classes
#   tree_height.tif        canopy height in metres where there are trees, else 0
#   buildings_ml.gpkg      machine-detected footprints (no names)
#   buildings.tif          share of each cell covered by any footprint, 0-1
#   roads.tif              1 where a motorable road passes
#   heritage.tif           1 inside the heritage buffer
#   forest.tif             1 in dense hill tree cover (stand-in for forest)
#   water_occurrence.tif   % of satellite looks with water, 1984-2021
#   water_lost.tif         1 where permanent or seasonal water has been lost
#   flood.tif              flood susceptibility index, 0-1
#   static_layers.json     what was built and the rules used
#
# The cost surface already looks for buildings.tif, roads.tif,
# heritage.tif and forest.tif by name, so these are picked up as soon
# as they exist. tree_height.tif keeps the project rule that a canopy
# value above zero means canopy, and makes that rule true.
#
# Usage:
#   python backend/scripts/build_static_layers.py --district sxr
#
# ============================================================


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = PROJECT_ROOT / "processed"
RAW_ROOT = PROJECT_ROOT / "rawdata"

# ESA WorldCover class codes.
WC_TREE = 10
WC_BUILT = 50
WC_WATER = 80

# The canopy height layer carries a height on every vegetated cell,
# crops and grass included, so on its own it cannot say where trees are.
# A cell counts as tree canopy only when the land-cover map also calls
# it tree cover. Lone trees inside built-up cells are missed.
TREE_MIN_HEIGHT_M = 5.0

# Roads a new alignment could reasonably share or upgrade.
MOTORABLE = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "living_street",
    "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
}

# India's monuments law keeps construction 100 m away from a protected
# monument. The heritage points here are mostly not notified monuments,
# so this is a planning buffer, not a legal boundary.
HERITAGE_BUFFER_M = 100.0

# Dense, tall, contiguous tree cover on hill slopes. Valley-floor stands
# of the same height are mostly plantations, orchards and gardens, which
# the canopy cost already protects. This is a satellite-derived stand-in
# for forest, not a legal forest boundary.
FOREST_MIN_CANOPY_M = 10.0
FOREST_MIN_PATCH_M2 = 50_000.0
FOREST_MIN_PATCH_SLOPE_DEG = 8.0

# JRC transition classes: 3 lost permanent water, 6 lost seasonal water.
JRC_LOST_CLASSES = (3, 6)
JRC_PERSISTENT_WATER_PCT = 50

# Flood susceptibility screening index. The valley floor is so flat that
# height above the nearest water barely varies, so most of the weight is
# on where water has actually been recorded and on local low ground.
FLOOD_WEIGHTS = {
    "water_history": 0.40,
    "low_ground": 0.30,
    "height_above_water": 0.20,
    "flatness": 0.10,
}
FLOOD_HISTORY_DECAY_M = 150.0
FLOOD_NEIGHBOURHOOD_M = 1000.0
FLOOD_LOW_GROUND_RANGE_M = 2.0
FLOOD_HEIGHT_M = 5.0
FLOOD_FLAT_SLOPE_DEG = 5.0
FLOOD_CLASSES = {"LOW": 0.45, "MODERATE": 0.65, "HIGH": 0.85}

BUILDING_SUPERSAMPLE = 2


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def log(message):
    print(message, flush=True)


def master_grid(district):
    with rasterio.open(PROCESSED_ROOT / district / "ndvi.tif") as src:
        data = src.read(1)
        valid = np.isfinite(data) & (data != src.nodata)
        return {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
            "bounds": tuple(src.bounds),
            "resolution": abs(src.transform.a),
        }, valid


def read_master(district, name):
    """Read a layer that is already on the master grid, nodata as NaN."""
    with rasterio.open(PROCESSED_ROOT / district / f"{name}.tif") as src:
        array = src.read(1).astype("float32")
        if src.nodata is not None:
            array[array == src.nodata] = np.nan
        return array


def warp_to_grid(path, grid, resampling, dtype, fill):
    """Bring any raster onto the master grid."""
    out = np.full((grid["height"], grid["width"]), fill, dtype=dtype)

    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            dst_transform=grid["transform"],
            dst_crs=grid["crs"],
            dst_nodata=fill,
            resampling=resampling,
        )
    return out


def write_grid(path, array, grid, dtype, nodata):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        dtype=dtype,
        count=1,
        width=grid["width"],
        height=grid["height"],
        crs=grid["crs"],
        transform=grid["transform"],
        nodata=nodata,
        compress="deflate",
        tiled=True,
    ) as dst:
        dst.write(array.astype(dtype), 1)
        dst.build_overviews([2, 4, 8, 16], Resampling.nearest)

    log(f"  wrote {path.relative_to(PROJECT_ROOT)}")


def masked(array, valid, nodata):
    out = array.copy()
    out[~valid] = nodata
    return out


def read_vector(district, name, grid):
    path = PROCESSED_ROOT / district / f"{name}.gpkg"
    if not path.exists():
        return None

    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(grid["crs"])

    gdf = gdf.to_crs(grid["crs"])
    return gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]


def burn(geometries, grid, all_touched):
    geometries = [geom for geom in geometries if geom is not None and not geom.is_empty]
    if not geometries:
        return np.zeros((grid["height"], grid["width"]), dtype="uint8")

    return rasterize(
        [(geom, 1) for geom in geometries],
        out_shape=(grid["height"], grid["width"]),
        transform=grid["transform"],
        fill=0,
        dtype="uint8",
        all_touched=all_touched,
    )


# ------------------------------------------------------------
# LAKES AND RIVERS
# ------------------------------------------------------------

# Half the width given to a river or canal that is mapped only as a line, m.
OSM_LINE_HALF_WIDTH_M = {"river": 10.0, "canal": 5.0}


def build_water_bodies(district, grid, valid):
    """
    Lakes, wetlands and rivers from OpenStreetMap, and a water layer that
    joins them to the satellite water index.

    The index misses the parts of a lake that are under weed or algae and
    reads them as land. A mapped lake outline does not.
    """
    log("\nLakes and rivers")

    source = RAW_ROOT / "osm" / f"{district}_water.gpkg"
    if not source.exists():
        log("  OpenStreetMap water not fetched; skipping (fetch_open_data.py --what osm_water)")
        return None

    frame = gpd.read_file(source)
    if frame.empty:
        log("  nothing mapped here")
        return None

    frame = frame.to_crs(grid["crs"])
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]

    # A river mapped as a line gets a nominal width.
    is_line = frame["line"].notna()
    frame.loc[is_line, "geometry"] = frame[is_line].apply(
        lambda row: row.geometry.buffer(OSM_LINE_HALF_WIDTH_M.get(row["line"], 5.0)), axis=1
    )
    frame = frame[frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    frame["geometry"] = frame.geometry.buffer(0)
    frame = frame[~frame.geometry.is_empty]

    frame.drop(columns="line").to_file(PROCESSED_ROOT / district / "water_osm.gpkg", driver="GPKG")

    standing = burn(frame[frame["kind"].isin(["lake", "wetland"])].geometry, grid, all_touched=False)
    flowing = burn(frame[frame["kind"] == "river"].geometry, grid, all_touched=True)
    # Where a river runs through a lake outline, it is the lake.
    flowing[standing > 0] = 0

    write_grid(PROCESSED_ROOT / district / "water_lakes.tif", masked(standing, valid, 255), grid, "uint8", 255)
    write_grid(PROCESSED_ROOT / district / "water_rivers.tif", masked(flowing, valid, 255), grid, "uint8", 255)

    # The water layer everything else reads: the satellite index, kept
    # aside under its own name the first time, joined with mapped water.
    water_path = PROCESSED_ROOT / district / "water.tif"
    index_path = PROCESSED_ROOT / district / "water_ndwi.tif"
    if not index_path.exists():
        shutil.copyfile(water_path, index_path)

    seen = np.nan_to_num(read_master(district, "water_ndwi"), nan=0.0) > 0
    joined = seen | (standing > 0) | (flowing > 0)
    write_grid(water_path, masked(joined.astype("uint8"), valid, 255), grid, "uint8", 255)

    cell_km2 = grid["resolution"] ** 2 / 1e6
    area = lambda cells: round(float((cells & valid).sum()) * cell_km2, 2)
    return {
        "mapped_features": int(len(frame)),
        "lakes_and_wetlands_km2": area(standing > 0),
        "rivers_km2": area(flowing > 0),
        "seen_by_satellite_km2": area(seen),
        "mapped_but_not_seen_km2": area(((standing > 0) | (flowing > 0)) & ~seen),
        "water_km2": area(joined),
    }


# ------------------------------------------------------------
# LAND COVER
# ------------------------------------------------------------

def build_landcover(district, grid, valid):
    source = RAW_ROOT / "worldcover" / f"{district}_worldcover_2021.tif"
    if not source.exists():
        log("  WorldCover clip not found; skipping land cover")
        return None

    landcover = warp_to_grid(source, grid, Resampling.nearest, "uint8", 0)
    write_grid(
        PROCESSED_ROOT / district / "landcover.tif",
        masked(landcover, valid, 0), grid, "uint8", 0,
    )
    return landcover


def build_tree_canopy(district, grid, valid, landcover):
    if landcover is None:
        return None, None

    height = np.nan_to_num(read_master(district, "canopy"), nan=0.0)
    trees = ((landcover == WC_TREE) & (height >= TREE_MIN_HEIGHT_M)).astype("uint8")

    write_grid(
        PROCESSED_ROOT / district / "tree_height.tif",
        masked(np.where(trees == 1, height, 0.0).astype("float32"), valid, -9999),
        grid, "float32", -9999,
    )

    cell_km2 = grid["resolution"] ** 2 / 1e6
    return trees, {
        "min_height_m": TREE_MIN_HEIGHT_M,
        "area_km2": round(float((trees.astype(bool) & valid).sum()) * cell_km2, 1),
        "share_of_district_pct": round(100 * float((trees.astype(bool) & valid).sum()) / float(valid.sum()), 1),
        "height_layer_cells_pct": round(100 * float(((height > 0) & valid).sum()) / float(valid.sum()), 1),
    }


# ------------------------------------------------------------
# BUILDINGS
# ------------------------------------------------------------

def load_ml_buildings(grid):
    """Read machine-detected footprints that fall inside the district extent."""
    west, south, east, north = transform_bounds(grid["crs"], "EPSG:4326", *grid["bounds"])
    geometries = []

    for path in sorted((RAW_ROOT / "ms_buildings").glob("*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                feature = json.loads(line)
                lon, lat = feature["geometry"]["coordinates"][0][0]
                if west <= lon <= east and south <= lat <= north:
                    geometries.append(shape(feature["geometry"]))

    if not geometries:
        return None

    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326").to_crs(grid["crs"])
    gdf = gdf[gdf.geometry.is_valid & gdf.intersects(box(*grid["bounds"]))].copy()
    gdf["building_id"] = np.arange(1, len(gdf) + 1)
    gdf["area_m2"] = gdf.geometry.area.round(1)
    gdf["source"] = "microsoft_ml"
    return gdf


def build_buildings(district, grid, valid):
    named = read_vector(district, "buildings", grid)
    detected = load_ml_buildings(grid)

    if detected is not None:
        path = PROCESSED_ROOT / district / "buildings_ml.gpkg"
        detected.to_file(path, layer="buildings_ml", driver="GPKG")
        log(f"  wrote {path.relative_to(PROJECT_ROOT)} ({len(detected):,} footprints)")

    geometries = []
    if named is not None:
        geometries.extend(named.geometry)
    if detected is not None:
        geometries.extend(detected.geometry)

    # Burn at a finer grid, then average, so a cell holds the share of
    # its area under a roof instead of a yes/no.
    n = BUILDING_SUPERSAMPLE
    fine = dict(grid)
    fine["transform"] = grid["transform"] * Affine.scale(1 / n)
    fine["width"] = grid["width"] * n
    fine["height"] = grid["height"] * n

    burned = burn(geometries, fine, all_touched=False)
    share = burned.reshape(grid["height"], n, grid["width"], n).mean(axis=(1, 3))

    write_grid(
        PROCESSED_ROOT / district / "buildings.tif",
        masked(share.astype("float32"), valid, -9999), grid, "float32", -9999,
    )

    return {
        "named_footprints": 0 if named is None else int(len(named)),
        "detected_footprints": 0 if detected is None else int(len(detected)),
        "roof_area_km2": round(float(share[valid].sum()) * grid["resolution"] ** 2 / 1e6, 2),
    }


# ------------------------------------------------------------
# ROADS, HERITAGE, FOREST
# ------------------------------------------------------------

def build_roads(district, grid, valid):
    roads = read_vector(district, "roads", grid)
    if roads is None:
        return None

    motorable = roads[roads["highway"].isin(MOTORABLE)]
    burned = burn(motorable.geometry, grid, all_touched=True)

    write_grid(
        PROCESSED_ROOT / district / "roads.tif",
        masked(burned, valid, 255), grid, "uint8", 255,
    )
    return {
        "segments": int(len(motorable)),
        "length_km": round(float(motorable.length.sum()) / 1000, 1),
    }


def build_heritage(district, grid, valid):
    heritage = read_vector(district, "heritage", grid)
    if heritage is None:
        return None

    burned = burn(heritage.geometry.buffer(HERITAGE_BUFFER_M), grid, all_touched=True)

    write_grid(
        PROCESSED_ROOT / district / "heritage.tif",
        masked(burned, valid, 255), grid, "uint8", 255,
    )
    return {
        "sites": int(len(heritage)),
        "buffer_m": HERITAGE_BUFFER_M,
        "area_km2": round(float(burned[valid].sum()) * grid["resolution"] ** 2 / 1e6, 2),
    }


def build_forest(district, grid, valid, trees):
    if trees is None:
        return None

    canopy = read_master(district, "canopy")
    slope = np.nan_to_num(read_master(district, "slope"), nan=0.0)
    dense = trees.astype(bool) & (np.nan_to_num(canopy, nan=0.0) >= FOREST_MIN_CANOPY_M)

    labels, count = ndimage.label(dense)
    sizes = np.bincount(labels.ravel())
    mean_slope = np.bincount(labels.ravel(), weights=slope.ravel()) / np.maximum(sizes, 1)
    min_cells = FOREST_MIN_PATCH_M2 / grid["resolution"] ** 2
    keep = (sizes >= min_cells) & (mean_slope >= FOREST_MIN_PATCH_SLOPE_DEG)
    keep[0] = False
    forest = keep[labels].astype("uint8")

    write_grid(
        PROCESSED_ROOT / district / "forest.tif",
        masked(forest, valid, 255), grid, "uint8", 255,
    )
    return {
        "min_canopy_m": FOREST_MIN_CANOPY_M,
        "min_patch_ha": FOREST_MIN_PATCH_M2 / 10_000,
        "min_patch_slope_deg": FOREST_MIN_PATCH_SLOPE_DEG,
        "patches": int(keep.sum()),
        "area_km2": round(float(forest[valid].sum()) * grid["resolution"] ** 2 / 1e6, 2),
    }


# ------------------------------------------------------------
# WATER HISTORY AND FLOOD
# ------------------------------------------------------------

def find_jrc(layer):
    matches = sorted((RAW_ROOT / "jrc_gsw").glob(f"{layer}_*.tif"))
    return matches[0] if matches else None


def build_water_history(district, grid, valid):
    occurrence_path = find_jrc("occurrence")
    transitions_path = find_jrc("transitions")

    if occurrence_path is None or transitions_path is None:
        log("  JRC surface water tiles not found; skipping water history")
        return None, None, None

    occurrence = warp_to_grid(occurrence_path, grid, Resampling.nearest, "uint8", 255)
    occurrence[occurrence > 100] = 0
    transitions = warp_to_grid(transitions_path, grid, Resampling.nearest, "uint8", 0)
    lost = np.isin(transitions, JRC_LOST_CLASSES).astype("uint8")

    write_grid(
        PROCESSED_ROOT / district / "water_occurrence.tif",
        masked(occurrence, valid, 255), grid, "uint8", 255,
    )
    write_grid(
        PROCESSED_ROOT / district / "water_lost.tif",
        masked(lost, valid, 255), grid, "uint8", 255,
    )

    cell_km2 = grid["resolution"] ** 2 / 1e6
    return occurrence, lost, {
        "ever_water_km2": round(float(((occurrence > 0) & valid).sum()) * cell_km2, 2),
        "lost_water_km2": round(float((lost.astype(bool) & valid).sum()) * cell_km2, 2),
    }


def build_flood(district, grid, valid, occurrence, lost):
    dem = read_master(district, "dem")
    slope = read_master(district, "slope")
    water = np.nan_to_num(read_master(district, "water"), nan=0.0) > 0

    if occurrence is not None:
        water |= occurrence >= JRC_PERSISTENT_WATER_PCT

    water &= np.isfinite(dem)
    if not water.any():
        log("  no water cells; skipping flood index")
        return None

    # Height of each cell above its nearest water cell. This is a quick
    # stand-in for height above nearest drainage: it ignores flow paths.
    _, (rows, cols) = ndimage.distance_transform_edt(
        ~water, sampling=grid["resolution"], return_indices=True
    )
    height = np.clip(dem - dem[rows, cols], 0, None)

    # Closeness to anywhere water has been recorded since 1984, which
    # includes past floods and former wetland as well as today's water.
    recorded = water.copy()
    if occurrence is not None:
        recorded |= (occurrence > 0) | lost.astype(bool)
    to_recorded = ndimage.distance_transform_edt(~recorded, sampling=grid["resolution"])

    # How far a cell sits below the average ground around it.
    filled = np.where(np.isfinite(dem), dem, np.nanmean(dem))
    cells = max(3, int(round(FLOOD_NEIGHBOURHOOD_M / grid["resolution"])) | 1)
    relative = ndimage.uniform_filter(filled, 5) - ndimage.uniform_filter(filled, cells)

    scores = {
        "water_history": np.exp(-to_recorded / FLOOD_HISTORY_DECAY_M),
        "low_ground": np.clip(0.5 - relative / (2 * FLOOD_LOW_GROUND_RANGE_M), 0, 1),
        "height_above_water": np.clip(1 - height / FLOOD_HEIGHT_M, 0, 1),
        "flatness": np.clip(1 - slope / FLOOD_FLAT_SLOPE_DEG, 0, 1),
    }

    index = sum(FLOOD_WEIGHTS[name] * scores[name] for name in FLOOD_WEIGHTS)
    index = index.astype("float32")

    usable = valid & np.isfinite(dem) & np.isfinite(slope) & ~water
    index[~usable] = -9999

    write_grid(PROCESSED_ROOT / district / "flood.tif", index, grid, "float32", -9999)

    cell_km2 = grid["resolution"] ** 2 / 1e6
    values = index[usable]
    low, moderate, high = (FLOOD_CLASSES[name] for name in ("LOW", "MODERATE", "HIGH"))
    return {
        "weights": FLOOD_WEIGHTS,
        "classes": FLOOD_CLASSES,
        "area_km2": {
            "LOW": round(float((values < low).sum()) * cell_km2, 1),
            "MODERATE": round(float(((values >= low) & (values < moderate)).sum()) * cell_km2, 1),
            "HIGH": round(float(((values >= moderate) & (values < high)).sum()) * cell_km2, 1),
            "VERY_HIGH": round(float((values >= high).sum()) * cell_km2, 1),
        },
    }


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def build(district):
    grid, valid = master_grid(district)

    log("=" * 70)
    log(f"STATIC LAYERS - {district}")
    log("=" * 70)
    log(f"Grid: {grid['width']} x {grid['height']} at {grid['resolution']:.0f} m")

    summary = {"district": district}

    landcover = build_landcover(district, grid, valid)
    if landcover is not None:
        cell_km2 = grid["resolution"] ** 2 / 1e6
        summary["landcover_km2"] = {
            "tree_cover": round(float(((landcover == WC_TREE) & valid).sum()) * cell_km2, 1),
            "built_up": round(float(((landcover == WC_BUILT) & valid).sum()) * cell_km2, 1),
            "water": round(float(((landcover == WC_WATER) & valid).sum()) * cell_km2, 1),
        }

    trees, summary["tree_canopy"] = build_tree_canopy(district, grid, valid, landcover)
    summary["buildings"] = build_buildings(district, grid, valid)
    summary["roads"] = build_roads(district, grid, valid)
    summary["heritage"] = build_heritage(district, grid, valid)
    summary["forest"] = build_forest(district, grid, valid, trees)

    build_water(district, grid, valid, summary)

    path = PROCESSED_ROOT / district / "static_layers.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(json.dumps(summary, indent=2))


def build_water(district, grid, valid, summary):
    """Everything that follows from where the water is: bodies, history, flood."""
    bodies = build_water_bodies(district, grid, valid)
    if bodies is not None:
        summary["water_bodies"] = bodies

    occurrence, lost, summary["water_history"] = build_water_history(district, grid, valid)
    summary["flood"] = build_flood(district, grid, valid, occurrence, lost)


def build_water_only(district):
    """Rebuild the water layers and keep the rest of the summary as it is."""
    grid, valid = master_grid(district)
    path = PROCESSED_ROOT / district / "static_layers.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"district": district}

    build_water(district, grid, valid, summary)

    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(json.dumps({key: summary[key] for key in ("water_bodies", "water_history", "flood") if key in summary}, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Build static district layers.")
    parser.add_argument("--district", default="sxr")
    parser.add_argument(
        "--only", choices=["water"],
        help="Rebuild just the water layers: lakes, rivers, water history and flood.",
    )
    args = parser.parse_args()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if args.only == "water":
            build_water_only(args.district)
        else:
            build(args.district)


if __name__ == "__main__":
    main()
