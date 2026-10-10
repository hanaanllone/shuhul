// What the planner reads once routes exist: the alternatives side by
// side, the heat and flood picture for one route, and what it owes.

import { PanelSection, Stat } from "../../components/ui";
import { apiUrl } from "../../lib/api";
import { ROUTE_COLORS, area, num, routeParts, signed, withUnit } from "../../lib/format";
import type { ProjectResult, RouteImpact } from "../../lib/types";
import { INTERVENTIONS } from "./PlannerMap";

interface RouteProps {
  result: ProjectResult;
  selected: string | null;
}

function impacts(result: ProjectResult): [string, RouteImpact][] {
  return Object.entries(result.impact?.routes || {});
}

// ---------- Routes ----------

const COMPARISON: [string, (route: RouteImpact) => string][] = [
  ["Length", (route) => withUnit(route.route_length_km, "km", 2)],
  ["Tree-equivalents", (route) => num(route.canopy?.estimated_tree_equivalent)],
  ["Green space", (route) => area(route.green_space?.green_area_m2)],
  ["Water crossings", (route) => num(route.water?.estimated_crossings)],
  ["Named buildings", (route) => num(route.buildings?.count)],
  ["Heritage sites", (route) => num(route.heritage?.count)],
  ["Mean slope", (route) => withUnit(route.slope?.mean_slope_deg, "°", 1)],
  ["Heat added", (route) => withUnit(route.heat?.heat_added_degree_ha, "°C·ha", 1)],
  ["Flood-prone land", (route) => area(route.flood?.flood_prone_m2)],
  ["Environmental cost", (route) => num(route.environmental_cost?.environmental_cost_index)],
];

interface RoutesProps extends RouteProps {
  onSelect: (name: string) => void;
}

export function RoutesPanel({ result, selected, onSelect }: RoutesProps) {
  const routes = impacts(result);

  return (
    <>
      <PanelSection heading="Alternatives">
        {routes.map(([name, route]) => {
          const { letter, label } = routeParts(name);

          return (
            <button
              key={name}
              type="button"
              className="route-card"
              aria-pressed={selected === name}
              onClick={() => onSelect(name)}
            >
              <span className="route-card-head">
                <span className="route-letter" style={{ background: ROUTE_COLORS[letter] }}>{letter}</span>
                {label}
              </span>
              <span className="route-facts">
                <span><b>{num(route.route_length_km, 2)}</b>km</span>
                <span><b>{num(route.canopy?.estimated_tree_equivalent)}</b>tree-equivalents</span>
                <span><b>{num(route.heat?.heat_added_degree_ha, 1)}</b>°C·ha heat</span>
              </span>
            </button>
          );
        })}
        <p className="field-hint">
          The routes are alternatives, not a ranking. Select one to see it on the map and in the other tabs.
        </p>
      </PanelSection>

      <PanelSection heading="Side by side">
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th />
                {routes.map(([name]) => <th key={name}>{routeParts(name).letter}</th>)}
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map(([label, read]) => (
                <tr key={label}>
                  <td>{label}</td>
                  {routes.map(([name, route]) => <td key={name}>{read(route)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </PanelSection>

      <PanelSection>
        <a
          className="btn is-dark is-block"
          href={apiUrl(`/api/projects/${result.projectId}/report`)}
          target="_blank"
          rel="noreferrer"
        >
          Open the report
        </a>
        <p className="field-hint">Opens in a new tab. Print it to save a PDF.</p>
      </PanelSection>
    </>
  );
}

// ---------- Heat and flood ----------

const SCENARIOS: [string, string][] = [
  ["existing", "Today"],
  ["after_construction", "After building"],
  ["after_mitigation", "After mitigation"],
];

export function HeatPanel({ result, selected }: RouteProps) {
  const route = result.impact?.routes?.[selected || ""];
  if (!route) return <p className="note">Select a route to see its heat and flood picture.</p>;

  const heat = route.heat;
  const flood = route.flood;

  return (
    <>
      <PanelSection heading={`Heat along route ${routeParts(selected || "").letter}`}>
        {!heat?.available ? (
          <p className="note">No thermal model covers this district yet.</p>
        ) : (
          <>
            <div className="scenario-row">
              {SCENARIOS.map(([key, label]) => {
                const zone = heat.scenarios?.[key]?.footprint;
                return (
                  <Stat
                    key={key}
                    label={label}
                    value={zone ? withUnit(zone.estimated_lst_c, "°C", 1) : "—"}
                    note={zone ? `Canopy ${num(zone.canopy_pct, 1)}%` : "No mitigation found"}
                  />
                );
              })}
            </div>

            <div className="stat-grid" style={{ marginTop: 12 }}>
              <Stat label="Corridor warming" value={`${signed(heat.corridor_change_c)} °C`} />
              <Stat
                label="Heat added"
                value={withUnit(heat.heat_added_degree_ha, "°C·ha", 1)}
                note={`Within ${heat.impact_zone_m} m of the route`}
              />
              <Stat
                label="Repaid nearby"
                value={heat.heat_repaid_pct === null || heat.heat_repaid_pct === undefined ? "—" : `${num(heat.heat_repaid_pct)}%`}
                note="By the mitigation plan"
              />
            </div>

            <p className="note" style={{ marginTop: 12 }}>
              {heat.method?.what} Model error on parts of the district it was not trained on:{" "}
              {heat.method?.held_out_error_c} °C. {heat.method?.degree_ha} {heat.method?.tree_note}
            </p>
          </>
        )}
      </PanelSection>

      <PanelSection heading="Flood">
        {!flood?.available ? (
          <p className="note">No flood layer for this district yet.</p>
        ) : (
          <>
            <div className="stat-grid">
              <Stat
                label="Flood-prone land"
                value={area(flood.flood_prone_m2)}
                note={flood.flood_prone_pct === null ? undefined : `${num(flood.flood_prone_pct)}% of the corridor`}
              />
              <Stat label="Water recorded here" value={area(flood.recorded_water_m2)} note="At some time since 1984" />
              <Stat label="Former water" value={area(flood.lost_water_m2)} note="Now mapped as land" />
            </div>
            <p className="note" style={{ marginTop: 12 }}>{flood.note} Confidence: low.</p>
          </>
        )}
      </PanelSection>
    </>
  );
}

// ---------- Mitigation ----------

const PLAN_STATUS: Record<string, string> = {
  sized_to_canopy: "The plan covers twice the canopy removed, and that repays the added heat.",
  heat_repaid: "The plan was grown beyond twice the canopy until the added heat was repaid.",
  grown_for_heat: "The plan was grown for heat and stopped at its limit.",
  nearby_land_used_up: "Suitable land near the route ran out before the added heat was repaid.",
  no_zones: "No suitable land for green infrastructure was found near this route.",
};

export function MitigationPanel({ result, selected }: RouteProps) {
  const plan = result.impact?.routes?.[selected || ""]?.mitigation_plan;
  if (!plan) return <p className="note">Select a route to see what it owes.</p>;

  return (
    <>
      <PanelSection heading={`What route ${routeParts(selected || "").letter} owes`}>
        <p style={{ marginBottom: 12 }}>{PLAN_STATUS[plan.status] || plan.status}</p>

        <div className="stat-grid">
          <Stat label="Canopy removed" value={area(plan.canopy_removed_m2)} />
          <Stat label="Owed" value={area(plan.canopy_owed_m2)} note={`${plan.canopy_ratio} for 1`} />
          <Stat label="Planned" value={area(plan.allocated_m2)} note={`of ${area(plan.available_nearby_m2)} found`} />
          <Stat
            label="Heat repaid"
            value={plan.heat_repaid_pct === null || plan.heat_repaid_pct === undefined ? "—" : `${num(plan.heat_repaid_pct)}%`}
          />
        </div>
      </PanelSection>

      <PanelSection heading="Where">
        {plan.zones.length === 0 ? (
          <p className="note">Nothing to list.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr><th>Zone</th><th>Type</th><th>Planned</th><th>Available</th></tr>
              </thead>
              <tbody>
                {plan.zones.map((zone) => (
                  <tr key={zone.zone_id}>
                    <td>{zone.zone_id.replace("Zone ", "")}</td>
                    <td>
                      <span className="dot" style={{ background: INTERVENTIONS[zone.intervention]?.color, marginRight: 6 }} />
                      {INTERVENTIONS[zone.intervention]?.label || zone.intervention}
                    </td>
                    <td>{area(zone.allocated_m2)}</td>
                    <td>{area(zone.available_m2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="note" style={{ marginTop: 12 }}>
          {plan.note} A zone here means the land looks suitable from the data. It does not mean the land
          is available: ownership and permissions have to be checked.
        </p>
      </PanelSection>
    </>
  );
}

// ---------- Method ----------

const FACTOR_LABELS: Record<string, string> = {
  slope: "Slope",
  ndvi: "Vegetation",
  water: "Water",
  canopy: "Tree canopy",
  buildings: "Buildings",
  roads: "Existing roads",
  heritage: "Heritage",
  heat: "Warming if paved",
  flood: "Flood susceptibility",
};

export function MethodPanel({ result }: { result: ProjectResult }) {
  const weights = Object.entries(result.costSurface?.weights || {}).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <PanelSection heading="How the routes were weighed">
        <p className="note" style={{ marginBottom: 10 }}>
          Each cell of the map gets an environmental cost from the factors below, in these shares for
          this project. Route A ignores it, route B balances it against distance, route C follows it.
        </p>
        <table className="table">
          <tbody>
            {weights.map(([key, weight]) => (
              <tr key={key}>
                <td>{FACTOR_LABELS[key] || key}</td>
                <td>{num(weight * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </PanelSection>

      <PanelSection heading="What the numbers are">
        <p className="note">
          Tree-equivalents turn canopy area into a familiar unit at 25 m² a tree; they are not a tree
          count. Environmental cost is a relative score, not money. Heat figures are modelled, flood
          figures are a screening index, and building counts cover named buildings only.
        </p>
      </PanelSection>
    </>
  );
}
