from pathlib import Path
import json
import traceback

from ..config import PROCESSED_ROOT, OUTPUT_ROOT, DEFAULT_DISTRICT
from ..db import update_project


def project_dir(project_id):
    """Every file a project produces lives in its own folder."""
    path = OUTPUT_ROOT / "projects" / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stage(project_id, name, progress):
    update_project(
        project_id,
        status="running",
        stage=name,
        progress=progress,
        error=None,
    )


def validate_payload(payload):
    required = [
        "projectName",
        "constructionType",
        "widthMeters",
        "start",
        "end",
        "softPreferences",
        "hardConstraints",
    ]

    missing = [x for x in required if x not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")

    if payload["constructionType"] not in {"road", "bridge", "flyover"}:
        raise ValueError(
            "constructionType must be road, bridge, or flyover"
        )

    if float(payload["widthMeters"]) <= 0:
        raise ValueError("widthMeters must be greater than 0")

    for endpoint in ("start", "end"):
        point = payload[endpoint]

        if (
            not isinstance(point, dict)
            or "lat" not in point
            or "lng" not in point
        ):
            raise ValueError(f"{endpoint} must contain lat and lng")

        lat = float(point["lat"])
        lng = float(point["lng"])

        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError(f"Invalid coordinates for {endpoint}")

    for key in (
        "treePriority",
        "greeneryPriority",
        "waterPriority",
        "shortestPriority",
        "constructionPriority",
        "heatPriority",
        "floodPriority",
    ):
        value = float(payload["softPreferences"].get(key, 50))

        if not 0 <= value <= 100:
            raise ValueError(f"{key} must be between 0 and 100")


def resolve_district(payload):
    """
    Resolve the district using the actual district GeoJSON polygons.

    Falls back to raster bounds only if the polygon resolver is not
    available. Cross-district routing is still rejected.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        return resolve_district_from_raster(payload)

    geojson_root = (
        Path(__file__).resolve().parents[2]
        / "districts-geojson"
    )

    if not geojson_root.exists():
        return resolve_district_from_raster(payload)

    start = Point(
        float(payload["start"]["lng"]),
        float(payload["start"]["lat"]),
    )
    end = Point(
        float(payload["end"]["lng"]),
        float(payload["end"]["lat"]),
    )

    start_district = None
    end_district = None

    for path in sorted(geojson_root.glob("*.geojson")):
        district = path.stem

        try:
            gdf = gpd.read_file(path)

            if gdf.empty:
                continue

            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            else:
                gdf = gdf.to_crs("EPSG:4326")

            geometry = gdf.geometry.unary_union

            if geometry.contains(start) or geometry.touches(start):
                start_district = district

            if geometry.contains(end) or geometry.touches(end):
                end_district = district

        except Exception:
            continue

        if start_district and end_district:
            break

    print("=" * 70)
    print("SHUHUL DISTRICT POLYGON RESOLUTION")
    print("=" * 70)
    print(f"Location A district: {start_district}")
    print(f"Location B district: {end_district}")

    if start_district and end_district:
        if start_district != end_district:
            raise ValueError(
                "Location A and Location B are in different districts. "
                "Cross-district routing is not enabled yet."
            )

        print(f"Resolved district: {start_district}")
        print("Resolution source: district_polygon")
        print("=" * 70)

        return start_district, "district_polygon"

    return resolve_district_from_raster(payload)


def resolve_district_from_raster(payload):
    try:
        import rasterio
        from pyproj import Transformer
    except ImportError:
        return DEFAULT_DISTRICT, "fallback_no_geospatial_runtime"

    districts = (
        [p for p in PROCESSED_ROOT.iterdir() if p.is_dir()]
        if PROCESSED_ROOT.exists()
        else []
    )

    start = payload["start"]
    end = payload["end"]

    for district_dir in districts:
        ndvi = district_dir / "ndvi.tif"

        if not ndvi.exists():
            continue

        try:
            with rasterio.open(ndvi) as src:
                transformer = Transformer.from_crs(
                    "EPSG:4326",
                    src.crs,
                    always_xy=True,
                )

                sx, sy = transformer.transform(
                    float(start["lng"]),
                    float(start["lat"]),
                )

                ex, ey = transformer.transform(
                    float(end["lng"]),
                    float(end["lat"]),
                )

                b = src.bounds

                start_inside = (
                    b.left <= sx <= b.right
                    and b.bottom <= sy <= b.top
                )

                end_inside = (
                    b.left <= ex <= b.right
                    and b.bottom <= ey <= b.top
                )

                if start_inside and end_inside:
                    return district_dir.name, "raster_bounds"

                if start_inside and not end_inside:
                    raise ValueError(
                        "Location A and Location B are in different "
                        "districts. Cross-district routing is not enabled yet."
                    )

        except ValueError:
            raise
        except Exception:
            continue

    return DEFAULT_DISTRICT, "fallback_default_district"


def run_cost_surface(district, payload, output_dir):
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "cost_surface.py"
    )

    if not script.exists():
        raise RuntimeError(
            "cost_surface.py is missing from backend/scripts."
        )

    from importlib.util import spec_from_file_location, module_from_spec

    spec = spec_from_file_location(
        "shuhul_cost_surface",
        script,
    )

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    prefs = payload["softPreferences"]
    hard = payload["hardConstraints"]
    construction = payload["constructionType"]

    result = module.build_cost_surface(
        district_dir=PROCESSED_ROOT / district,
        output_soft=(
            output_dir / f"soft_cost_{construction}.tif"
        ),
        output_hard=(
            output_dir / f"hard_constraints_{construction}.tif"
        ),
        construction=construction,
        tree_priority=float(
            prefs.get("treePriority", 50)
        ) / 100,
        greenery_priority=float(
            prefs.get("greeneryPriority", 50)
        ) / 100,
        water_priority=float(
            prefs.get("waterPriority", 50)
        ) / 100,
        shortest_priority=float(
            prefs.get("shortestPriority", 50)
        ) / 100,
        construction_priority=float(
            prefs.get("constructionPriority", 50)
        ) / 100,
        hard_heritage=bool(hard.get("heritage")),
        hard_water=bool(hard.get("water")),
        hard_forest=bool(hard.get("forest")),
        heat_priority=float(
            prefs.get("heatPriority", 50)
        ) / 100,
        flood_priority=float(
            prefs.get("floodPriority", 50)
        ) / 100,
        hard_flood=bool(hard.get("flood")),
        hard_steep=bool(hard.get("steepSlope")),
    )

    config_path = (
        output_dir
        / f"config_{construction}.json"
    )

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    result["config_output"] = str(config_path)

    return result


def generate_routes(district, payload, cost_result, output_dir):
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "route_planner.py"
    )

    if not script.exists():
        raise RuntimeError(
            "route_planner.py is not present in backend/scripts."
        )

    from importlib.util import spec_from_file_location, module_from_spec

    spec = spec_from_file_location(
        "shuhul_route_planner",
        script,
    )

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "plan_routes"):
        raise RuntimeError(
            "route_planner.py must expose plan_routes(...) "
            "for Flask integration."
        )

    return module.plan_routes(
        district=district,
        construction=payload["constructionType"],
        start=payload["start"],
        end=payload["end"],
        cost_result=cost_result,
        output_dir=output_dir,
    )


def run_impact_analysis(district, payload, output_dir):
    """
    Connect the existing impact_analyzer.py to the backend pipeline.

    We intentionally reuse the analyzer's existing functions rather than
    duplicating any GIS calculations here.
    """
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "impact_analyzer.py"
    )

    if not script.exists():
        raise RuntimeError(
            "impact_analyzer.py is not present in backend/scripts."
        )

    from importlib.util import spec_from_file_location, module_from_spec

    spec = spec_from_file_location(
        "shuhul_impact_analyzer",
        script,
    )

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    # The analyzer reads the district layers from the configured data folder.
    module.PROCESSED = Path(PROCESSED_ROOT)

    required_functions = [
        "load_routes",
        "analyze_route",
        "build_comparison",
    ]

    missing = [
        name
        for name in required_functions
        if not hasattr(module, name)
    ]

    if missing:
        raise RuntimeError(
            "impact_analyzer.py is missing required functions: "
            + ", ".join(missing)
        )

    construction = payload["constructionType"]
    width = float(payload["widthMeters"])

    # These match the existing impact_analyzer defaults.
    ndvi_threshold = float(
        payload.get("analysis", {}).get(
            "ndviThreshold",
            module.DEFAULT_NDVI_GREEN_THRESHOLD,
        )
    )

    ndwi_threshold = float(
        payload.get("analysis", {}).get(
            "ndwiWaterThreshold",
            module.DEFAULT_NDWI_WATER_THRESHOLD,
        )
    )

    high_slope_threshold = float(
        payload.get("analysis", {}).get(
            "highSlopeThreshold",
            module.DEFAULT_HIGH_SLOPE_THRESHOLD,
        )
    )

    canopy_area_per_tree = float(
        payload.get("analysis", {}).get(
            "canopyAreaPerTree",
            module.DEFAULT_CANOPY_AREA_PER_TREE,
        )
    )

    print()
    print("=" * 70)
    print("SHUHUL — BACKEND IMPACT ANALYSIS")
    print("=" * 70)
    print(f"District:     {district}")
    print(f"Construction: {construction}")
    print(f"Width:        {width} m")
    print("=" * 70)

    routes = module.load_routes(
        district,
        construction,
        route_file=output_dir / f"routes_{construction}.geojson",
    )

    cost_path = output_dir / f"soft_cost_{construction}.tif"

    cost_raster = None

    try:
        if cost_path.exists():
            import rasterio
            cost_raster = rasterio.open(cost_path)

        results = {}

        for route_name, route in routes.items():
            results[route_name] = module.analyze_route(
                route_name=route_name,
                route=route,
                district=district,
                construction=construction,
                width=width,
                ndvi_threshold=ndvi_threshold,
                ndwi_threshold=ndwi_threshold,
                high_slope_threshold=high_slope_threshold,
                canopy_area_per_tree=canopy_area_per_tree,
                cost_raster=cost_raster,
            )

        comparison = module.build_comparison(results)

        impact_result = {
            "district": district,
            "construction": construction,
            "project_width_m": width,
            "routes": results,
            "route_comparison": comparison,
            "assumptions": {
                "ndvi_green_threshold": ndvi_threshold,
                "ndwi_water_threshold": ndwi_threshold,
                "high_slope_threshold_deg": high_slope_threshold,
                "canopy_area_per_tree_m2": canopy_area_per_tree,
                "width_definition": (
                    "Total project width. Impact corridor uses "
                    "width / 2 as buffer radius."
                ),
                "tree_equivalent_warning": (
                    "Estimated tree-equivalent canopy impact is a "
                    "planning-level estimate and is not an individual "
                    "tree count."
                ),
            },
        }
        
        # ------------------------------------------------------------
        # Persist impact result for mitigation + report
        # ------------------------------------------------------------
        
        impact_file = output_dir / f"impact_{construction}.json"
        
        with open(impact_file, "w", encoding="utf-8") as f:
            json.dump(
                impact_result,
                f,
                indent=2,
                default=str,
            )
        
        print()
        print("=" * 70)
        print("IMPACT ARTIFACT WRITTEN")
        print("=" * 70)
        print(f"Impact file: {impact_file}")
        print("=" * 70)
        
        return impact_result
    finally:
        if cost_raster is not None:
            cost_raster.close()



def _load_module_from_path(module_name, script):
    from importlib.util import spec_from_file_location, module_from_spec

    spec = spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {script}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_mitigation_analysis(district, payload, output_dir):
    """Run the existing local-first mitigation engine and return API-safe JSON."""
    project_root = Path(__file__).resolve().parents[2]
    script = project_root / "backend" / "scripts" / "mitigation_analyzer.py"
    if not script.exists():
        # pipeline.py lives under backend/services, so this is the normal fallback.
        script = Path(__file__).resolve().parents[1] / "scripts" / "mitigation_analyzer.py"

    if not script.exists():
        raise RuntimeError("mitigation_analyzer.py is not present in backend/scripts.")

    module = _load_module_from_path("shuhul_mitigation_analyzer", script)

    required = [
        "first_existing",
        "load_routes",
        "load_route_impacts",
        "load_vector",
        "find_mitigation_for_route",
        "write_json",
        "make_feature_collection",
    ]
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "mitigation_analyzer.py is missing required functions: "
            + ", ".join(missing)
        )

    construction = payload["constructionType"]
    district_dir = PROCESSED_ROOT / district

    route_file = output_dir / f"routes_{construction}.geojson"
    impact_file = output_dir / f"impact_{construction}.json"

    if not route_file.exists():
        raise FileNotFoundError(f"Route file not found: {route_file}")
    if not impact_file.exists():
        raise FileNotFoundError(f"Impact file not found: {impact_file}")

    ndvi_path = module.first_existing(
        district_dir, ["ndvi.tif", "ndvi"], required=True
    )
    ndwi_path = module.first_existing(district_dir, ["ndwi.tif", "ndwi"])
    water_path = module.first_existing(district_dir, ["water.tif", "water"])
    canopy_path = module.first_existing(
        district_dir, ["tree_height.tif", "canopy.tif", "canopy", "chm.tif", "chm"]
    )
    buildings_path = module.first_existing(
        district_dir, ["buildings.gpkg", "buildings"]
    )
    heritage_path = module.first_existing(
        district_dir, ["heritage.gpkg", "heritage"]
    )
    roads_path = module.first_existing(
        district_dir, ["roads.gpkg", "roads"]
    )

    import rasterio

    with rasterio.open(ndvi_path) as src:
        target_crs = src.crs

    routes = module.load_routes(route_file, target_crs)
    impacts = module.load_route_impacts(impact_file)

    buildings = module.load_vector(buildings_path, target_crs)
    heritage = module.load_vector(heritage_path, target_crs)
    roads = module.load_vector(roads_path, target_crs)

    route_results = []

    print()
    print("=" * 70)
    print("SHUHUL — BACKEND MITIGATION ANALYSIS")
    print("=" * 70)
    print(f"District:     {district}")
    print(f"Construction: {construction}")
    print(f"Width:        {float(payload['widthMeters'])} m")
    print("=" * 70)

    for route in routes:
        route_name = route["route"]
        impact = module.impact_for_route(route_name, impacts)

        print()
        print(f"MITIGATION FOR {route_name}")

        result = module.find_mitigation_for_route(
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

        print(
            f"  radius={result['search_radius_m']}m | "
            f"zones={result['candidate_summary']['selected_zone_count']} | "
            f"capacity={result['candidate_summary']['selected_capacity_m2']:,.1f} m²"
        )

    output_json = output_dir / f"mitigation_{construction}.json"
    output_geojson = output_dir / f"mitigation_{construction}.geojson"

    mitigation_output = {
        "project": {
            "district": district,
            "construction": construction,
            "project_width_m": float(payload["widthMeters"]),
        },
        "search_strategy": {
            "principle": (
                "Search for feasible mitigation opportunities as close "
                "as possible to the construction impact corridor."
            ),
            "search_radii_m": list(module.SEARCH_RADII_M),
            "minimum_zones": module.MIN_ZONES,
            "minimum_total_capacity_m2": module.MIN_TOTAL_CAPACITY_M2,
        },
        "intervention_rules": {
            "open_land": "tree_restoration",
            "suitable_road": "bush_restoration",
            "suitable_building": "green_roof",
            "minimum_bush_road_width_m": module.MIN_BUSH_ROAD_WIDTH_M,
            "average_roof_area_m2": module.AVERAGE_ROOF_AREA_M2,
            "tree_minimum_road_width_m": module.MIN_TREE_ROAD_WIDTH_M,
        },
        "assumptions": {
            "ndvi_open_threshold": module.NDVI_OPEN_THRESHOLD,
            "ndwi_water_threshold": module.NDWI_WATER_THRESHOLD,
            "existing_canopy_height_threshold_m": module.CANOPY_HEIGHT_THRESHOLD_M,
            "building_exclusion_buffer_m": module.BUILDING_EXCLUSION_BUFFER_M,
            "heritage_exclusion_buffer_m": module.HERITAGE_EXCLUSION_BUFFER_M,
            "minimum_open_zone_area_m2": module.MIN_OPEN_ZONE_AREA_M2,
            "thermal_note": (
                "Mitigation capacity is a planning-level spatial "
                "opportunity estimate and is not an exact thermal or "
                "ecological equivalence."
            ),
        },
        "routes": route_results,
    }

    module.write_json(output_json, mitigation_output)

    geojson = module.make_feature_collection(
        route_results,
        source_crs=target_crs,
        output_crs="EPSG:4326",
    )
    output_geojson.write_text(
        json.dumps(geojson, indent=2),
        encoding="utf-8",
    )

    # Re-read the sanitized JSON so no Shapely objects enter the API/database.
    sanitized = _read_json_file(output_json)

    return {
        **sanitized,
        "files": {
            "json": str(output_json),
            "geojson": str(output_geojson),
        },
        "geojson": geojson,
    }


def run_route_effects(district, payload, impact_result, mitigation_result, output_dir):
    """Add modelled heat and flood effects to each route of the impact result."""
    from .route_effects import add_route_effects

    return add_route_effects(
        district,
        payload,
        impact_result,
        mitigation_result,
        output_dir,
    )


def run_report_generation(district, payload, impact_result, mitigation_result, output_dir):
    project_root = Path(__file__).resolve().parents[2]
    script = project_root / "backend" / "scripts" / "report_generator.py"

    if not script.exists():
        raise RuntimeError("report_generator.py is not present in backend/scripts.")

    module = _load_module_from_path("shuhul_report_generator", script)

    report = module.build_report(
        project_payload=payload,
        district=district,
        impact_result=impact_result,
        mitigation_result=mitigation_result,
    )

    written = module.write_report(report, output_dir)

    return {
        "summary": report["summary"],
        "data": report,
        "files": {
            "json": written["json_path"],
            "html": written["html_path"],
        },
    }


def load_result_geojson(output_dir, construction):
    """Expose route geometry to the frontend without making the frontend read files."""
    route_path = output_dir / f"routes_{construction}.geojson"
    if not route_path.exists():
        return None
    return _read_json_file(route_path)

PREVIEW_MAX_POINTS = 60


def build_preview(payload, route_geojson):
    """
    A small outline of the project for its card on the home page: the
    two endpoints and each route thinned to a few dozen points.
    """
    routes = []

    for feature in (route_geojson or {}).get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue

        coordinates = geometry["coordinates"]
        step = max(1, len(coordinates) // PREVIEW_MAX_POINTS)
        thinned = coordinates[::step]
        if thinned[-1] != coordinates[-1]:
            thinned.append(coordinates[-1])

        routes.append({
            "name": feature.get("properties", {}).get("route"),
            "points": [[round(lat, 5), round(lng, 5)] for lng, lat in thinned],
        })

    return {
        "start": payload.get("start"),
        "end": payload.get("end"),
        "routes": routes,
    }


def run_project(project_id, payload):
    output_dir = None

    try:
        _stage(
            project_id,
            "Validating project inputs",
            10,
        )

        validate_payload(payload)
        output_dir = project_dir(project_id)

        _stage(
            project_id,
            "Resolving project district",
            20,
        )

        district, district_source = resolve_district(payload)

        print("=" * 70)
        print("SHUHUL DISTRICT RESOLUTION")
        print("=" * 70)
        print(f"Start: {payload['start']}")
        print(f"End: {payload['end']}")
        print(f"District: {district}")
        print(f"Resolution source: {district_source}")
        print(f"Processed root: {PROCESSED_ROOT}")
        print("=" * 70)

        _stage(
            project_id,
            "Building environmental cost surface",
            35,
        )

        cost_result = run_cost_surface(
            district,
            payload,
            output_dir,
        )

        _stage(
            project_id,
            "Generating Route A / B / C",
            55,
        )

        routes = generate_routes(
            district,
            payload,
            cost_result,
            output_dir,
        )

        _stage(
            project_id,
            "Analyzing environmental impact of Route A / B / C",
            65,
        )

        impact_result = run_impact_analysis(
            district,
            payload,
            output_dir,
        )

        _stage(
            project_id,
            "Finding local mitigation opportunities",
            80,
        )

        mitigation_result = run_mitigation_analysis(
            district,
            payload,
            output_dir,
        )

        _stage(
            project_id,
            "Estimating heat and flood effects",
            88,
        )

        run_route_effects(
            district,
            payload,
            impact_result,
            mitigation_result,
            output_dir,
        )

        _stage(
            project_id,
            "Preparing project report",
            94,
        )

        report_result = run_report_generation(
            district,
            payload,
            impact_result,
            mitigation_result,
            output_dir,
        )

        route_geojson = load_result_geojson(
            output_dir,
            payload["constructionType"],
        )

        result = {
            "projectId": project_id,
            "project": payload,
            "district": district,
            "districtResolution": district_source,
            "costSurface": cost_result,
            "routes": routes,
            "routeGeoJSON": route_geojson,
            "impact": impact_result,
            "mitigation": mitigation_result,
            "report": report_result,
            "pipeline": {
                "completed": [
                    "validate",
                    "district_resolution",
                    "cost_surface",
                    "route_generation",
                    "impact_analysis",
                    "mitigation_analysis",
                    "route_effects",
                    "report_generation",
                ],
            },
        }

        update_project(
            project_id,
            status="completed",
            stage="Analysis, mitigation and report complete",
            progress=100,
            result_json=result,
            preview_json=build_preview(payload, route_geojson),
        )

    except Exception as exc:
        message = str(exc)
        # The router's own wording means nothing to a planner.
        if "no minimum-cost path" in message:
            message = (
                "No route is possible within these limits. Land marked as never to be "
                "built on lies between the two points with no way around it. Untick a "
                "limit under Never build on, or move a point."
            )
        elif "lies inside a hard constraint" in message:
            message = (
                "One of the points sits on land marked as never to be built on. "
                "Move it, or untick that limit under Never build on."
            )
        elif "outside the valid planning area" in message or "outside the raster" in message:
            message = "One of the points is outside the district's data. Move it inside."

        update_project(
            project_id,
            status="failed",
            stage="Analysis failed",
            progress=0,
            error=message,
        )

        traceback.print_exc()

    finally:
        # The cost rasters are the only large files a run produces and
        # nothing reads them once the report is written.
        if output_dir is not None:
            for raster in output_dir.glob("*.tif"):
                raster.unlink(missing_ok=True)
