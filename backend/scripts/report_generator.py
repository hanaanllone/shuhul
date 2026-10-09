from __future__ import annotations

import json
from html import escape
from pathlib import Path


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value, digits=1):
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def build_report(project_payload, district, impact_result, mitigation_result):
    """Build a planning-level project report from deterministic pipeline outputs."""
    impact_routes = impact_result.get("routes", {})
    comparison = impact_result.get("route_comparison", {})

    mitigation_routes = mitigation_result.get("routes", {})
    if isinstance(mitigation_routes, list):
        mitigation_routes = {
            item.get("route", f"Route {i+1}"): item
            for i, item in enumerate(mitigation_routes)
        }

    route_rows = []
    for route_name, impact in impact_routes.items():
        m = mitigation_routes.get(route_name, {})
        summary = m.get("candidate_summary", {})
        route_rows.append({
            "route": route_name,
            "length_km": impact.get("route_length_km"),
            "green_area_m2": impact.get("green_space", {}).get("green_area_m2"),
            "canopy_area_m2": impact.get("canopy", {}).get("canopy_area_m2"),
            "water_area_m2": impact.get("water", {}).get("water_area_m2"),
            "water_crossings": impact.get("water", {}).get("estimated_crossings"),
            "buildings_affected": impact.get("buildings", {}).get("count"),
            "heritage_conflicts": impact.get("heritage", {}).get("count"),
            "environmental_cost_index": impact.get("environmental_cost", {}).get("environmental_cost_index"),
            "tree_equivalent": impact.get("canopy", {}).get("estimated_tree_equivalent"),
            "heat_added_degree_ha": impact.get("heat", {}).get("heat_added_degree_ha"),
            "heat_repaid_pct": impact.get("heat", {}).get("heat_repaid_pct"),
            "corridor_change_c": impact.get("heat", {}).get("corridor_change_c"),
            "flood_prone_m2": impact.get("flood", {}).get("flood_prone_m2"),
            "lost_water_m2": impact.get("flood", {}).get("lost_water_m2"),
            "mitigation_radius_m": m.get("search_radius_m"),
            "mitigation_zones": summary.get("selected_zone_count", 0),
            "mitigation_capacity_m2": summary.get("selected_capacity_m2", 0),
        })

    total_zones = sum(_num(r.get("mitigation_zones")) for r in route_rows)
    total_capacity = sum(_num(r.get("mitigation_capacity_m2")) for r in route_rows)

    heat_method = next(
        (
            impact["heat"]["method"]
            for impact in impact_routes.values()
            if impact.get("heat", {}).get("available")
        ),
        None,
    )

    return {
        "title": project_payload.get("projectName", "Shuhul Project Report"),
        "district": district,
        "construction": project_payload.get("constructionType"),
        "project_width_m": _num(project_payload.get("widthMeters")),
        "generated_by": "Shuhul deterministic GIS planning pipeline",
        "summary": {
            "routes_analyzed": len(route_rows),
            "mitigation_zones_across_routes": int(total_zones),
            "mitigation_capacity_m2_across_routes": total_capacity,
        },
        "routes": route_rows,
        "route_comparison": comparison,
        "mitigation": {
            "search_strategy": mitigation_result.get("search_strategy", {}),
            "intervention_rules": mitigation_result.get("intervention_rules", {}),
            "assumptions": mitigation_result.get("assumptions", {}),
            "routes": mitigation_routes,
        },
        "impact_assumptions": impact_result.get("assumptions", {}),
        "heat_method": heat_method,
        "project_inputs": {
            "softPreferences": project_payload.get("softPreferences", {}),
            "hardConstraints": project_payload.get("hardConstraints", {}),
        },
        "limitations": [
            "This is a planning-level spatial analysis, not an engineering design.",
            "Environmental Cost Index is a route-planning metric, not a monetary cost.",
            "Tree-equivalent canopy uses a planning assumption and is not an individual tree count.",
            "Mitigation capacity represents feasible spatial opportunity and is not an exact ecological or thermal equivalence.",
            "Green-roof capacity uses a regional average when detailed roof-area data is unavailable.",
            "Heat figures are modelled estimates of mid-morning summer surface temperature, not measurements and not air temperature.",
            "Tree planting is credited at mature canopy, which takes years to reach.",
            "Flood figures come from a screening index. No flood depth or drainage is modelled.",
        ],
    }


def render_report_html(report):
    rows = []
    for r in report.get("routes", []):
        rows.append(
            "<tr>"
            f"<td>{escape(str(r.get('route', '—')))}</td>"
            f"<td>{_fmt(r.get('length_km'), 2)}</td>"
            f"<td>{_fmt(r.get('green_area_m2'), 0)}</td>"
            f"<td>{_fmt(r.get('canopy_area_m2'), 0)}</td>"
            f"<td>{_fmt(r.get('water_area_m2'), 0)}</td>"
            f"<td>{_fmt(r.get('water_crossings'), 0)}</td>"
            f"<td>{_fmt(r.get('buildings_affected'), 0)}</td>"
            f"<td>{_fmt(r.get('heritage_conflicts'), 0)}</td>"
            f"<td>{_fmt(r.get('environmental_cost_index'), 0)}</td>"
            f"<td>{_fmt(r.get('mitigation_capacity_m2'), 0)}</td>"
            "</tr>"
        )

    heat_rows = []
    for r in report.get("routes", []):
        heat_rows.append(
            "<tr>"
            f"<td>{escape(str(r.get('route', '—')))}</td>"
            f"<td>{_fmt(r.get('tree_equivalent'), 0)}</td>"
            f"<td>{_fmt(r.get('corridor_change_c'), 2)}</td>"
            f"<td>{_fmt(r.get('heat_added_degree_ha'), 1)}</td>"
            f"<td>{_fmt(r.get('heat_repaid_pct'), 0)}</td>"
            f"<td>{_fmt(r.get('flood_prone_m2'), 0)}</td>"
            f"<td>{_fmt(r.get('lost_water_m2'), 0)}</td>"
            "</tr>"
        )

    heat_method = report.get("heat_method") or {}
    heat_note = (
        f"<p class=\"small\">{escape(str(heat_method.get('what', '')))} "
        f"Model error on parts of the district it was not trained on: "
        f"{_fmt(heat_method.get('held_out_error_c'), 2)} °C. "
        f"{escape(str(heat_method.get('degree_ha', '')))} "
        f"{escape(str(heat_method.get('tree_note', '')))}</p>"
        if heat_method
        else "<p class=\"small\">No thermal model covers this district yet.</p>"
    )

    mitigation_sections = []
    for route_name, route in report.get("mitigation", {}).get("routes", {}).items():
        zones = route.get("selected_zones", [])
        zone_rows = "".join(
            "<li>"
            f"<b>{escape(str(z.get('zone_id', 'Zone')))}</b> — "
            f"{escape(str(z.get('intervention', 'unknown')))}; "
            f"{_fmt(z.get('capacity_m2'), 0)} m²; "
            f"{_fmt(z.get('distance_m'), 0)} m from corridor"
            "</li>"
            for z in zones
        )
        mitigation_sections.append(
            f"<h3>{escape(str(route_name))}</h3>"
            f"<p>Search radius: {_fmt(route.get('search_radius_m'), 0)} m · "
            f"Selected zones: {len(zones)}</p>"
            f"<ul>{zone_rows or '<li>No zones selected</li>'}</ul>"
        )

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{escape(str(report.get('title', 'Shuhul Report')))}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 40px; color:#172033; line-height:1.5; }}
h1 {{ margin-bottom:4px; }}
h2 {{ margin-top:30px; }}
.meta {{ color:#5b6475; }}
table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:12px; }}
th,td {{ border:1px solid #d9dde5; padding:7px; text-align:left; }}
th {{ background:#f4f6f9; }}
.card {{ border:1px solid #d9dde5; border-radius:10px; padding:14px; margin:12px 0; }}
.small {{ font-size:12px; color:#626b7c; }}
@media print {{ body {{ margin:18px; }} }}
</style>
</head>
<body>
<h1>{escape(str(report.get('title', 'Shuhul Project Report')))}</h1>
<div class="meta">{escape(str(report.get('district', ''))).upper()} ·
{escape(str(report.get('construction', '')))} ·
{_fmt(report.get('project_width_m'), 1)} m project width</div>

<div class="card">
<b>Planning summary</b><br>
Routes analyzed: {report.get('summary', {}).get('routes_analyzed', 0)}<br>
Mitigation zones across routes: {report.get('summary', {}).get('mitigation_zones_across_routes', 0)}<br>
Total selected mitigation opportunity: {_fmt(report.get('summary', {}).get('mitigation_capacity_m2_across_routes'), 0)} m²
</div>

<h2>Route comparison</h2>
<table>
<thead><tr>
<th>Route</th><th>Length km</th><th>Green m²</th><th>Canopy m²</th>
<th>Water m²</th><th>Crossings</th><th>Buildings</th><th>Heritage</th>
<th>Env. Cost Index</th><th>Mitigation m²</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>

<h2>Heat and flood</h2>
<table>
<thead><tr>
<th>Route</th><th>Tree-equivalent canopy</th><th>Corridor temperature change °C</th>
<th>Heat added, degree-hectares</th><th>Repaid near the route %</th>
<th>Flood-prone land m²</th><th>Former water m²</th>
</tr></thead>
<tbody>{''.join(heat_rows)}</tbody>
</table>
{heat_note}

<h2>Mitigation recommendations</h2>
{''.join(mitigation_sections)}

<h2>Methodology and limitations</h2>
<ul>
{''.join(f"<li>{escape(str(x))}</li>" for x in report.get('limitations', []))}
</ul>
<p class="small">Generated by Shuhul. Results are intended to support early-stage spatial planning and comparison of alternatives.</p>
</body>
</html>"""
    return html


def write_report(report, output_dir: Path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"
    html_path = output_dir / "report.html"

    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    html_path.write_text(render_report_html(report), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "html_path": str(html_path),
        "report": report,
    }
