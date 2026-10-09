# backend/scripts/impact_analyzer.py

from pathlib import Path
import argparse
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import shape
from pyproj import Transformer


# ============================================================
# PROJECT PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

PROCESSED = ROOT / "processed"
ROUTES_DIR = ROOT / "outputs" / "routes"
OUTPUT_DIR = ROOT / "outputs" / "impacts"


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_NDVI_GREEN_THRESHOLD = 0.30
DEFAULT_NDWI_WATER_THRESHOLD = 0.20
DEFAULT_HIGH_SLOPE_THRESHOLD = 15.0

# Planning assumption only.
# NOT an actual tree-density measurement.
DEFAULT_CANOPY_AREA_PER_TREE = 25.0


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description="Tshaai environmental impact analysis"
    )

    parser.add_argument(
        "--district",
        required=True
    )

    parser.add_argument(
        "--construction",
        default="road",
        choices=["road", "bridge", "flyover"]
    )

    parser.add_argument(
        "--width",
        type=float,
        required=True,
        help="Total project width in meters"
    )

    parser.add_argument(
        "--ndvi-threshold",
        type=float,
        default=DEFAULT_NDVI_GREEN_THRESHOLD
    )

    parser.add_argument(
        "--ndwi-water-threshold",
        type=float,
        default=DEFAULT_NDWI_WATER_THRESHOLD,
        help="NDWI value above which a pixel is treated as water"
    )

    parser.add_argument(
        "--high-slope-threshold",
        type=float,
        default=DEFAULT_HIGH_SLOPE_THRESHOLD
    )

    parser.add_argument(
        "--canopy-area-per-tree",
        type=float,
        default=DEFAULT_CANOPY_AREA_PER_TREE
    )

    parser.add_argument(
        "--cost-raster",
        default=None,
        help="Optional explicit environmental cost raster"
    )

    return parser.parse_args()


# ============================================================
# PATH HELPERS
# ============================================================

def district_dir(district):
    return PROCESSED / district


def raster_path(district, name):
    return district_dir(district) / f"{name}.tif"


def vector_path(district, name):
    return district_dir(district) / f"{name}.gpkg"


# ============================================================
# ROUTES
# ============================================================

def load_routes(district, construction):

    path = (
        ROUTES_DIR
        / district
        / f"routes_{construction}.geojson"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Route file not found:\n{path}"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    routes = {}

    for feature in data.get("features", []):

        geometry = feature.get("geometry")

        if not geometry:
            continue

        geom = shape(geometry)

        if geom.is_empty:
            continue

        props = feature.get("properties", {})

        route_name = (
            props.get("route")
            or props.get("name")
            or props.get("id")
        )

        if route_name is None:
            continue

        routes[str(route_name)] = geom

    if not routes:
        raise ValueError(
            "No valid routes found in route GeoJSON."
        )

    return routes


# ============================================================
# RASTER LOADING
# ============================================================

def open_raster(district, name):

    path = raster_path(district, name)

    if not path.exists():
        raise FileNotFoundError(
            f"Required raster not found:\n{path}"
        )

    return rasterio.open(path)


# ============================================================
# REPROJECT GEOMETRY
# ============================================================

def reproject_geometry(
    geometry,
    source_crs,
    target_crs
):

    return gpd.GeoSeries(
        [geometry],
        crs=source_crs
    ).to_crs(target_crs).iloc[0]


# ============================================================
# IMPACT CORRIDOR
# ============================================================

def create_corridor(
    route,
    width,
    target_crs
):

    if width <= 0:
        raise ValueError(
            "Project width must be greater than zero."
        )

    route_projected = reproject_geometry(
        route,
        "EPSG:4326",
        target_crs
    )

    corridor = route_projected.buffer(
        width / 2.0
    )

    return route_projected, corridor


# ============================================================
# MASKED RASTER
# ============================================================

def read_masked(
    raster,
    geometry
):

    try:

        data, transform = mask(
            raster,
            [geometry],
            crop=True,
            filled=False
        )

    except ValueError:

        return None, None

    return data[0], transform


def valid_values(data):

    if data is None:
        return np.array([])

    return np.asarray(
        data.compressed(),
        dtype=np.float64
    )


# ============================================================
# GREEN SPACE
# ============================================================

def calculate_green_space(
    ndvi,
    corridor,
    threshold
):

    data, transform = read_masked(
        ndvi,
        corridor
    )

    values = valid_values(data)

    corridor_area = corridor.area

    if len(values) == 0:

        return {
            "green_area_m2": 0.0,
            "green_percentage_of_corridor": 0.0,
            "green_percentage_of_valid_raster": 0.0,
            "valid_observed_area_m2": 0.0
        }

    pixel_area = abs(
        transform.a * transform.e
    )

    green_pixels = np.sum(
        values >= threshold
    )

    green_area = (
        green_pixels * pixel_area
    )

    valid_area = (
        len(values) * pixel_area
    )

    return {

        "green_area_m2": float(
            green_area
        ),

        "green_percentage_of_corridor": float(
            green_area /
            corridor_area *
            100
            if corridor_area > 0
            else 0
        ),

        "green_percentage_of_valid_raster": float(
            green_area /
            valid_area *
            100
            if valid_area > 0
            else 0
        ),

        "valid_observed_area_m2": float(
            valid_area
        )
    }


# ============================================================
# CANOPY
# ============================================================

def calculate_canopy(
    canopy,
    corridor
):

    data, transform = read_masked(
        canopy,
        corridor
    )

    values = valid_values(data)

    if len(values) == 0:

        return {
            "canopy_area_m2": 0.0,
            "canopy_percentage_of_corridor": 0.0,
            "canopy_mean_value": 0.0
        }

    pixel_area = abs(
        transform.a * transform.e
    )

    canopy_pixels = np.sum(
        values > 0
    )

    canopy_area = (
        canopy_pixels * pixel_area
    )

    return {

        "canopy_area_m2": float(
            canopy_area
        ),

        "canopy_percentage_of_corridor": float(
            canopy_area /
            corridor.area *
            100
            if corridor.area > 0
            else 0
        ),

        "canopy_mean_value": float(
            np.mean(values)
        )
    }


# ============================================================
# WATER
#
# Water is detected from:
#
#   1. Explicit water raster
#   2. NDWI threshold
#
# The union is used so that either dataset can identify water.
# ============================================================

def calculate_water(
    water,
    ndwi,
    corridor,
    ndwi_threshold
):

    water_data, transform = read_masked(
        water,
        corridor
    )

    ndwi_data, _ = read_masked(
        ndwi,
        corridor
    )

    water_values = valid_values(
        water_data
    )

    ndwi_values = valid_values(
        ndwi_data
    )

    if water_data is None:

        return {
            "water_area_m2": 0.0,
            "water_percentage_of_corridor": 0.0,
            "water_mask_area_m2": 0.0,
            "ndwi_water_area_m2": 0.0,
            "combined_water_area_m2": 0.0
        }

    pixel_area = abs(
        transform.a * transform.e
    )

    # Both rasters are aligned by preprocessing.
    #
    # Use the full arrays here rather than independently
    # compressed arrays because we need pixel-wise OR.

    water_arr = np.ma.filled(
        water_data,
        0
    ).astype(float)

    ndwi_arr = np.ma.filled(
        ndwi_data,
        np.nan
    ).astype(float)

    explicit_water = (
        water_arr > 0
    )

    ndwi_water = (
        np.isfinite(ndwi_arr)
        &
        (ndwi_arr >= ndwi_threshold)
    )

    combined_water = (
        explicit_water
        |
        ndwi_water
    )

    water_pixels = np.sum(
        combined_water
    )

    explicit_pixels = np.sum(
        explicit_water
    )

    ndwi_pixels = np.sum(
        ndwi_water
    )

    combined_area = (
        water_pixels * pixel_area
    )

    explicit_area = (
        explicit_pixels * pixel_area
    )

    ndwi_area = (
        ndwi_pixels * pixel_area
    )

    return {

        "water_area_m2": float(
            combined_area
        ),

        "water_percentage_of_corridor": float(
            combined_area /
            corridor.area *
            100
            if corridor.area > 0
            else 0
        ),

        "water_mask_area_m2": float(
            explicit_area
        ),

        "ndwi_water_area_m2": float(
            ndwi_area
        ),

        "combined_water_area_m2": float(
            combined_area
        ),

        "ndwi_threshold": float(
            ndwi_threshold
        )
    }


# ============================================================
# WATER CROSSINGS
# ============================================================

def calculate_water_crossings(
    route,
    water,
    ndwi,
    ndwi_threshold
):

    resolution = abs(
        water.transform.a
    )

    route_length = route.length

    if route_length <= 0:
        return 0

    samples = max(
        int(route_length / resolution),
        2
    )

    distances = np.linspace(
        0,
        route_length,
        samples
    )

    points = [
        route.interpolate(d)
        for d in distances
    ]

    coords = [
        (p.x, p.y)
        for p in points
    ]

    water_values = np.array([
        float(v[0])
        for v in water.sample(coords)
    ])

    ndwi_values = np.array([
        float(v[0])
        for v in ndwi.sample(coords)
    ])

    water_signal = (
        water_values > 0
    )

    ndwi_signal = (
        np.isfinite(ndwi_values)
        &
        (ndwi_values >= ndwi_threshold)
    )

    combined = (
        water_signal
        |
        ndwi_signal
    )

    if not np.any(combined):
        return 0

    transitions = np.sum(
        combined[1:] != combined[:-1]
    )

    crossings = int(
        np.ceil(transitions / 2)
    )

    if combined[0]:
        crossings += 1

    return crossings


# ============================================================
# SLOPE
# ============================================================

def calculate_slope(
    slope,
    corridor,
    threshold
):

    data, _ = read_masked(
        slope,
        corridor
    )

    values = valid_values(data)

    if len(values) == 0:

        return {
            "mean_slope_deg": 0.0,
            "max_slope_deg": 0.0,
            "high_slope_percentage": 0.0
        }

    high_slope = np.sum(
        values >= threshold
    )

    return {

        "mean_slope_deg": float(
            np.mean(values)
        ),

        "max_slope_deg": float(
            np.max(values)
        ),

        "high_slope_percentage": float(
            high_slope /
            len(values) *
            100
        )
    }


# ============================================================
# VECTOR INTERSECTION
# ============================================================

def count_intersections(
    path,
    corridor,
    target_crs
):

    if not path.exists():

        return {
            "available": False,
            "count": None
        }

    gdf = gpd.read_file(path)

    if gdf.empty:

        return {
            "available": True,
            "count": 0
        }

    if gdf.crs is None:

        raise ValueError(
            f"Vector has no CRS:\n{path}"
        )

    gdf = gdf.to_crs(
        target_crs
    )

    count = int(
        gdf.intersects(corridor).sum()
    )

    return {
        "available": True,
        "count": count
    }


# ============================================================
# ENVIRONMENTAL COST RASTER
# ============================================================

def discover_cost_raster(
    district,
    construction
):

    filename = (
        f"soft_cost_{construction}.tif"
    )

    # First: processed district
    candidates = [

        PROCESSED
        / district
        / filename,

        ROOT
        / "outputs"
        / "cost_surface"
        / district
        / filename,

        ROOT
        / "outputs"
        / "cost_surfaces"
        / district
        / filename,

        ROOT
        / "outputs"
        / district
        / filename
    ]

    for path in candidates:

        if path.exists():
            return path

    # Last resort: search project tree.
    matches = list(
        ROOT.rglob(filename)
    )

    if matches:

        return matches[0]

    return None


def calculate_environmental_cost(
    cost_raster,
    route
):

    resolution = abs(
        cost_raster.transform.a
    )

    length = route.length

    if length <= 0:

        return {
            "environmental_cost_index": 0.0,
            "mean_environmental_cost": 0.0
        }

    samples = max(
        int(length / resolution),
        2
    )

    distances = np.linspace(
        0,
        length,
        samples
    )

    points = [
        route.interpolate(d)
        for d in distances
    ]

    coords = [
        (p.x, p.y)
        for p in points
    ]

    values = np.array([
        float(v[0])
        for v in cost_raster.sample(coords)
    ])

    values = values[
        np.isfinite(values)
    ]

    if len(values) == 0:

        return {
            "environmental_cost_index": None,
            "mean_environmental_cost": None
        }

    return {

        "environmental_cost_index": float(
            np.sum(values)
        ),

        "mean_environmental_cost": float(
            np.mean(values)
        )
    }


# ============================================================
# TREE-EQUIVALENT ESTIMATE
# ============================================================

def calculate_tree_equivalent(
    canopy_area,
    canopy_area_per_tree
):

    if canopy_area_per_tree <= 0:
        return None

    return (
        canopy_area /
        canopy_area_per_tree
    )


# ============================================================
# SINGLE ROUTE
# ============================================================

def analyze_route(
    route_name,
    route,
    district,
    construction,
    width,
    ndvi_threshold,
    ndwi_threshold,
    high_slope_threshold,
    canopy_area_per_tree,
    cost_raster
):

    print()
    print("=" * 70)
    print(f"ANALYZING {route_name}")
    print("=" * 70)

    # --------------------------------------------------------
    # Reference CRS
    # --------------------------------------------------------

    ndvi = open_raster(
        district,
        "ndvi"
    )

    target_crs = ndvi.crs

    # --------------------------------------------------------
    # Route + corridor
    # --------------------------------------------------------

    route_projected, corridor = (
        create_corridor(
            route,
            width,
            target_crs
        )
    )

    route_length = route_projected.length

    corridor_area = corridor.area

    # --------------------------------------------------------
    # Rasters
    # --------------------------------------------------------

    ndwi = open_raster(
        district,
        "ndwi"
    )

    water = open_raster(
        district,
        "water"
    )

    canopy = open_raster(
        district,
        "canopy"
    )

    slope = open_raster(
        district,
        "slope"
    )

    # --------------------------------------------------------
    # Green space
    # --------------------------------------------------------

    green = calculate_green_space(
        ndvi,
        corridor,
        ndvi_threshold
    )

    # --------------------------------------------------------
    # Canopy
    # --------------------------------------------------------

    canopy_result = calculate_canopy(
        canopy,
        corridor
    )

    canopy_area = canopy_result[
        "canopy_area_m2"
    ]

    tree_equivalent = (
        calculate_tree_equivalent(
            canopy_area,
            canopy_area_per_tree
        )
    )

    # --------------------------------------------------------
    # Water
    # --------------------------------------------------------

    water_result = calculate_water(
        water,
        ndwi,
        corridor,
        ndwi_threshold
    )

    water_crossings = (
        calculate_water_crossings(
            route_projected,
            water,
            ndwi,
            ndwi_threshold
        )
    )

    water_result[
        "estimated_crossings"
    ] = water_crossings

    # --------------------------------------------------------
    # Slope
    # --------------------------------------------------------

    slope_result = calculate_slope(
        slope,
        corridor,
        high_slope_threshold
    )

    # --------------------------------------------------------
    # Vector layers
    # --------------------------------------------------------

    buildings = count_intersections(
        vector_path(
            district,
            "buildings"
        ),
        corridor,
        target_crs
    )

    heritage = count_intersections(
        vector_path(
            district,
            "heritage"
        ),
        corridor,
        target_crs
    )

    # --------------------------------------------------------
    # Environmental cost
    # --------------------------------------------------------

    if cost_raster is not None:

        environmental_cost = (
            calculate_environmental_cost(
                cost_raster,
                route_projected
            )
        )

    else:

        environmental_cost = {

            "environmental_cost_index":
                None,

            "mean_environmental_cost":
                None
        }

    # --------------------------------------------------------
    # Result
    # --------------------------------------------------------

    result = {

        "route": route_name,

        "construction": construction,

        "project_width_m": float(
            width
        ),

        "route_length_km": float(
            route_length / 1000
        ),

        "impact_corridor_area_m2": float(
            corridor_area
        ),

        "impact_corridor_area_ha": float(
            corridor_area / 10000
        ),

        "green_space": green,

        "canopy": {

            **canopy_result,

            "estimated_tree_equivalent": (
                float(tree_equivalent)
                if tree_equivalent is not None
                else None
            ),

            "tree_equivalent_is_planning_estimate":
                True
        },

        "water": water_result,

        "slope": slope_result,

        "buildings": buildings,

        "heritage": heritage,

        "environmental_cost":
            environmental_cost,

        "assumptions": {

            "ndvi_green_threshold":
                float(ndvi_threshold),

            "ndwi_water_threshold":
                float(ndwi_threshold),

            "high_slope_threshold_deg":
                float(high_slope_threshold),

            "canopy_area_per_tree_m2":
                float(canopy_area_per_tree),

            "corridor_width_m":
                float(width),

            "corridor_definition":
                "Project width is the total corridor width; "
                "buffer radius is width / 2.",

            "tree_equivalent_definition":
                "Canopy area divided by a planning-level "
                "canopy-area-per-tree assumption. "
                "This is not an individual tree count.",

            "water_definition":
                "Combined water signal from explicit water "
                "mask OR NDWI above the configured threshold."
        }
    }

    # --------------------------------------------------------
    # Console output
    # --------------------------------------------------------

    print(
        f"Length: "
        f"{result['route_length_km']:.3f} km"
    )

    print(
        f"Impact corridor: "
        f"{result['impact_corridor_area_ha']:.3f} ha"
    )

    print(
        f"Green space: "
        f"{green['green_area_m2']:.1f} m² "
        f"({green['green_percentage_of_corridor']:.1f}% "
        f"of corridor)"
    )

    print(
        f"Canopy: "
        f"{canopy_area:.1f} m² "
        f"({canopy_result['canopy_percentage_of_corridor']:.1f}%)"
    )

    print(
        f"Estimated tree-equivalent canopy impact: "
        f"{tree_equivalent:.1f}"
        if tree_equivalent is not None
        else "Estimated tree-equivalent canopy impact: N/A"
    )

    print(
        f"Water area: "
        f"{water_result['combined_water_area_m2']:.1f} m²"
    )

    print(
        f"Water crossings: "
        f"{water_crossings}"
    )

    print(
        f"Buildings affected: "
        f"{buildings['count']}"
    )

    print(
        f"Heritage conflicts: "
        f"{heritage['count']}"
    )

    print(
        f"Mean slope: "
        f"{slope_result['mean_slope_deg']:.2f}°"
    )

    print(
        f"High-slope area: "
        f"{slope_result['high_slope_percentage']:.2f}%"
    )

    if environmental_cost[
        "environmental_cost_index"
    ] is not None:

        print(
            f"Environmental cost index: "
            f"{environmental_cost['environmental_cost_index']:.2f}"
        )

    else:

        print(
            "Environmental cost index: NOT FOUND"
        )

    return result


# ============================================================
# COMPARISON
# ============================================================

def percentage_change(
    value,
    baseline
):

    if value is None or baseline is None:
        return None

    if baseline == 0:

        if value == 0:
            return 0.0

        return None

    return (
        (value - baseline)
        / baseline
        * 100
    )


def build_comparison(results):

    names = list(results.keys())

    if not names:
        return {}

    baseline_name = names[0]

    baseline = results[
        baseline_name
    ]

    def get(
        result,
        *keys
    ):

        value = result

        for key in keys:
            value = value.get(key)

            if value is None:
                return None

        return value

    comparison = {}

    for name, result in results.items():

        comparison[name] = {

            "baseline":
                baseline_name,

            "length_change_percent":
                percentage_change(
                    get(
                        result,
                        "route_length_km"
                    ),
                    get(
                        baseline,
                        "route_length_km"
                    )
                ),

            "green_space_change_percent":
                percentage_change(
                    get(
                        result,
                        "green_space",
                        "green_area_m2"
                    ),
                    get(
                        baseline,
                        "green_space",
                        "green_area_m2"
                    )
                ),

            "canopy_change_percent":
                percentage_change(
                    get(
                        result,
                        "canopy",
                        "canopy_area_m2"
                    ),
                    get(
                        baseline,
                        "canopy",
                        "canopy_area_m2"
                    )
                ),

            "water_area_change_percent":
                percentage_change(
                    get(
                        result,
                        "water",
                        "combined_water_area_m2"
                    ),
                    get(
                        baseline,
                        "water",
                        "combined_water_area_m2"
                    )
                ),

            "environmental_cost_change_percent":
                percentage_change(
                    get(
                        result,
                        "environmental_cost",
                        "environmental_cost_index"
                    ),
                    get(
                        baseline,
                        "environmental_cost",
                        "environmental_cost_index"
                    )
                ),

            "building_conflict_difference":
                (
                    get(
                        result,
                        "buildings",
                        "count"
                    )
                    -
                    get(
                        baseline,
                        "buildings",
                        "count"
                    )
                    if
                    get(
                        result,
                        "buildings",
                        "count"
                    ) is not None
                    and
                    get(
                        baseline,
                        "buildings",
                        "count"
                    ) is not None
                    else None
                ),

            "heritage_conflict_difference":
                (
                    get(
                        result,
                        "heritage",
                        "count"
                    )
                    -
                    get(
                        baseline,
                        "heritage",
                        "count"
                    )
                    if
                    get(
                        result,
                        "heritage",
                        "count"
                    ) is not None
                    and
                    get(
                        baseline,
                        "heritage",
                        "count"
                    ) is not None
                    else None
                )
        }

    return comparison


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()

    district = args.district.lower()

    print()
    print("=" * 70)
    print("TSHAAY — ENVIRONMENTAL IMPACT ENGINE")
    print("=" * 70)

    print(f"District:              {district}")
    print(f"Construction:          {args.construction}")
    print(f"Project width:         {args.width} m")
    print(f"NDVI threshold:        {args.ndvi_threshold}")
    print(f"NDWI water threshold:  {args.ndwi_water_threshold}")
    print(f"High slope threshold:  {args.high_slope_threshold}°")

    # --------------------------------------------------------
    # Discover cost raster
    # --------------------------------------------------------

    if args.cost_raster:

        cost_path = Path(
            args.cost_raster
        )

        if not cost_path.exists():

            raise FileNotFoundError(
                f"Specified cost raster does not exist:\n"
                f"{cost_path}"
            )

    else:

        cost_path = discover_cost_raster(
            district,
            args.construction
        )

    if cost_path:

        print(
            f"Cost raster:          {cost_path}"
        )

        cost_raster = rasterio.open(
            cost_path
        )

    else:

        print(
            "Cost raster:          NOT FOUND"
        )

        cost_raster = None

    # --------------------------------------------------------
    # Load routes
    # --------------------------------------------------------

    routes = load_routes(
        district,
        args.construction
    )

    print(
        f"Routes found:          "
        f"{', '.join(routes.keys())}"
    )

    # --------------------------------------------------------
    # Analyze routes
    # --------------------------------------------------------

    results = {}

    for route_name, route in routes.items():

        results[route_name] = analyze_route(

            route_name=route_name,

            route=route,

            district=district,

            construction=args.construction,

            width=args.width,

            ndvi_threshold=args.ndvi_threshold,

            ndwi_threshold=args.ndwi_water_threshold,

            high_slope_threshold=
                args.high_slope_threshold,

            canopy_area_per_tree=
                args.canopy_area_per_tree,

            cost_raster=cost_raster
        )

    # --------------------------------------------------------
    # Comparison
    # --------------------------------------------------------

    comparison = build_comparison(
        results
    )

    # --------------------------------------------------------
    # Final output
    # --------------------------------------------------------

    output_dir = (
        OUTPUT_DIR
        / district
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        output_dir
        / f"impact_{args.construction}.json"
    )

    final_output = {

        "district":
            district,

        "construction":
            args.construction,

        "project_width_m":
            float(args.width),

        "routes":
            results,

        "route_comparison":
            comparison,

        "assumptions": {

            "ndvi_green_threshold":
                float(args.ndvi_threshold),

            "ndwi_water_threshold":
                float(args.ndwi_water_threshold),

            "high_slope_threshold_deg":
                float(args.high_slope_threshold),

            "canopy_area_per_tree_m2":
                float(args.canopy_area_per_tree),

            "width_definition":
                "Total project width. "
                "Impact corridor uses width / 2 "
                "as buffer radius.",

            "water_definition":
                "Water impact uses the union of "
                "explicit water-mask pixels and "
                "pixels whose NDWI exceeds the "
                "configured threshold.",

            "tree_equivalent_warning":
                "Estimated tree-equivalent canopy "
                "impact is a planning-level estimate "
                "and must not be interpreted as an "
                "individual tree count.",

            "comparison_baseline":
                "The first route in the generated "
                "route file is used as the baseline "
                "for percentage changes."
        }
    }

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            final_output,
            f,
            indent=2
        )

    # --------------------------------------------------------
    # Comparison console output
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("ROUTE COMPARISON")
    print("=" * 70)

    baseline_name = list(
        results.keys()
    )[0]

    baseline = results[
        baseline_name
    ]

    for name, result in results.items():

        print()
        print(name)

        length_change = percentage_change(
            result["route_length_km"],
            baseline["route_length_km"]
        )

        green_change = percentage_change(
            result["green_space"]["green_area_m2"],
            baseline["green_space"]["green_area_m2"]
        )

        canopy_change = percentage_change(
            result["canopy"]["canopy_area_m2"],
            baseline["canopy"]["canopy_area_m2"]
        )

        if name == baseline_name:

            print("  Baseline route")

        else:

            print(
                f"  Length change:  "
                f"{length_change:+.2f}%"
            )

            print(
                f"  Green change:   "
                f"{green_change:+.2f}%"
            )

            print(
                f"  Canopy change:  "
                f"{canopy_change:+.2f}%"
            )

    print()
    print("=" * 70)
    print("IMPACT ANALYSIS COMPLETE")
    print("=" * 70)

    print(
        f"Output:\n{output_file}"
    )


if __name__ == "__main__":
    main()