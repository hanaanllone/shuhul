"""
Shuhul route effects: heat and flood.

Adds two entries to every route in the impact result:

    heat    existing / after construction / after mitigation, from the
            district thermal model, and how much of the added heat the
            proposed mitigation repays near the route
    flood   how much of the construction corridor lies on flood-prone
            land or on land that used to be water

Both are measured on the construction corridor (the route buffered by
half the project width), the same corridor the impact analysis uses.
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


def _mitigation_changes(mitigation_result, route_name, crs):
    """Proposed green infrastructure for a route as (shape, surface) pairs."""
    features = (mitigation_result or {}).get("geojson", {}).get("features", [])
    shapes = []
    surfaces = []

    for feature in features:
        properties = feature.get("properties", {})
        if properties.get("route") != route_name or not feature.get("geometry"):
            continue

        surface = MITIGATION_SURFACES.get(properties.get("intervention"))
        if surface is None:
            continue

        shapes.append(shape(feature["geometry"]))
        surfaces.append(surface)

    if not shapes:
        return []

    projected = gpd.GeoSeries(shapes, crs="EPSG:4326").to_crs(crs)
    return [
        (geometry, surface)
        for geometry, surface in zip(projected, surfaces)
        if geometry.geom_type in ("Polygon", "MultiPolygon") and not geometry.is_empty
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


def add_route_effects(district, payload, impact_result, mitigation_result, output_dir):
    """
    Add heat and flood entries to each route of the impact result, in
    place, and save them next to the other project files.
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

        mitigation = _mitigation_changes(mitigation_result, route_name, crs)

        route["heat"] = heat_effect(district, corridor, mitigation, construction)
        route["flood"] = flood_exposure(district, corridor)
        effects[route_name] = {"heat": route["heat"], "flood": route["flood"]}

    path = Path(output_dir) / f"effects_{construction}.json"
    path.write_text(json.dumps(effects, indent=2), encoding="utf-8")

    return effects
