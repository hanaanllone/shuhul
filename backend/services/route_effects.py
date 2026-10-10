"""
Shuhul route effects: heat, flood and how much mitigation a route owes.

Adds three entries to every route in the impact result:

    heat             existing / after construction / after mitigation,
                     from the district thermal model
    flood            how much of the construction corridor lies on
                     flood-prone land or on land that used to be water
    mitigation_plan  how much of the nearby mitigation land the route
                     needs, zone by zone, and whether that repays the
                     heat it adds

All three are measured on the construction corridor (the route buffered
by half the project width), the same corridor the impact analysis uses.
"""

from pathlib import Path
import json

import geopandas as gpd
import rasterio
from rasterio.mask import mask
from shapely.geometry import shape

from ..config import PROCESSED_ROOT
from . import thermal

# Flood susceptibility classes, as written by build_static_layers.py.
FLOOD_CLASSES = [
    ("low", 0.45),
    ("moderate", 0.65),
    ("high", 0.85),
    ("very_high", float("inf")),
]

MITIGATION_SURFACES = {
    "tree_restoration": "tree",
    "bush_restoration": "shrub",
    "green_roof": "green_roof",
}

# Area of green infrastructure asked for per unit of tree canopy removed.
# Two for one is the starting point; it is a planning assumption.
CANOPY_COMPENSATION_RATIO = 2.0

# If that does not repay the heat a route adds, the plan grows in steps
# until it does or the nearby land runs out.
SIZING_ROUNDS = 6
SIZING_STEP = 1.6
SIZING_FIRST_STEP_M2 = 1000.0
HEAT_REPAID_TOLERANCE_DEGREE_HA = 0.05


def _corridors(route_file, width_m, crs):
    """Construction corridor of every route, in the district CRS."""
    routes = gpd.read_file(route_file)
    if routes.crs is None:
        routes = routes.set_crs("EPSG:4326")

    routes = routes.to_crs(crs)
    return {
        str(row["route"]): row.geometry.buffer(float(width_m) / 2.0)
        for _, row in routes.iterrows()
        if row.geometry is not None and not row.geometry.is_empty
    }


def _mitigation_zones(mitigation_result, route_name, crs):
    """Mitigation zones found for a route, nearest first."""
    features = (mitigation_result or {}).get("geojson", {}).get("features", [])
    picked = []

    for feature in features:
        properties = feature.get("properties", {})
        surface = MITIGATION_SURFACES.get(properties.get("intervention"))

        if properties.get("route") != route_name or surface is None or not feature.get("geometry"):
            continue

        picked.append((properties, surface, shape(feature["geometry"])))

    if not picked:
        return []

    projected = gpd.GeoSeries([item[2] for item in picked], crs="EPSG:4326").to_crs(crs)
    zones = []

    for (properties, surface, _), geometry in zip(picked, projected):
        if geometry.geom_type not in ("Polygon", "MultiPolygon") or geometry.is_empty:
            continue

        zones.append({
            "zone_id": properties.get("zone_id"),
            "intervention": properties.get("intervention"),
            "surface": surface,
            "geometry": geometry,
            "distance_m": float(properties.get("distance_m") or 0.0),
            "available_m2": float(properties.get("capacity_m2") or geometry.area),
            "allocated_m2": 0.0,
        })

    return sorted(zones, key=lambda zone: zone["distance_m"])


def _allocate(zones, target_m2):
    """Fill zones nearest first until the target area is reached."""
    remaining = target_m2

    for zone in zones:
        zone["allocated_m2"] = max(min(zone["available_m2"], remaining), 0.0)
        remaining -= zone["allocated_m2"]


def _changes(zones):
    """
    Allocated mitigation as thermal changes. A zone that is only partly
    used is treated as planted evenly at that share.
    """
    return [
        (
            zone["geometry"],
            zone["surface"],
            min(zone["allocated_m2"] / zone["geometry"].area, 1.0),
        )
        for zone in zones
        if zone["allocated_m2"] > 0 and zone["geometry"].area > 0
    ]


def _corridor_values(path, corridor):
    """Cell values of a district raster inside a corridor, and the cell area."""
    if not path.exists():
        return None, None

    with rasterio.open(path) as src:
        try:
            data, _ = mask(src, [corridor], crop=True, filled=False)
        except ValueError:
            return None, None

        values = data[0].compressed().astype("float32")
        return values, abs(src.transform.a * src.transform.e)


def flood_exposure(district, corridor):
    directory = Path(PROCESSED_ROOT) / district
    index, cell_m2 = _corridor_values(directory / "flood.tif", corridor)

    if index is None:
        return {"available": False}

    areas = {}
    lower = -float("inf")
    for name, upper in FLOOD_CLASSES:
        areas[f"{name}_m2"] = round(float(((index >= lower) & (index < upper)).sum()) * cell_m2, 1)
        lower = upper

    lost, lost_cell = _corridor_values(directory / "water_lost.tif", corridor)
    recorded, recorded_cell = _corridor_values(directory / "water_occurrence.tif", corridor)

    # Water cells are left out of the index, so the classes add up to
    # the land part of the corridor.
    land_m2 = sum(areas.values())
    prone_m2 = areas["high_m2"] + areas["very_high_m2"]

    return {
        "available": True,
        **areas,
        "flood_prone_m2": round(prone_m2, 1),
        "flood_prone_pct": round(100 * prone_m2 / land_m2, 1) if land_m2 else None,
        "lost_water_m2": None if lost is None else round(float((lost > 0).sum()) * lost_cell, 1),
        "recorded_water_m2": (
            None if recorded is None
            else round(float((recorded > 0).sum()) * recorded_cell, 1)
        ),
        "note": (
            "Screening index. Flood-prone means the high and very high classes; "
            "very high is land where water has been recorded since 1984."
        ),
    }


def heat_effect(district, corridor, mitigation, construction):
    try:
        result = thermal.construction_scenarios(
            corridor,
            mitigation=mitigation,
            district=district,
            construction=construction,
        )
    except thermal.ThermalUnavailable:
        return {"available": False}

    scenarios = result["scenarios"]
    built = scenarios["after_construction"]["impact_zone"]
    mitigated = scenarios.get("after_mitigation", {}).get("impact_zone")

    added = built["heat_added_degree_ha"]
    summary = {
        "available": True,
        "scenarios": scenarios,
        "impact_zone_m": result["impact_zone_m"],
        "heat_added_degree_ha": added,
        "corridor_change_c": scenarios["after_construction"]["footprint"]["mean_change_c"],
        "method": result["method"],
    }

    if mitigated is not None:
        # What is still warmer near the route once the mitigation is in
        # place. Mitigation planted outside the impact zone cools its own
        # surroundings but does not repay heat here.
        remaining = max(mitigated["heat_added_degree_ha"] - mitigated["heat_removed_degree_ha"], 0.0)
        repaid = min(max(added - remaining, 0.0), added)

        summary.update({
            "heat_remaining_degree_ha": round(remaining, 2),
            "heat_repaid_degree_ha": round(repaid, 2),
            "heat_repaid_pct": round(100 * repaid / added, 1) if added > 0 else None,
            "corridor_change_after_mitigation_c": (
                scenarios["after_mitigation"]["footprint"]["mean_change_c"]
            ),
        })

    return summary


def plan_mitigation(district, corridor, zones, canopy_removed_m2, construction):
    """
    Size the mitigation to what the route owes.

    It starts at twice the tree canopy the route removes, placed in the
    nearest zones first. If the thermal model says that still leaves
    the surroundings warmer, the plan grows until the added heat is
    repaid or the zones found near the route are used up.

    Returns (heat, plan).
    """
    available = sum(zone["available_m2"] for zone in zones)
    owed = CANOPY_COMPENSATION_RATIO * canopy_removed_m2
    target = min(owed, available)
    status = "no_zones" if not zones else "sized_to_canopy"

    heat = heat_effect(district, corridor, None, construction)

    for _ in range(SIZING_ROUNDS):
        if not zones or not heat.get("available"):
            break

        _allocate(zones, target)
        heat = heat_effect(district, corridor, _changes(zones) or None, construction)

        remaining = heat.get("heat_remaining_degree_ha", heat["heat_added_degree_ha"])
        if remaining <= HEAT_REPAID_TOLERANCE_DEGREE_HA:
            status = "heat_repaid" if target > owed else "sized_to_canopy"
            break

        if target >= available:
            status = "nearby_land_used_up"
            break

        target = min(max(target * SIZING_STEP, target + SIZING_FIRST_STEP_M2), available)
        status = "grown_for_heat"

    allocated = sum(zone["allocated_m2"] for zone in zones)

    plan = {
        "status": status,
        "canopy_removed_m2": round(canopy_removed_m2, 1),
        "canopy_ratio": CANOPY_COMPENSATION_RATIO,
        "canopy_owed_m2": round(owed, 1),
        "allocated_m2": round(allocated, 1),
        "available_nearby_m2": round(available, 1),
        "heat_repaid_pct": heat.get("heat_repaid_pct"),
        "zones": [
            {
                "zone_id": zone["zone_id"],
                "intervention": zone["intervention"],
                "distance_m": round(zone["distance_m"], 1),
                "available_m2": round(zone["available_m2"], 1),
                "allocated_m2": round(zone["allocated_m2"], 1),
            }
            for zone in zones
        ],
        "note": (
            f"Starts at {CANOPY_COMPENSATION_RATIO:g} m² of green infrastructure per m² of "
            "tree canopy removed, a planning assumption, then grows until the modelled "
            "heat added near the route is repaid or the nearby zones are used up. "
            "Planting is credited at maturity."
        ),
    }

    return heat, plan


def add_route_effects(district, payload, impact_result, mitigation_result, output_dir):
    """
    Add heat, flood and mitigation-plan entries to each route of the
    impact result, in place, and save them next to the other project files.
    """
    construction = payload["constructionType"]
    route_file = Path(output_dir) / f"routes_{construction}.geojson"

    with rasterio.open(Path(PROCESSED_ROOT) / district / "ndvi.tif") as src:
        crs = src.crs

    corridors = _corridors(route_file, payload["widthMeters"], crs)
    effects = {}

    for route_name, route in impact_result.get("routes", {}).items():
        corridor = corridors.get(route_name)
        if corridor is None:
            continue

        zones = _mitigation_zones(mitigation_result, route_name, crs)
        canopy_removed = float(route.get("canopy", {}).get("canopy_area_m2") or 0.0)

        route["heat"], route["mitigation_plan"] = plan_mitigation(
            district, corridor, zones, canopy_removed, construction
        )
        route["flood"] = flood_exposure(district, corridor)

        effects[route_name] = {
            "heat": route["heat"],
            "flood": route["flood"],
            "mitigation_plan": route["mitigation_plan"],
        }

    path = Path(output_dir) / f"effects_{construction}.json"
    path.write_text(json.dumps(effects, indent=2), encoding="utf-8")

    return effects
