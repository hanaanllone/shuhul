"""
Shuhul site finder: where building would cost the land least.

Route planning answers "how do I get from A to B". This answers the
question before it: "where could a new school, depot or housing block
go at all". It ranks the district's 500 m zones by what building there
would cost: few trees to lose, little flood risk, little heat added,
gentle ground, and enough open land to hold the project.

It reads the zone measurements made for ecological stress, so both
pages describe the same zones.

    GET /api/sites/<district>?min_ha=2&road=1&flood=1
"""

import json

import numpy as np

from .stress_analysis import cached_stress, standing

# What makes a zone a cheaper place to build, and how much each counts:
# (zone property, weight, True when a high value is better, the reason in words).
FACTORS = {
    "trees": ("canopy_cover_pct", 0.25, False, "Few trees to lose"),
    "flood": ("flood_prone_pct", 0.25, False, "Little flood-prone land"),
    "heat": ("warming_if_paved_c", 0.20, False, "Adds little heat"),
    "room": ("open_land_ha", 0.20, True, "Plenty of open land"),
    "slope": ("mean_slope_deg", 0.10, False, "Gentle ground"),
}

# Zones left out whatever the planner asks for.
MOSTLY_WATER_PCT = 50.0
FOREST_PCT = 20.0
FLOOD_LIMIT_PCT = 50.0

# The best 15% of the zones that qualify are "good", the next 35% "fair".
GOOD_SHARE = 0.15
FAIR_SHARE = 0.50
REASON_MIN = 0.7
MAX_REASONS = 3


class SitesUnavailable(Exception):
    """The district does not have the layers this needs."""


def _ruled_out(zone, min_ha, need_road, avoid_flood):
    """Why a zone cannot be offered, or None when it can."""
    if (zone.get("water_pct") or 0) >= MOSTLY_WATER_PCT:
        return "Mostly water or wetland"
    if (zone.get("heritage_pct") or 0) > 0:
        return "Within 100 m of a heritage site"
    if (zone.get("forest_pct") or 0) >= FOREST_PCT:
        return "Hill forest"
    if (zone.get("open_land_ha") or 0) < min_ha:
        return f"Less than {min_ha:g} ha of open land"
    if need_road and not (zone.get("road_pct") or 0) > 0:
        return "No road in the zone"
    if avoid_flood and (zone.get("flood_prone_pct") or 0) >= FLOOD_LIMIT_PCT:
        return "Half or more is flood-prone"
    return None


def find_sites(district, min_ha=1.0, need_road=True, avoid_flood=True):
    data = json.loads(cached_stress(district))
    zones = [feature["properties"] for feature in data["features"]]

    if not any(zone.get("open_land_ha") is not None for zone in zones):
        raise SitesUnavailable("No data for this district.")

    for zone in zones:
        zone["site_score"] = None
        zone["site_rank"] = None
        zone["site_factors"] = {}
        zone["site_reasons"] = []
        zone["site_ruled_out"] = _ruled_out(zone, min_ha, need_road, avoid_flood)
        zone["site_level"] = "RULED_OUT"

    eligible = [zone for zone in zones if zone["site_ruled_out"] is None]

    # Each factor is the zone's standing among every zone that could be
    # built on at all, so the comparison does not shift with the filters.
    comparable = [
        zone for zone in zones
        if (zone.get("water_pct") or 0) < MOSTLY_WATER_PCT and zone.get("open_land_ha") is not None
    ]
    spread = {}
    for key, (field, _, _, _) in FACTORS.items():
        values = np.sort(np.array(
            [zone[field] for zone in comparable if zone.get(field) is not None],
            dtype="float64",
        ))
        if values.size >= 2 and values[-1] > values[0]:
            spread[key] = values

    for zone in eligible:
        parts = {}
        for key, (field, weight, high_is_better, _) in FACTORS.items():
            if key in spread and zone.get(field) is not None:
                parts[key] = (standing(spread[key], zone[field], high_is_better), weight)

        if not parts:
            continue

        zone["site_score"] = round(float(np.average(
            [value for value, _ in parts.values()],
            weights=[weight for _, weight in parts.values()],
        )), 3)
        zone["site_factors"] = {key: round(value, 3) for key, (value, _) in parts.items()}

        ranked = sorted(parts.items(), key=lambda item: item[1][0] * item[1][1], reverse=True)
        zone["site_reasons"] = [
            FACTORS[key][3] for key, (value, _) in ranked if value >= REASON_MIN
        ][:MAX_REASONS]

    scored = sorted(
        (zone for zone in eligible if zone["site_score"] is not None),
        key=lambda zone: zone["site_score"],
        reverse=True,
    )
    for rank, zone in enumerate(scored, start=1):
        share = rank / len(scored)
        zone["site_rank"] = rank
        zone["site_level"] = (
            "GOOD" if share <= GOOD_SHARE else "FAIR" if share <= FAIR_SHARE else "POOR"
        )

    return {
        "type": "FeatureCollection",
        "district": district,
        "features": data["features"],
        "asked": {"min_ha": min_ha, "need_road": need_road, "avoid_flood": avoid_flood},
        "zones_ranked": len(scored),
        "method": {
            "weights": {key: factor[1] for key, factor in FACTORS.items()},
            "labels": {key: factor[3] for key, factor in FACTORS.items()},
            "scoring": (
                "Each factor is the share of the district's zones that the zone beats "
                "on it, from 0 to 1. The factors are combined by weight."
            ),
            "levels": (
                f"Good is the top {GOOD_SHARE:.0%} of the zones that qualify, fair the "
                f"next {FAIR_SHARE - GOOD_SHARE:.0%}, poor the rest."
            ),
            "always_left_out": (
                "Zones that are mostly water or wetland, within 100 m of a heritage "
                f"site, or {FOREST_PCT:.0f}% or more hill forest."
            ),
            "open_land": (
                "Open land is land that is not water, not built-up and not under trees. "
                "It includes farmland. Shuhul does not know who owns it or what it is used for."
            ),
            "confidence": (
                "Low. A first sift of where to look, to be followed by a site visit "
                "and the land records."
            ),
        },
    }


def register_site_routes(app):
    """Register GET /api/sites/<district>."""
    from flask import jsonify, request

    @app.get("/api/sites/<district>")
    def sites(district):
        try:
            min_ha = min(max(float(request.args.get("min_ha", 1)), 0.25), 25.0)
        except ValueError:
            return jsonify({"error": "min_ha must be a number."}), 400

        try:
            return jsonify(find_sites(
                district,
                min_ha=min_ha,
                need_road=request.args.get("road", "1") != "0",
                avoid_flood=request.args.get("flood", "1") != "0",
            ))
        except FileNotFoundError:
            return jsonify({"error": "No data for this district."}), 404
        except SitesUnavailable as exc:
            return jsonify({"error": str(exc)}), 404
