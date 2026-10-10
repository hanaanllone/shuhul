"""
Shuhul - Mitigation Engine
==========================

Finds local restoration opportunities around a proposed construction
corridor and assigns a practical intervention:

    open / degraded land  -> tree restoration
    sufficiently wide road -> bushes / shrubs
    suitable buildings    -> green / sod roofs

Design principle:
    SEARCH LOCALLY FIRST.
    Start near the construction corridor and progressively expand the
    search radius only when enough feasible opportunities are not found.

This is a planning-level engine. It does NOT claim that the interventions
are exact ecological or thermal equivalents.

Expected project structure:

Tsaay/
├── backend/
│   └── scripts/
│       └── mitigation_analyzer.py
├── processed/
│   └── <district>/
│       ├── ndvi.tif
│       ├── ndwi.tif
│       ├── water.tif
│       ├── canopy.tif
│       ├── buildings.gpkg
│       ├── heritage.gpkg
│       └── roads.gpkg
└── outputs/
    ├── routes/
    │   └── <district>/
    │       └── routes_<construction>.geojson
    ├── impacts/
    │   └── <district>/
    │       └── impact_<construction>.json
    └── mitigation/
        └── <district>/
            ├── mitigation_<construction>.json
            └── mitigation_<construction>.geojson

Dependencies:
    rasterio
    geopandas
    shapely
    numpy
    scipy
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union


# ============================================================
# DEFAULTS
# ============================================================

SEARCH_RADII_M = [250, 500, 1000, 2000, 5000]

NDVI_GREEN_THRESHOLD = 0.30
NDVI_OPEN_THRESHOLD = 0.30

# CHM/canopy is a height-like layer in this project.
# > 2 m is used as a planning-level "existing tree/canopy" mask.
CANOPY_HEIGHT_THRESHOLD_M = 2.0

NDWI_WATER_THRESHOLD = 0.20

# Mitigation feasibility buffers.
BUILDING_EXCLUSION_BUFFER_M = 5.0

# ESA WorldCover class for built-up land.
LANDCOVER_BUILT_UP = 50
HERITAGE_EXCLUSION_BUFFER_M = 20.0

# Minimum connected open-land patch.
MIN_OPEN_ZONE_AREA_M2 = 300.0

# Road intervention assumptions.
MIN_BUSH_ROAD_WIDTH_M = 10.0
# Trees are allowed on/along very wide roads only.
# Ordinary roads are excluded from tree-restoration candidates.
MIN_TREE_ROAD_WIDTH_M = 15.0
BUSH_BUFFER_M = 2.0

# Green-roof fallback assumption when actual roof area is unavailable.
AVERAGE_ROOF_AREA_M2 = 92.903  # 1,000 ft²

# We want a small shortlist rather than hundreds of raw candidates.
MAX_ZONES = 12

# At least this many candidate zones are desirable before expanding.
MIN_ZONES = 3

# A small total capacity threshold prevents selecting three tiny patches.
MIN_TOTAL_CAPACITY_M2 = 5000.0

# Mitigation land to look for, per unit of tree canopy a route removes.
# Twice the canopy is what the route is asked to replace; the rest is
# headroom, because repaying the heat it adds can take more than that.
CANOPY_CAPACITY_RATIO = 4.0

# Road class -> approximate planning width if an explicit width field
# is not available. These are only fallbacks.
ROAD_CLASS_WIDTHS_M = {
    "motorway": 15.0,
    "trunk": 12.0,
    "primary": 10.0,
    "secondary": 8.0,
    "tertiary": 6.0,
    "residential": 5.0,
    "unclassified": 4.5,
    "service": 3.5,
    "track": 2.5,
    "path": 2.0,
    "footway": 1.5,
    "pedestrian": 3.0,
}


# ============================================================
# GENERAL HELPERS
# ============================================================

def find_file(folder: Path, candidates: list[str], required: bool = False):
    """Find a file by exact case-insensitive filename or stem."""
    files = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}

    for name in candidates:
        path = files.get(name.lower())
        if path is not None:
            return path

        if not name.lower().endswith((".tif", ".tiff", ".gpkg", ".geojson", ".json")):
            for suffix in [".tif", ".tiff", ".gpkg", ".geojson", ".json"]:
                path = files.get((name + suffix).lower())
                if path is not None:
                    return path

    if required:
        raise FileNotFoundError(
            f"Could not find any of {candidates} in {folder}"
        )

    return None


def first_existing(folder: Path, names: list[str], required=False):
    return find_file(folder, names, required=required)


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data):
    """
    Write JSON-safe output.

    Shapely geometries are intentionally excluded from the JSON payload.
    The corresponding GeoJSON file contains the actual zone geometries.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    def clean(value):
        if isinstance(value, dict):
            return {
                key: clean(val)
                for key, val in value.items()
                if key not in {"geometry", "point"}
            }

        if isinstance(value, list):
            return [clean(item) for item in value]

        if isinstance(value, np.integer):
            return int(value)

        if isinstance(value, np.floating):
            return float(value)

        return value

    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean(data), f, indent=2)


def safe_float(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def find_property(props: dict, names: list[str]):
    """Case-insensitive property lookup."""
    lowered = {str(k).lower(): v for k, v in props.items()}

    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]

    return None


# ============================================================
# ROUTE LOADING
# ============================================================

def load_routes(route_file: Path, target_crs: str):
    """
    Load route GeoJSON.

    The current route planner writes one Feature per route and stores
    the route name in the 'route' property.
    """
    routes = gpd.read_file(route_file)

    if routes.empty:
        raise ValueError(f"No routes found in {route_file}")

    if routes.crs is None:
        routes = routes.set_crs("EPSG:4326")

    routes = routes.to_crs(target_crs)

    route_name_col = None
    for col in routes.columns:
        if col.lower() == "route":
            route_name_col = col
            break

    if route_name_col is None:
        # Fallback: one feature = one route.
        routes["_route_name"] = [
            f"Route {chr(65 + i)}" for i in range(len(routes))
        ]
        route_name_col = "_route_name"

    output = []

    for _, row in routes.iterrows():
        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        output.append(
            {
                "route": str(row[route_name_col]),
                "geometry": geom,
            }
        )

    if not output:
        raise ValueError(f"No valid route geometries found in {route_file}")

    return output


# ============================================================
# IMPACT LOADING
# ============================================================

def load_route_impacts(impact_file: Path):
    """
    Load impact JSON.

    Supports the current structure:
        {
            "Route A — Shortest": {...},
            "Route B — Balanced": {...},
            ...
        }

    Also supports a top-level 'routes' dictionary if used later.
    """
    data = read_json(impact_file)

    if isinstance(data.get("routes"), dict):
        source = data["routes"]
    else:
        source = {
            k: v
            for k, v in data.items()
            if isinstance(v, dict)
            and (
                "route" in v
                or "green_space" in v
                or "impact_corridor_area_m2" in v
            )
        }

    return source


def impact_for_route(route_name: str, impacts: dict):
    if route_name in impacts:
        return impacts[route_name]

    # Fuzzy fallback.
    route_lower = route_name.lower()
    for key, value in impacts.items():
        if str(key).lower() == route_lower:
            return value

    for key, value in impacts.items():
        if route_lower in str(key).lower() or str(key).lower() in route_lower:
            return value

    return {}


# ============================================================
# RASTER HELPERS
# ============================================================

def raster_info(path: Path):
    with rasterio.open(path) as src:
        return src.crs, src.transform, src.width, src.height


def read_window(path: Path, bounds, reference_path: Path):
    """
    Read a raster over the same window as the reference NDVI raster.
    All processed rasters are expected to share the same master grid.
    """
    with rasterio.open(reference_path) as ref:
        window = from_bounds(
            bounds[0],
            bounds[1],
            bounds[2],
            bounds[3],
            transform=ref.transform,
        )

        window = window.round_offsets().round_lengths()

        # Clip to raster.
        full = rasterio.windows.Window(
            0, 0, ref.width, ref.height
        )
        window = window.intersection(full)

        transform = rasterio.windows.transform(window, ref.transform)

    with rasterio.open(path) as src:
        arr = src.read(
            1,
            window=window,
            boundless=False,
        ).astype("float32")

        nodata = src.nodata

    if nodata is not None:
        arr[arr == nodata] = np.nan

    arr[~np.isfinite(arr)] = np.nan

    return arr, transform, window


def pixel_area_m2(transform):
    return abs(transform.a * transform.e)


def raster_geometry_mask(geometry, out_shape, transform, invert=False):
    return geometry_mask(
        [geometry],
        out_shape=out_shape,
        transform=transform,
        invert=invert,
    )


# ============================================================
# CANDIDATE MASK
# ============================================================
def build_road_masks(
    roads,
    search_area,
    transform,
    out_shape,
):
    """
    Build road-surface masks for mitigation planning.

    The roads dataset contains road geometries/centerlines, so we
    convert each road to an approximate physical road footprint using
    its inferred width.

    Returns:

        road_surface_mask:
            Approximate physical road surface.

        wide_road_mask:
            Road surfaces whose inferred width is >=
            MIN_TREE_ROAD_WIDTH_M.

    IMPORTANT:
        Tree restoration must never be placed on the physical
        road surface.

        A wide road may make its surrounding verge/edge relevant
        for vegetation planning, but the carriageway itself remains
        excluded.
    """

    road_surface_mask = np.zeros(
        out_shape,
        dtype=bool,
    )

    wide_road_mask = np.zeros(
        out_shape,
        dtype=bool,
    )

    if roads is None or roads.empty:
        return road_surface_mask, wide_road_mask

    subset = roads[
        roads.geometry.intersects(search_area)
    ]

    if subset.empty:
        return road_surface_mask, wide_road_mask

    for _, row in subset.iterrows():

        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        width_m, width_source = infer_road_width(row)

        # --------------------------------------------------------
        # If width is unknown, use a conservative fallback.
        # We still exclude the road centerline + small buffer
        # rather than allowing trees directly on it.
        # --------------------------------------------------------

        if width_m is None:
            road_half_width = 3.0
        else:
            road_half_width = max(
                float(width_m) / 2.0,
                2.0,
            )

        # Add a small safety margin around the estimated
        # carriageway.
        road_surface = geom.buffer(
            road_half_width + 1.0
        )

        if road_surface.is_empty:
            continue

        # --------------------------------------------------------
        # Rasterize the ACTUAL APPROXIMATE ROAD SURFACE.
        # --------------------------------------------------------

        road_pixels = geometry_mask(
            [road_surface],
            out_shape=out_shape,
            transform=transform,
            invert=True,
        )

        road_surface_mask |= road_pixels

        # Keep track of wide roads separately for possible
        # future roadside-verge logic.
        if (
            width_m is not None
            and width_m >= MIN_TREE_ROAD_WIDTH_M
        ):
            wide_road_mask |= road_pixels

    return road_surface_mask, wide_road_mask

def build_open_land_mask(
    ndvi,
    ndwi,
    water,
    canopy,
    building_mask,
    heritage_mask,
    corridor_mask,
    road_mask,
    wide_road_mask,
):
    """
    Create the mask for open/degraded land suitable for tree restoration.

    A candidate pixel must:
      - have valid NDVI
      - have low enough NDVI to represent open/degraded land
      - not be water / high NDWI
      - not be an existing tree/canopy pixel
      - not be a building exclusion area
      - not be heritage exclusion area
      - not be inside the construction corridor
    """
    valid = np.isfinite(ndvi)

    water_mask = np.zeros_like(valid, dtype=bool)

    if water is not None:
        water_mask |= np.isfinite(water) & (water > 0)

    if ndwi is not None:
        water_mask |= np.isfinite(ndwi) & (ndwi >= NDWI_WATER_THRESHOLD)

    existing_canopy = np.zeros_like(valid, dtype=bool)

    if canopy is not None:
        existing_canopy = (
            np.isfinite(canopy)
            & (canopy >= CANOPY_HEIGHT_THRESHOLD_M)
        )

    # ------------------------------------------------------------
    # Road handling
    # ------------------------------------------------------------
    #
    # Normal roads must NEVER become tree-restoration zones.
    #
    # Very wide roads are explicitly allowed by the current
    # planning assumption.
    #
    # Therefore:
    #
    #     road + not wide  -> excluded
    #     road + wide      -> allowed
    #     non-road         -> allowed
    #
    # Never plant trees on the physical road surface.
    road_exclusion = road_mask

    open_land = (
        valid
        & (ndvi <= NDVI_OPEN_THRESHOLD)
        & ~water_mask
        & ~existing_canopy
        & ~building_mask
        & ~heritage_mask
        & ~corridor_mask
        & ~road_exclusion
    )

    return open_land


# ============================================================
# OPEN LAND ZONES
# ============================================================

def find_open_land_zones(
    mask,
    transform,
    corridor_geometry,
    max_zones=15,
):
    """
    Convert connected open-land patches into polygons.

    8-connected pixels are treated as belonging to the same patch.
    """
    if not mask.any():
        return []

    structure = np.ones((3, 3), dtype=np.uint8)
    labels, count = ndimage.label(mask, structure=structure)

    if count == 0:
        return []

    area_per_pixel = pixel_area_m2(transform)
    candidates = []

    for label_id in range(1, count + 1):
        component = labels == label_id
        pixel_count = int(component.sum())
        area_m2 = pixel_count * area_per_pixel

        if area_m2 < MIN_OPEN_ZONE_AREA_M2:
            continue

        geoms = list(
            shapes(
                component.astype("uint8"),
                mask=component,
                transform=transform,
            )
        )

        if not geoms:
            continue

        geom = unary_union(
            [shape(g) for g, value in geoms if value == 1]
        )

        if geom.is_empty:
            continue

        distance_m = float(geom.distance(corridor_geometry))

        candidates.append(
            {
                "geometry": geom,
                "intervention": "tree_restoration",
                "area_m2": float(area_m2),
                "distance_m": distance_m,
                "source": "open_land",
            }
        )

    candidates.sort(key=lambda x: (x["distance_m"], -x["area_m2"]))

    return candidates[:max_zones]


# ============================================================
# VECTOR LAYERS
# ============================================================

def load_vector(path: Path | None, target_crs: str):
    if path is None:
        return None

    gdf = gpd.read_file(path)

    if gdf.empty:
        # Keep CRS information if possible.
        if gdf.crs is None:
            gdf = gdf.set_crs(target_crs)
        else:
            gdf = gdf.to_crs(target_crs)
        return gdf

    if gdf.crs is None:
        gdf = gdf.set_crs(target_crs)

    return gdf.to_crs(target_crs)


def vector_mask(gdf, geometry, transform, out_shape, buffer_m=0):
    if gdf is None or gdf.empty:
        return np.zeros(out_shape, dtype=bool)

    search_geom = geometry

    subset = gdf[gdf.geometry.intersects(search_geom)]

    if subset.empty:
        return np.zeros(out_shape, dtype=bool)

    geoms = []

    for geom in subset.geometry:
        if geom is None or geom.is_empty:
            continue

        if buffer_m > 0:
            geom = geom.buffer(buffer_m)

        geoms.append(geom)

    if not geoms:
        return np.zeros(out_shape, dtype=bool)

    union = unary_union(geoms)

    return geometry_mask(
        [union],
        out_shape=out_shape,
        transform=transform,
        invert=True,
    )


# ============================================================
# ROAD WIDTH / ROAD INTERVENTIONS
# ============================================================

def infer_road_width(row):
    """
    Try to determine a road width from available attributes.

    Priority:
      1. explicit width-like field
      2. lanes field
      3. highway / class / type fallback

    Returns:
      width_m, source
    """
    props = row.to_dict()

    explicit_names = [
        "width",
        "road_width",
        "width_m",
        "carriageway_width",
        "estimated_width",
    ]

    value = find_property(props, explicit_names)

    if value is not None:
        width = safe_float(value)
        if width is not None and width > 0:
            return width, "explicit_width"

    lanes_value = find_property(
        props,
        ["lanes", "lane_count", "num_lanes"],
    )

    lanes = safe_float(lanes_value)

    if lanes is not None and lanes > 0:
        return lanes * 3.0, "lanes_estimate"

    road_class = find_property(
        props,
        ["highway", "road_class", "class", "type", "road_type"],
    )

    if road_class is not None:
        key = str(road_class).lower().strip()

        for road_type, width in ROAD_CLASS_WIDTHS_M.items():
            if key == road_type or road_type in key:
                return width, f"class_estimate:{road_type}"

    return None, "unknown"


def find_road_bush_candidates(
    roads,
    search_area,
    corridor_geometry,
    max_candidates=15,
):
    if roads is None or roads.empty:
        return []

    subset = roads[roads.geometry.intersects(search_area)]

    candidates = []

    for _, row in subset.iterrows():
        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        width_m, width_source = infer_road_width(row)

        if width_m is None:
            # We do not invent a width when the dataset gives us
            # insufficient information.
            continue

        if width_m < MIN_BUSH_ROAD_WIDTH_M:
            continue

        # Approximate usable roadside intervention strip.
        intervention_width = min(BUSH_BUFFER_M, max(width_m / 4.0, 1.0))
        intervention_geom = geom.buffer(intervention_width)

        # Never place the proposed restoration inside the construction
        # corridor itself.
        intervention_geom = intervention_geom.difference(corridor_geometry)

        if intervention_geom.is_empty:
            continue

        area_m2 = float(intervention_geom.area)

        if area_m2 < 100:
            continue

        candidates.append(
            {
                "geometry": intervention_geom,
                "intervention": "bush_restoration",
                "area_m2": area_m2,
                "distance_m": float(
                    intervention_geom.distance(corridor_geometry)
                ),
                "source": "road",
                "road_width_m": float(width_m),
                "road_width_source": width_source,
            }
        )

    candidates.sort(key=lambda x: (x["distance_m"], -x["area_m2"]))

    return candidates[:max_candidates]


# ============================================================
# GREEN ROOF CANDIDATES
# ============================================================

def find_green_roof_candidates(
    buildings,
    heritage,
    water_geometry,
    search_area,
    corridor_geometry,
    max_candidates=15,
):
    if buildings is None or buildings.empty:
        return []

    subset = buildings[buildings.geometry.intersects(search_area)]

    if subset.empty:
        return []

    heritage_union = None

    if heritage is not None and not heritage.empty:
        heritage_subset = heritage[
            heritage.geometry.intersects(search_area)
        ]

        if not heritage_subset.empty:
            heritage_union = unary_union(
                [
                    g.buffer(HERITAGE_EXCLUSION_BUFFER_M)
                    for g in heritage_subset.geometry
                    if g is not None and not g.is_empty
                ]
            )

    candidates = []

    for _, row in subset.iterrows():
        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        # Heritage buildings/sites are not recommended for the generic
        # green-roof intervention in this MVP.
        if heritage_union is not None and geom.intersects(heritage_union):
            continue

        # Do not recommend a roof intervention for a building sitting
        # directly inside the water geometry.
        if water_geometry is not None and geom.intersects(water_geometry):
            continue

        point = geom.representative_point()

        candidates.append(
            {
                "geometry": geom,
                "point": point,
                "intervention": "green_roof",
                "estimated_roof_area_m2": AVERAGE_ROOF_AREA_M2,
                "distance_m": float(point.distance(corridor_geometry)),
                "source": "building",
            }
        )

    candidates.sort(key=lambda x: x["distance_m"])

    # Group nearby buildings into practical "zones".
    # 100 m grid-like clustering is approximated by sequential buffering.
    zones = []

    for candidate in candidates:
        assigned = False

        for zone in zones:
            if candidate["point"].distance(zone["geometry"]) <= 100:
                zone["geometry"] = zone["geometry"].union(
                    candidate["geometry"]
                )
                zone["building_count"] += 1
                zone["estimated_roof_area_m2"] += (
                    AVERAGE_ROOF_AREA_M2
                )
                zone["distance_m"] = min(
                    zone["distance_m"],
                    candidate["distance_m"],
                )
                assigned = True
                break

        if not assigned:
            zones.append(
                {
                    "geometry": candidate["geometry"],
                    "intervention": "green_roof",
                    "building_count": 1,
                    "estimated_roof_area_m2": AVERAGE_ROOF_AREA_M2,
                    "distance_m": candidate["distance_m"],
                    "source": "building",
                }
            )

    zones.sort(key=lambda x: x["distance_m"])

    return zones[:max_candidates]


# ============================================================
# CANDIDATE DEDUPLICATION / RANKING
# ============================================================

def candidate_key(candidate):
    return (
        candidate["intervention"],
        round(candidate["distance_m"], 1),
        round(candidate.get("area_m2", candidate.get("estimated_roof_area_m2", 0)), 1),
    )


def merge_candidates(open_candidates, road_candidates, roof_candidates):
    candidates = []

    candidates.extend(open_candidates)
    candidates.extend(road_candidates)
    candidates.extend(roof_candidates)

    # Distance is the primary ranking criterion.
    # Larger capacity breaks ties.
    for candidate in candidates:
        candidate["capacity_m2"] = float(
            candidate.get(
                "area_m2",
                candidate.get("estimated_roof_area_m2", 0),
            )
        )

    candidates.sort(
        key=lambda x: (
            x["distance_m"],
            -x["capacity_m2"],
        )
    )

    unique = []
    seen = set()

    for candidate in candidates:
        key = candidate_key(candidate)

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return unique


def select_local_zones(candidates, required_m2=MIN_TOTAL_CAPACITY_M2):
    """
    Select the nearest practical zones.

    We intentionally do NOT optimize for a single global score.
    Distance is primary because this engine is local-first.

    Zones are taken nearest first until together they can hold what the
    route needs, with at least MIN_ZONES so the planner has a choice.
    """
    selected = []
    total_capacity = 0.0

    for candidate in candidates:
        if len(selected) >= MAX_ZONES:
            break

        if len(selected) >= MIN_ZONES and total_capacity >= required_m2:
            break

        selected.append(candidate)
        total_capacity += candidate["capacity_m2"]

    return selected, total_capacity


# ============================================================
# GEOJSON OUTPUT
# ============================================================
def make_feature_collection(routes_output, source_crs, output_crs="EPSG:4326"):
    """
    Convert mitigation geometries from the internal/project CRS
    to WGS84 before writing GeoJSON.

    Internal processing:
        EPSG:32643

    GeoJSON:
        EPSG:4326
    """

    features = []

    for route_result in routes_output:
        route_name = route_result["route"]

        for zone in route_result["selected_zones"]:

            # ------------------------------------------------
            # Convert geometry to WGS84
            # ------------------------------------------------

            geom = zone["geometry"]

            if geom is None or geom.is_empty:
                continue

            zone_gdf = gpd.GeoDataFrame(
                {"geometry": [geom]},
                crs=source_crs,
            )

            zone_gdf = zone_gdf.to_crs(output_crs)

            geom_wgs84 = zone_gdf.geometry.iloc[0]

            if geom_wgs84.is_empty:
                continue

            # ------------------------------------------------
            # Properties
            # ------------------------------------------------

            props = {
                "route": route_name,
                "zone_id": zone["zone_id"],
                "intervention": zone["intervention"],
                "distance_m": round(zone["distance_m"], 2),
                "capacity_m2": round(zone["capacity_m2"], 2),
                "source": zone.get("source"),
            }

            if "area_m2" in zone:
                props["area_m2"] = round(zone["area_m2"], 2)

            if "building_count" in zone:
                props["building_count"] = zone["building_count"]

            if "estimated_roof_area_m2" in zone:
                props["estimated_roof_area_m2"] = round(
                    zone["estimated_roof_area_m2"],
                    2,
                )

            if "road_width_m" in zone:
                props["road_width_m"] = round(
                    zone["road_width_m"],
                    2,
                )

            features.append(
                {
                    "type": "Feature",
                    "geometry": geom_wgs84.__geo_interface__,
                    "properties": props,
                }
            )

    return {
        "type": "FeatureCollection",
        "features": features,
    }
# ============================================================
# MAIN ROUTE PROCESSOR
# ============================================================

def process_route(
    route,
    impact,
    district_dir,
    radius,
    ndvi_path,
    ndwi_path,
    water_path,
    canopy_path,
    buildings,
    heritage,
    roads,
):
    route_name = route["route"]
    route_geometry = route["geometry"]

    # --------------------------------------------------------
    # Construction impact corridor
    # --------------------------------------------------------

    project_width_m = float(
        impact.get(
            "project_width_m",
            impact.get("assumptions", {}).get(
                "corridor_width_m",
                20.0,
            ),
        )
    )

    corridor = route_geometry.buffer(project_width_m / 2.0)

    # Local search zone around construction.
    search_area = corridor.buffer(radius)

    # --------------------------------------------------------
    # Reference raster window
    # --------------------------------------------------------

    with rasterio.open(ndvi_path) as src:
        window = from_bounds(
            *search_area.bounds,
            transform=src.transform,
        ).round_offsets().round_lengths()

        full = rasterio.windows.Window(
            0, 0, src.width, src.height
        )

        window = window.intersection(full)

        transform = rasterio.windows.transform(
            window,
            src.transform,
        )

        ndvi = src.read(1, window=window).astype("float32")
        nodata = src.nodata

        if nodata is not None:
            ndvi[ndvi == nodata] = np.nan

    def read_same_window(path):
        if path is None:
            return None

        with rasterio.open(path) as src:
            arr = src.read(1, window=window).astype("float32")
            nodata = src.nodata

            if nodata is not None:
                arr[arr == nodata] = np.nan

            arr[~np.isfinite(arr)] = np.nan

            return arr

    ndwi = read_same_window(ndwi_path)
    water = read_same_window(water_path)
    canopy = read_same_window(canopy_path)

    shape_ = ndvi.shape

    # --------------------------------------------------------
    # Raster masks
    # --------------------------------------------------------

    building_mask = vector_mask(
        buildings,
        search_area,
        transform,
        shape_,
        buffer_m=BUILDING_EXCLUSION_BUFFER_M,
    )

    # The named footprints cover only a fraction of real buildings.
    # Where the fuller layers exist, ground under a detected roof or
    # mapped as built-up is not open land either.
    roof_share = read_same_window(
        first_existing(district_dir, ["buildings.tif"])
    )
    if roof_share is not None:
        building_mask = building_mask | (
            np.isfinite(roof_share) & (roof_share > 0)
        )

    landcover = read_same_window(
        first_existing(district_dir, ["landcover.tif"])
    )
    if landcover is not None:
        building_mask = building_mask | (landcover == LANDCOVER_BUILT_UP)

    heritage_mask = vector_mask(
        heritage,
        search_area,
        transform,
        shape_,
        buffer_m=HERITAGE_EXCLUSION_BUFFER_M,
    )

    corridor_mask = raster_geometry_mask(
        corridor,
        shape_,
        transform,
        invert=True,
    )
    road_mask, wide_road_mask = build_road_masks(
        roads=roads,
        search_area=search_area,
        transform=transform,
        out_shape=shape_,
    )

    open_mask = build_open_land_mask(
        ndvi=ndvi,
        ndwi=ndwi,
        water=water,
        canopy=canopy,
        building_mask=building_mask,
        heritage_mask=heritage_mask,
        corridor_mask=corridor_mask,
        road_mask=road_mask,
        wide_road_mask=wide_road_mask,
    )

    open_candidates = find_open_land_zones(
        open_mask,
        transform,
        corridor,
    )

    # --------------------------------------------------------
    # Vector water geometry for roof exclusion
    # --------------------------------------------------------

    water_geometry = None

    water_parts = []

    if water is not None:
        # Raster water geometry is expensive to vectorize over huge areas.
        # For this local search window it is acceptable.
        water_bool = np.isfinite(water) & (water > 0)

        if ndwi is not None:
            water_bool |= (
                np.isfinite(ndwi)
                & (ndwi >= NDWI_WATER_THRESHOLD)
            )

        if water_bool.any():
            for geom_json, value in shapes(
                water_bool.astype("uint8"),
                mask=water_bool,
                transform=transform,
            ):
                if value == 1:
                    water_parts.append(shape(geom_json))

    if water_parts:
        water_geometry = unary_union(water_parts)

    # --------------------------------------------------------
    # Road candidates
    # --------------------------------------------------------

    road_candidates = find_road_bush_candidates(
        roads=roads,
        search_area=search_area,
        corridor_geometry=corridor,
    )

    # --------------------------------------------------------
    # Green-roof candidates
    # --------------------------------------------------------

    roof_candidates = find_green_roof_candidates(
        buildings=buildings,
        heritage=heritage,
        water_geometry=water_geometry,
        search_area=search_area,
        corridor_geometry=corridor,
    )

    candidates = merge_candidates(
        open_candidates,
        road_candidates,
        roof_candidates,
    )

    # --------------------------------------------------------
    # Impact references
    # --------------------------------------------------------

    green_area = safe_float(
        impact.get("green_space", {}).get("green_area_m2")
    )

    canopy_area = safe_float(
        impact.get("canopy", {}).get("canopy_area_m2")
    )

    required_capacity = max(
        MIN_TOTAL_CAPACITY_M2,
        CANOPY_CAPACITY_RATIO * (canopy_area or 0.0),
    )

    selected, total_capacity = select_local_zones(
        candidates,
        required_capacity,
    )

    # Assign Zone A / B / C.
    for index, zone in enumerate(selected):
        zone["zone_id"] = f"Zone {chr(65 + index)}"

    return {
        "route": route_name,
        "construction": impact.get("construction"),
        "search_radius_m": radius,
        "project_width_m": project_width_m,
        "impact_corridor_area_m2": safe_float(
            impact.get("impact_corridor_area_m2")
        ),
        "impact_reference": {
            "green_area_m2": green_area,
            "canopy_area_m2": canopy_area,
        },
        "candidate_summary": {
            "total_candidates_found": len(candidates),
            "tree_candidates": sum(
                x["intervention"] == "tree_restoration"
                for x in candidates
            ),
            "bush_candidates": sum(
                x["intervention"] == "bush_restoration"
                for x in candidates
            ),
            "green_roof_candidates": sum(
                x["intervention"] == "green_roof"
                for x in candidates
            ),
            "selected_zone_count": len(selected),
            "selected_capacity_m2": total_capacity,
            "required_capacity_m2": required_capacity,
        },
        "selected_zones": selected,
    }


# ============================================================
# LOCAL-FIRST SEARCH
# ============================================================

def find_mitigation_for_route(
    route,
    impact,
    district_dir,
    ndvi_path,
    ndwi_path,
    water_path,
    canopy_path,
    buildings,
    heritage,
    roads,
):
    """
    Expand the search radius until we have enough local candidates.

    The search radius itself is part of the output so the UI can explain
    how far Shuhul had to look.
    """
    last_result = None

    for radius in SEARCH_RADII_M:
        result = process_route(
            route=route,
            impact=impact,
            district_dir=district_dir,
            radius=radius,
            ndvi_path=ndvi_path,
            ndwi_path=ndwi_path,
            water_path=water_path,
            canopy_path=canopy_path,
            buildings=buildings,
            heritage=heritage,
            roads=roads,
        )

        last_result = result

        zones = result["candidate_summary"]["selected_zone_count"]
        capacity = result["candidate_summary"]["selected_capacity_m2"]

        print(
            f"    Search radius {radius:>5} m | "
            f"candidates={result['candidate_summary']['total_candidates_found']:>3} | "
            f"selected={zones} | "
            f"capacity={capacity:,.1f} m²"
        )

        if (
            zones >= MIN_ZONES
            and capacity >= result["candidate_summary"]["required_capacity_m2"]
        ):
            result["search_status"] = "sufficient_local_opportunities_found"
            return result

        # Looking farther only helps while there is room for more zones.
        if zones >= MAX_ZONES:
            result["search_status"] = "nearest_zones_selected"
            return result

    last_result["search_status"] = "expanded_to_maximum_radius"
    return last_result


# ============================================================
# CLI
# ============================================================

def main():
    global AVERAGE_ROOF_AREA_M2
    global MIN_BUSH_ROAD_WIDTH_M
    global MIN_TREE_ROAD_WIDTH_M
    global MAX_ZONES

    parser = argparse.ArgumentParser(
        description=(
            "Shuhul local-first mitigation and restoration-zone analyzer."
        )
    )

    parser.add_argument(
        "--district",
        required=True,
        help="District code, e.g. sxr",
    )

    parser.add_argument(
        "--construction",
        choices=["road", "bridge", "flyover"],
        default="road",
    )

    parser.add_argument(
        "--processed-root",
        default=None,
        help="Defaults to <project_root>/processed",
    )

    parser.add_argument(
        "--route-file",
        default=None,
        help="Optional route GeoJSON override.",
    )

    parser.add_argument(
        "--impact-file",
        default=None,
        help="Optional impact JSON override.",
    )

    parser.add_argument(
        "--average-roof-area-ft2",
        type=float,
        default=1000.0,
        help="Regional average roof area fallback.",
    )

    parser.add_argument(
        "--min-bush-road-width-m",
        type=float,
        default=MIN_BUSH_ROAD_WIDTH_M,
        help="Minimum road width for bush/shrub intervention.",
    )

    parser.add_argument(
    "--min-tree-road-width-m",
    type=float,
    default=MIN_TREE_ROAD_WIDTH_M,
    help=(
        "Minimum road width for considering tree restoration "
        "on very wide roads."
    ),
    )



    parser.add_argument(
        "--max-zones",
        type=int,
        default=MAX_ZONES,
        help="Maximum recommended zones per route.",
    )

    args = parser.parse_args()

    # Apply configurable values.
    AVERAGE_ROOF_AREA_M2 = (
        args.average_roof_area_ft2 * 0.092903
    )
    MIN_BUSH_ROAD_WIDTH_M = args.min_bush_road_width_m
    MAX_ZONES = max(1, args.max_zones)
    MIN_TREE_ROAD_WIDTH_M = args.min_tree_road_width_m

    # --------------------------------------------------------
    # Project paths
    # --------------------------------------------------------

    project_root = Path(__file__).resolve().parents[2]

    processed_root = (
        Path(args.processed_root)
        if args.processed_root
        else project_root / "processed"
    )

    district_dir = processed_root / args.district

    if not district_dir.exists():
        raise FileNotFoundError(
            f"District directory not found: {district_dir}"
        )

    route_file = (
        Path(args.route_file)
        if args.route_file
        else (
            project_root
            / "outputs"
            / "routes"
            / args.district
            / f"routes_{args.construction}.geojson"
        )
    )

    impact_file = (
        Path(args.impact_file)
        if args.impact_file
        else (
            project_root
            / "outputs"
            / "impacts"
            / args.district
            / f"impact_{args.construction}.json"
        )
    )

    if not route_file.exists():
        raise FileNotFoundError(
            f"Route file not found: {route_file}"
        )

    if not impact_file.exists():
        raise FileNotFoundError(
            f"Impact file not found: {impact_file}"
        )

    # --------------------------------------------------------
    # Layers
    # --------------------------------------------------------

    ndvi_path = first_existing(
        district_dir,
        ["ndvi.tif", "ndvi"],
        required=True,
    )

    ndwi_path = first_existing(
        district_dir,
        ["ndwi.tif", "ndwi"],
    )

    water_path = first_existing(
        district_dir,
        ["water.tif", "water"],
    )

    canopy_path = first_existing(
        district_dir,
        ["tree_height.tif", "canopy.tif", "canopy", "chm.tif", "chm"],
    )

    buildings_path = first_existing(
        district_dir,
        ["buildings.gpkg", "buildings"],
    )

    heritage_path = first_existing(
        district_dir,
        ["heritage.gpkg", "heritage"],
    )

    roads_path = first_existing(
        district_dir,
        ["roads.gpkg", "roads"],
    )

    # --------------------------------------------------------
    # CRS
    # --------------------------------------------------------

    with rasterio.open(ndvi_path) as src:
        target_crs = src.crs

    if target_crs is None:
        raise ValueError(
            f"NDVI raster has no CRS: {ndvi_path}"
        )

    # --------------------------------------------------------
    # Load vectors/routes/impacts
    # --------------------------------------------------------

    routes = load_routes(
        route_file,
        target_crs,
    )

    impacts = load_route_impacts(
        impact_file
    )

    buildings = load_vector(
        buildings_path,
        target_crs,
    )

    heritage = load_vector(
        heritage_path,
        target_crs,
    )

    roads = load_vector(
        roads_path,
        target_crs,
    )

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print("SHUHUL MITIGATION ENGINE")
    print("=" * 78)
    print(f"District:             {args.district}")
    print(f"Construction:         {args.construction}")
    print(f"Average roof area:    {args.average_roof_area_ft2:,.0f} ft²")
    print(f"Minimum bush road:    {MIN_BUSH_ROAD_WIDTH_M:.1f} m")
    print()
    print("LOCAL-FIRST SEARCH")
    print("-" * 78)
    print("Radii:", ", ".join(f"{x}m" for x in SEARCH_RADII_M))
    print(f"Minimum tree road:   {MIN_TREE_ROAD_WIDTH_M:.1f} m")
    print()

    route_results = []

    for route in routes:
        route_name = route["route"]

        print("-" * 78)
        print(f"{route_name}")
        print("-" * 78)

        impact = impact_for_route(
            route_name,
            impacts,
        )

        if not impact:
            print(
                "WARNING: No matching impact record found. "
                "Using route geometry only."
            )

        result = find_mitigation_for_route(
            route=route,
            impact=impact,
            district_dir=district_dir,
            ndvi_path=ndvi_path,
            ndwi_path=ndwi_path,
            water_path=water_path,
            canopy_path=canopy_path,
            buildings=buildings,
            heritage=heritage,
            roads=roads,
        )

        route_results.append(result)

        print()
        print(
            f"Selected search radius: "
            f"{result['search_radius_m']} m"
        )

        for zone in result["selected_zones"]:
            if zone["distance_m"] <= 0.5:
                distance_label = "adjacent to construction"
            else:
                distance_label = f"{zone['distance_m']:.1f} m away"

            print(
                f"  {zone['zone_id']}: "
                f"{zone['intervention']} | "
                f"{distance_label} | "
                f"{zone['capacity_m2']:,.1f} m²"
            )

    # --------------------------------------------------------
    # Output JSON
    # --------------------------------------------------------

    output_dir = (
        project_root
        / "outputs"
        / "mitigation"
        / args.district
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_json = (
        output_dir
        / f"mitigation_{args.construction}.json"
    )

    output_geojson = (
        output_dir
        / f"mitigation_{args.construction}.geojson"
    )

    output = {
        "project": {
            "district": args.district,
            "construction": args.construction,
        },

        "search_strategy": {
            "principle": (
                "Search for feasible mitigation opportunities "
                "as close as possible to the construction impact corridor."
            ),
            "search_radii_m": SEARCH_RADII_M,
            "minimum_zones": MIN_ZONES,
            "minimum_total_capacity_m2": MIN_TOTAL_CAPACITY_M2,
        },

        "intervention_rules": {
            "open_land": "tree_restoration",
            "suitable_road": "bush_restoration",
            "suitable_building": "green_roof",
            "minimum_bush_road_width_m": MIN_BUSH_ROAD_WIDTH_M,
            "average_roof_area_m2": AVERAGE_ROOF_AREA_M2,
            "average_roof_area_ft2": args.average_roof_area_ft2,
            "tree_restoration": (
                "Empty/degraded land; very wide roads may also be considered "
                "under the planning threshold."
            ),
            "tree_minimum_road_width_m": MIN_TREE_ROAD_WIDTH_M,
        },

        "assumptions": {
            "ndvi_open_threshold": NDVI_OPEN_THRESHOLD,
            "ndwi_water_threshold": NDWI_WATER_THRESHOLD,
            "existing_canopy_height_threshold_m": (
                CANOPY_HEIGHT_THRESHOLD_M
            ),
            "building_exclusion_buffer_m": (
                BUILDING_EXCLUSION_BUFFER_M
            ),
            "heritage_exclusion_buffer_m": (
                HERITAGE_EXCLUSION_BUFFER_M
            ),
            "minimum_open_zone_area_m2": (
                MIN_OPEN_ZONE_AREA_M2
            ),
            "roof_area_note": (
                "Green-roof capacity uses a configurable regional "
                "average when detailed roof-area data is unavailable."
            ),
            "thermal_note": (
                "Mitigation capacity is a planning-level spatial "
                "opportunity estimate and is not itself a claim of "
                "exact thermal or ecological equivalence."
            ),
        },

        "routes": route_results,
    }

    write_json(
        output_json,
        output,
    )

    # GeoJSON must not contain shapely objects / internal fields.
    geojson = make_feature_collection(
    route_results,
    source_crs=target_crs,
    output_crs="EPSG:4326",
)

    with open(
        output_geojson,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            geojson,
            f,
            indent=2,
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print("MITIGATION ENGINE COMPLETE")
    print("=" * 78)
    print(f"JSON:     {output_json}")
    print(f"GeoJSON:  {output_geojson}")
    print("=" * 78)


if __name__ == "__main__":
    main()