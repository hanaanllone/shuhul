
import argparse
import json
import math
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
from skimage.graph import route_through_array


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

COST_ROOT = PROJECT_ROOT / "outputs" / "cost_surfaces"


# ============================================================
# HELPERS
# ============================================================

def load_config(district, construction):
    config_path = (
        COST_ROOT
        / district
        / f"config_{construction}.json"
    )

    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration not found:\n{config_path}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_raster(path):
    src = rasterio.open(path)

    data = src.read(1).astype(np.float32)

    return src, data


def latlon_to_pixel(src, lat, lon):
    """
    Convert WGS84 latitude/longitude to raster row/column.
    """

    transformer = Transformer.from_crs(
        "EPSG:4326",
        src.crs,
        always_xy=True
    )

    x, y = transformer.transform(lon, lat)

    row, col = src.index(x, y)

    return row, col


def pixel_to_latlon(src, row, col):
    """
    Convert raster row/column to WGS84 latitude/longitude.
    """

    x, y = src.xy(row, col)

    transformer = Transformer.from_crs(
        src.crs,
        "EPSG:4326",
        always_xy=True
    )

    lon, lat = transformer.transform(x, y)

    return lat, lon


def validate_point(
    row,
    col,
    shape,
    hard_mask,
    cost_data,
    point_name
):
    height, width = shape

    if not (0 <= row < height and 0 <= col < width):
        raise ValueError(
            f"{point_name} is outside the raster."
        )

    if hard_mask[row, col] == 1:
        raise ValueError(
            f"{point_name} lies inside a hard constraint."
        )

    if hard_mask[row, col] == 255:
        raise ValueError(
            f"{point_name} lies outside the valid planning area."
        )

    if not np.isfinite(cost_data[row, col]):
        raise ValueError(
            f"{point_name} lies on an invalid cost pixel."
        )


def snap_to_nearest_valid_cell(
    row,
    col,
    hard_mask,
    cost_data,
    max_radius_pixels=100,
):
    """
    Snap a point that falls on raster NODATA to the nearest valid
    planning cell.

    This is only for NODATA/invalid raster cells. Hard constraints
    remain forbidden and are never silently bypassed.

    At the project's 10 m target grid, 100 pixels is approximately
    a 1 km search radius.
    """

    height, width = cost_data.shape

    best = None
    best_distance_sq = None

    r0 = max(0, row - max_radius_pixels)
    r1 = min(height, row + max_radius_pixels + 1)
    c0 = max(0, col - max_radius_pixels)
    c1 = min(width, col + max_radius_pixels + 1)

    for r in range(r0, r1):
        for c in range(c0, c1):
            if hard_mask[r, c] != 0:
                continue

            if not np.isfinite(cost_data[r, c]):
                continue

            dr = r - row
            dc = c - col
            distance_sq = dr * dr + dc * dc

            if best_distance_sq is None or distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                best = (r, c)

    if best is None:
        return None

    return best


# ============================================================
# DISTANCE / PATH UTILITIES
# ============================================================

def path_distance(path, resolution):
    """
    Calculate physical path length in metres.

    Supports 8-connected movement.
    """

    total = 0.0

    for (r1, c1), (r2, c2) in zip(path[:-1], path[1:]):

        dr = abs(r2 - r1)
        dc = abs(c2 - c1)

        if dr == 1 and dc == 1:
            total += resolution * math.sqrt(2)

        elif dr + dc == 1:
            total += resolution

        else:
            # Should never happen with 8-connected routing,
            # but protects against unexpected paths.
            total += resolution * math.sqrt(
                dr * dr + dc * dc
            )

    return total


def route_cost(path, cost_surface):
    """
    Sum environmental cost along a route.
    """

    values = np.array(
        [cost_surface[r, c] for r, c in path],
        dtype=np.float64
    )

    return float(np.sum(values))


def path_to_geojson(path, src):
    """
    Convert raster path into a GeoJSON LineString.
    """

    coordinates = []

    for row, col in path:
        lat, lon = pixel_to_latlon(
            src,
            row,
            col
        )

        coordinates.append([
            lon,
            lat
        ])

    return {
        "type": "LineString",
        "coordinates": coordinates
    }


# ============================================================
# ROUTING
# ============================================================

def calculate_route(
    routing_surface,
    hard_mask,
    start,
    end
):
    """
    Run raster-based least-cost routing.

    hard_mask:
        0   = allowed
        1   = forbidden
        255 = NoData

    Forbidden/NoData cells receive infinite cost.
    """

    routing_surface = routing_surface.copy()

    forbidden = (
        (hard_mask == 1) |
        (hard_mask == 255)
    )

    routing_surface[forbidden] = np.inf

    path, solver_cost = route_through_array(
        routing_surface,
        start,
        end,
        fully_connected=True,
        geometric=True
    )

    return path, float(solver_cost)


# ============================================================
# ROUTE SURFACES
# ============================================================

def build_route_surfaces(
    environmental_cost,
    hard_mask,
    shortest_priority,
    construction_priority
):
    """
    Build the three objective surfaces.

    Route A:
        Pure distance.

    Route B:
        Balanced distance + environmental cost.

    Route C:
        Environmental impact with a small distance component.

    construction_priority is currently retained for future
    construction-cost modeling. The construction-specific
    modifiers have already influenced the environmental surface.
    """

    valid = (
        (hard_mask != 255) &
        np.isfinite(environmental_cost)
    )

    if not np.any(valid):
        raise ValueError(
            "No valid planning pixels found."
        )

    # --------------------------------------------------------
    # Normalize environmental cost to 0-1
    # --------------------------------------------------------

    env = environmental_cost.copy()

    valid_values = env[valid]

    env_min = np.percentile(
        valid_values,
        1
    )

    env_max = np.percentile(
        valid_values,
        99
    )

    if env_max <= env_min:
        env_norm = np.zeros_like(env)
    else:
        env_norm = (
            (env - env_min) /
            (env_max - env_min)
        )

    env_norm = np.clip(
        env_norm,
        0,
        1
    )

    # --------------------------------------------------------
    # Route A
    # --------------------------------------------------------

    shortest_surface = np.ones_like(
        env_norm,
        dtype=np.float32
    )

    # --------------------------------------------------------
    # Route B
    # --------------------------------------------------------

    # User's shortest priority determines how much distance
    # matters. Environmental importance is its complement.

    distance_weight = float(
        np.clip(shortest_priority, 0, 1)
    )

    environment_weight = 1.0 - distance_weight

    balanced_surface = (
        distance_weight * 1.0 +
        environment_weight * env_norm
    ).astype(np.float32)

    # --------------------------------------------------------
    # Route C
    # --------------------------------------------------------

    # Primarily environmental, but retain some distance so that
    # the route does not become unnecessarily extreme.

    environmental_surface = (
        0.85 * env_norm +
        0.15 * 1.0
    ).astype(np.float32)

    # --------------------------------------------------------
    # Apply hard constraints
    # --------------------------------------------------------

    for surface in (
        shortest_surface,
        balanced_surface,
        environmental_surface
    ):
        surface[hard_mask == 1] = np.inf
        surface[hard_mask == 255] = np.inf

    return (
        shortest_surface,
        balanced_surface,
        environmental_surface
    )


# ============================================================
# OUTPUT
# ============================================================

def save_geojson(
    district,
    construction,
    routes,
    output_dir
):
    features = []

    for route_name, route_data in routes.items():

        geometry = route_data["geometry"]

        properties = {
            "route": route_name,
            "distance_km": round(
                route_data["distance_km"],
                3
            ),
            "environmental_cost": round(
                route_data["environmental_cost"],
                3
            ),
            "solver_cost": round(
                route_data["solver_cost"],
                3
            )
        }

        features.append({
            "type": "Feature",
            "properties": properties,
            "geometry": geometry
        })

    collection = {
        "type": "FeatureCollection",
        "features": features
    }

    output_path = (
        output_dir /
        f"routes_{construction}.geojson"
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            collection,
            f,
            indent=2
        )

    return output_path



# ============================================================
# PYTHON API
# ============================================================

def plan_routes(
    district,
    construction="road",
    start=None,
    end=None,
    cost_result=None,
    start_lat=None,
    start_lng=None,
    end_lat=None,
    end_lng=None,
    output_dir=None,
):
    """
    Programmatic routing API used by the Flask backend.

    This reuses the exact same routing helpers used by the CLI:
      - load_config()
      - load_raster()
      - latlon_to_pixel()
      - validate_point()
      - build_route_surfaces()
      - calculate_route()
      - path_distance()
      - route_cost()
      - path_to_geojson()

    Returns route data for Routes A/B/C and writes the same JSON and
    GeoJSON outputs as the CLI.
    """

    # --------------------------------------------------------
    # BACKEND INPUT NORMALIZATION
    # --------------------------------------------------------
    #
    # Flask passes:
    #   start={"lat": ..., "lng": ...}
    #   end={"lat": ..., "lng": ...}
    #
    # Keep start_lat/start_lng/end_lat/end_lng as a backwards-
    # compatible option for direct Python/CLI-style callers.
    # --------------------------------------------------------

    if start is not None:
        if isinstance(start, dict):
            start_lat = start.get("lat", start.get("latitude"))
            start_lng = start.get(
                "lng",
                start.get("lon", start.get("longitude"))
            )
        elif isinstance(start, (list, tuple)) and len(start) >= 2:
            start_lat = start[0]
            start_lng = start[1]
        else:
            raise ValueError(
                "start must be an object with lat/lng "
                "or a [lat, lng] pair."
            )

    if end is not None:
        if isinstance(end, dict):
            end_lat = end.get("lat", end.get("latitude"))
            end_lng = end.get(
                "lng",
                end.get("lon", end.get("longitude"))
            )
        elif isinstance(end, (list, tuple)) and len(end) >= 2:
            end_lat = end[0]
            end_lng = end[1]
        else:
            raise ValueError(
                "end must be an object with lat/lng "
                "or a [lat, lng] pair."
            )

    if start_lat is None or start_lng is None:
        raise ValueError(
            "start must contain lat and lng."
        )

    if end_lat is None or end_lng is None:
        raise ValueError(
            "end must contain lat and lng."
        )

    district = str(district)
    construction = str(construction)

    if construction not in {"road", "bridge", "flyover"}:
        raise ValueError(
            "construction must be one of: road, bridge, flyover"
        )

    # --------------------------------------------------------
    # COST-SURFACE OUTPUTS
    # --------------------------------------------------------

    district_dir = COST_ROOT / district

    cost_path = (
        district_dir /
        f"soft_cost_{construction}.tif"
    )

    hard_path = (
        district_dir /
        f"hard_constraints_{construction}.tif"
    )

    # If the cost-surface stage just ran, prefer the exact paths it
    # returned. This keeps routing tied to the current project settings.
    if isinstance(cost_result, dict):
        returned_soft = cost_result.get("soft_output")
        returned_hard = cost_result.get("hard_output")

        if returned_soft:
            cost_path = Path(returned_soft)

        if returned_hard:
            hard_path = Path(returned_hard)

    if not cost_path.exists():
        raise FileNotFoundError(
            f"Soft cost raster not found:\n{cost_path}"
        )

    if not hard_path.exists():
        raise FileNotFoundError(
            f"Hard constraint raster not found:\n{hard_path}"
        )

    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    # The cost-surface stage returns the settings it was built with.
    # Reading them from there, not from a shared file, keeps the
    # settings of one project out of the routes of another.
    if isinstance(cost_result, dict) and "soft_preferences" in cost_result:
        config = cost_result
    else:
        config = load_config(
            district,
            construction
        )

    soft = config["soft_preferences"]

    shortest_priority = float(
        soft.get("shortest_priority", 0.5)
    )

    construction_priority = float(
        soft.get("construction_priority", 0.5)
    )

    # --------------------------------------------------------
    # LOAD RASTERS
    # --------------------------------------------------------

    cost_src, environmental_cost = load_raster(
        cost_path
    )

    hard_src, hard_mask = load_raster(
        hard_path
    )

    try:
        if environmental_cost.shape != hard_mask.shape:
            raise ValueError(
                "Soft cost and hard constraint rasters "
                "have different dimensions."
            )

        # Also verify that both rasters describe the same grid.
        if (
            cost_src.crs != hard_src.crs
            or cost_src.transform != hard_src.transform
            or cost_src.width != hard_src.width
            or cost_src.height != hard_src.height
        ):
            raise ValueError(
                "Soft cost and hard constraint rasters "
                "are not aligned to the same grid."
            )

        # ----------------------------------------------------
        # POINTS
        # ----------------------------------------------------

        start = latlon_to_pixel(
            cost_src,
            float(start_lat),
            float(start_lng)
        )

        end = latlon_to_pixel(
            cost_src,
            float(end_lat),
            float(end_lng)
        )

        # ----------------------------------------------------
        # POINT VALIDATION / NODATA SNAPPING
        # ----------------------------------------------------
        # A user can click a visually valid location that happens to
        # land on a NODATA pixel in the planning raster. Do not reject
        # the project for a tiny raster gap; snap to the nearest valid
        # planning cell. Hard constraints are still rejected.

        def prepare_endpoint(point, name):
            row, col = point

            if not (
                0 <= row < environmental_cost.shape[0]
                and 0 <= col < environmental_cost.shape[1]
            ):
                raise ValueError(
                    f"{name} is outside the raster."
                )

            if hard_mask[row, col] == 1:
                raise ValueError(
                    f"{name} lies inside a hard constraint."
                )

            is_invalid = (
                hard_mask[row, col] == 255
                or not np.isfinite(environmental_cost[row, col])
            )

            if not is_invalid:
                return (row, col), False

            snapped = snap_to_nearest_valid_cell(
                row,
                col,
                hard_mask,
                environmental_cost,
                max_radius_pixels=100,
            )

            if snapped is None:
                raise ValueError(
                    f"{name} lies outside the valid planning area "
                    "and no valid planning cell was found within 1 km."
                )

            return snapped, True

        start, start_snapped = prepare_endpoint(
            start,
            "Start point"
        )

        end, end_snapped = prepare_endpoint(
            end,
            "End point"
        )

        # ----------------------------------------------------
        # ROUTE SURFACES
        # ----------------------------------------------------

        (
            shortest_surface,
            balanced_surface,
            environmental_surface
        ) = build_route_surfaces(
            environmental_cost,
            hard_mask,
            shortest_priority,
            construction_priority
        )

        # ----------------------------------------------------
        # ROUTE A
        # ----------------------------------------------------

        path_a, solver_a = calculate_route(
            shortest_surface,
            hard_mask,
            start,
            end
        )

        # ----------------------------------------------------
        # ROUTE B
        # ----------------------------------------------------

        path_b, solver_b = calculate_route(
            balanced_surface,
            hard_mask,
            start,
            end
        )

        # ----------------------------------------------------
        # ROUTE C
        # ----------------------------------------------------

        path_c, solver_c = calculate_route(
            environmental_surface,
            hard_mask,
            start,
            end
        )

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        resolution = float(
            abs(cost_src.transform.a)
        )

        paths = {
            "Route A — Shortest": (
                path_a,
                solver_a
            ),
            "Route B — Balanced": (
                path_b,
                solver_b
            ),
            "Route C — Lower Environmental Impact": (
                path_c,
                solver_c
            )
        }

        routes = {}

        for name, (path, solver_cost) in paths.items():

            distance = path_distance(
                path,
                resolution
            )

            environmental = route_cost(
                path,
                environmental_cost
            )

            routes[name] = {
                "distance_km": distance / 1000.0,
                "environmental_cost": environmental,
                "solver_cost": solver_cost,
                "geometry": path_to_geojson(
                    path,
                    cost_src
                )
            }

        # ----------------------------------------------------
        # OUTPUT
        # ----------------------------------------------------

        if output_dir is None:
            output_dir = (
                PROJECT_ROOT /
                "outputs" /
                "routes" /
                district
            )

        output_dir = Path(output_dir)

        output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        geojson_path = save_geojson(
            district,
            construction,
            routes,
            output_dir
        )

        results = {
            "district": district,
            "construction": construction,

            "start": {
                "lat": float(start_lat),
                "lng": float(start_lng),
                "lon": float(start_lng),
            },

            "end": {
                "lat": float(end_lat),
                "lng": float(end_lng),
                "lon": float(end_lng),
            },

            "endpointSnapping": {
                "startSnapped": bool(start_snapped),
                "endSnapped": bool(end_snapped),
                "reason": (
                    "Nearest valid planning cell used for an endpoint "
                    "that fell on raster NODATA."
                    if (start_snapped or end_snapped)
                    else None
                ),
            },

            "preferences": {
                "shortest_priority":
                    shortest_priority,
                "construction_priority":
                    construction_priority
            },

            "routes": {}
        }

        for name, data in routes.items():

            results["routes"][name] = {
                "distance_km":
                    round(data["distance_km"], 3),

                "environmental_cost":
                    round(
                        data["environmental_cost"],
                        3
                    ),

                "solver_cost":
                    round(
                        data["solver_cost"],
                        3
                    ),

                "geometry":
                    data["geometry"]
            }

        json_path = (
            output_dir /
            f"routes_{construction}.json"
        )

        with open(
            json_path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                results,
                f,
                indent=2
            )

        # ----------------------------------------------------
        # Backend-friendly aliases
        # ----------------------------------------------------

        # Keep the existing human-readable route names above,
        # while also exposing A/B/C directly for the API.
        results["route_a"] = results["routes"].get(
            "Route A — Shortest"
        )
        results["route_b"] = results["routes"].get(
            "Route B — Balanced"
        )
        results["route_c"] = results["routes"].get(
            "Route C — Lower Environmental Impact"
        )

        results["geojson"] = str(geojson_path)
        results["json"] = str(json_path)

        return results

    finally:
        cost_src.close()
        hard_src.close()



# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Shuhul A→B Route Planner"
    )

    parser.add_argument(
        "--district",
        required=True
    )

    parser.add_argument(
        "--construction",
        required=True,
        choices=[
            "road",
            "bridge",
            "flyover"
        ]
    )

    parser.add_argument(
        "--start-lat",
        required=True,
        type=float
    )

    parser.add_argument(
        "--start-lon",
        required=True,
        type=float
    )

    parser.add_argument(
        "--end-lat",
        required=True,
        type=float
    )

    parser.add_argument(
        "--end-lon",
        required=True,
        type=float
    )

    args = parser.parse_args()

    district = args.district
    construction = args.construction

    district_dir = (
        COST_ROOT /
        district
    )

    cost_path = (
        district_dir /
        f"soft_cost_{construction}.tif"
    )

    hard_path = (
        district_dir /
        f"hard_constraints_{construction}.tif"
    )

    if not cost_path.exists():
        raise FileNotFoundError(
            f"Soft cost raster not found:\n{cost_path}"
        )

    if not hard_path.exists():
        raise FileNotFoundError(
            f"Hard constraint raster not found:\n{hard_path}"
        )

    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    config = load_config(
        district,
        construction
    )

    soft = config["soft_preferences"]

    shortest_priority = float(
        soft["shortest_priority"]
    )

    construction_priority = float(
        soft["construction_priority"]
    )

    # --------------------------------------------------------
    # LOAD RASTERS
    # --------------------------------------------------------

    cost_src, environmental_cost = load_raster(
        cost_path
    )

    hard_src, hard_mask = load_raster(
        hard_path
    )

    if environmental_cost.shape != hard_mask.shape:
        raise ValueError(
            "Soft cost and hard constraint rasters "
            "have different dimensions."
        )

    # --------------------------------------------------------
    # POINTS
    # --------------------------------------------------------

    start = latlon_to_pixel(
        cost_src,
        args.start_lat,
        args.start_lon
    )

    end = latlon_to_pixel(
        cost_src,
        args.end_lat,
        args.end_lon
    )

    validate_point(
        *start,
        environmental_cost.shape,
        hard_mask,
        environmental_cost,
        "Start point"
    )

    validate_point(
        *end,
        environmental_cost.shape,
        hard_mask,
        environmental_cost,
        "End point"
    )

    # --------------------------------------------------------
    # ROUTE SURFACES
    # --------------------------------------------------------

    (
        shortest_surface,
        balanced_surface,
        environmental_surface
    ) = build_route_surfaces(
        environmental_cost,
        hard_mask,
        shortest_priority,
        construction_priority
    )

    # --------------------------------------------------------
    # ROUTE A
    # --------------------------------------------------------

    print("\nCalculating Route A — Shortest...")

    path_a, solver_a = calculate_route(
        shortest_surface,
        hard_mask,
        start,
        end
    )

    # --------------------------------------------------------
    # ROUTE B
    # --------------------------------------------------------

    print("Calculating Route B — Balanced...")

    path_b, solver_b = calculate_route(
        balanced_surface,
        hard_mask,
        start,
        end
    )

    # --------------------------------------------------------
    # ROUTE C
    # --------------------------------------------------------

    print(
        "Calculating Route C — "
        "Lower Environmental Impact..."
    )

    path_c, solver_c = calculate_route(
        environmental_surface,
        hard_mask,
        start,
        end
    )

    # --------------------------------------------------------
    # RESULTS
    # --------------------------------------------------------

    resolution = float(
        abs(cost_src.transform.a)
    )

    paths = {
        "Route A — Shortest": (
            path_a,
            solver_a
        ),
        "Route B — Balanced": (
            path_b,
            solver_b
        ),
        "Route C — Lower Environmental Impact": (
            path_c,
            solver_c
        )
    }

    routes = {}

    for name, (path, solver_cost) in paths.items():

        distance = path_distance(
            path,
            resolution
        )

        environmental = route_cost(
            path,
            environmental_cost
        )

        routes[name] = {
            "distance_km": distance / 1000.0,
            "environmental_cost": environmental,
            "solver_cost": solver_cost,
            "geometry": path_to_geojson(
                path,
                cost_src
            )
        }

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    output_dir = (
        PROJECT_ROOT /
        "outputs" /
        "routes" /
        district
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    geojson_path = save_geojson(
        district,
        construction,
        routes,
        output_dir
    )

    results = {
        "district": district,
        "construction": construction,

        "start": {
            "lat": args.start_lat,
            "lon": args.start_lon
        },

        "end": {
            "lat": args.end_lat,
            "lon": args.end_lon
        },

        "preferences": {
            "shortest_priority":
                shortest_priority,
            "construction_priority":
                construction_priority
        },

        "routes": {}
    }

    for name, data in routes.items():

        results["routes"][name] = {
            "distance_km":
                round(data["distance_km"], 3),

            "environmental_cost":
                round(
                    data["environmental_cost"],
                    3
                ),

            "solver_cost":
                round(
                    data["solver_cost"],
                    3
                )
        }

    json_path = (
        output_dir /
        f"routes_{construction}.json"
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            results,
            f,
            indent=2
        )

    # --------------------------------------------------------
    # PRINT SUMMARY
    # --------------------------------------------------------

    print("\n")
    print("=" * 70)
    print("SHUHUL ROUTE PLANNER")
    print("=" * 70)

    print(f"District:      {district}")
    print(f"Construction:  {construction}")

    print("\nSTART")
    print(
        f"  Lat: {args.start_lat}"
    )
    print(
        f"  Lon: {args.start_lon}"
    )

    print("\nEND")
    print(
        f"  Lat: {args.end_lat}"
    )
    print(
        f"  Lon: {args.end_lon}"
    )

    print("\nROUTES")
    print("-" * 70)

    for name, data in routes.items():

        print(f"\n{name}")

        print(
            f"  Distance: "
            f"{data['distance_km']:.3f} km"
        )

        print(
            f"  Environmental cost: "
            f"{data['environmental_cost']:.3f}"
        )

    print("\nOUTPUTS")
    print("-" * 70)

    print(
        f"GeoJSON:\n  {geojson_path}"
    )

    print(
        f"JSON:\n  {json_path}"
    )

    print("=" * 70)
    print("ROUTE PLANNING COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()