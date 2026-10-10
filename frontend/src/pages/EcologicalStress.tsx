import { useEffect, useMemo, useState } from "react";
import { geoJSON as leafletGeoJSON } from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { GeoJSON } from "react-leaflet";
import BaseMap, { FitBounds, ResizeWatcher } from "../components/BaseMap";
import DistrictSelect, { useDistricts } from "../components/DistrictSelect";
import { Panel, PanelSection, Stat, Tabs } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num } from "../lib/format";

type Level = "LOW" | "MODERATE" | "HIGH";

interface Zone {
  zone_id: string;
  stress_level: Level;
  stress_score: number;
  drivers: { key: string; label: string; score: number }[];
  indicator_scores: Record<string, number>;
  mean_ndvi: number | null;
  canopy_cover_pct: number | null;
  built_up_density_pct: number | null;
  mean_lst: number | null;
  main_road_pct: number | null;
  greening_priority: number | null;
  greening_level: Level | "NOT_APPLICABLE";
  greening_rank: number | null;
  greening_factors: Record<string, number>;
  greening_reasons: string[];
  education_buildings: number;
  health_buildings: number;
  sensitive_names: string[];
}

interface StressData extends GeoJSON.FeatureCollection {
  methodology: { weights: Record<string, number>; normalization: string };
  greening: {
    available: boolean;
    unavailable_reason: string | null;
    zones_ranked: number;
    weights: Record<string, number>;
    labels: Record<string, string>;
    scoring: string;
    levels: string;
    left_out: string;
    air_note: string;
    sensitive_note: string;
    confidence: string;
  };
}

interface DistrictAir {
  air: { annual_mean_pm2_5?: number | null; days_over_standard?: number; days_with_data?: number } | null;
}

type View = "stress" | "greening";

const LEVEL_NAMES: Record<Level, string> = { LOW: "Low", MODERATE: "Moderate", HIGH: "High" };

// Stress uses the warning colours. Greening priority is one hue, light to
// dark, so the two maps cannot be mistaken for each other.
const COLORS: Record<View, Record<string, string>> = {
  stress: { LOW: "#5f9b6b", MODERATE: "#d9a441", HIGH: "#c0563a" },
  greening: { LOW: "#d5e6cb", MODERATE: "#7fb089", HIGH: "#1c5a3c", NOT_APPLICABLE: "#b9c0bb" },
};

const INDICATORS: Record<string, string> = {
  lst: "Surface temperature",
  ndvi: "Vegetation",
  canopy: "Tree canopy",
  buildings: "Built-up density",
  ndwi: "Surface moisture",
};

const TOP_ZONES = 8;

function hasSensitiveSite(zone: Zone): boolean {
  return zone.education_buildings + zone.health_buildings > 0;
}

// "2 school or college buildings, 1 hospital or clinic building: Name, Name"
function sitesText(zone: Zone): string {
  const parts: string[] = [];
  if (zone.education_buildings) {
    parts.push(`${zone.education_buildings} school or college building${zone.education_buildings === 1 ? "" : "s"}`);
  }
  if (zone.health_buildings) {
    parts.push(`${zone.health_buildings} hospital or clinic building${zone.health_buildings === 1 ? "" : "s"}`);
  }
  const names = zone.sensitive_names.length ? `: ${zone.sensitive_names.join(", ")}` : "";
  return parts.join(", ") + names;
}

// ["Little tree canopy", "Hot surface"] -> "Little tree canopy, hot surface"
function asSentence(reasons: string[]): string {
  const text = reasons.join(", ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export default function EcologicalStress() {
  const districts = useDistricts();
  const [district, setDistrict] = useState("sr-c");
  const [view, setView] = useState<View>("stress");
  const [data, setData] = useState<StressData | null>(null);
  const [air, setAir] = useState<DistrictAir["air"]>(null);
  const [error, setError] = useState("");
  const [level, setLevel] = useState<Level | null>(null);
  const [picked, setPicked] = useState<Zone | null>(null);
  const [sitesOnly, setSitesOnly] = useState(false);

  useEffect(() => {
    setData(null);
    setAir(null);
    setPicked(null);
    setError("");

    api<StressData>(`/api/stress/${district}`)
      .then(setData)
      .catch((problem) => setError(errorMessage(problem, "Could not load ecological stress.")));

    api<DistrictAir>(`/api/climate/${district}`)
      .then((climate) => setAir(climate.air))
      .catch(() => setAir(null));
  }, [district]);

  const levelOf = (zone: Zone) => (view === "stress" ? zone.stress_level : zone.greening_level);

  const zones = useMemo(() => (data?.features || []).map((feature) => feature.properties as Zone), [data]);

  const shown = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!data) return null;
    return {
      type: "FeatureCollection",
      features: data.features.filter((feature) => {
        const zone = feature.properties as Zone;
        if (level && levelOf(zone) !== level) return false;
        return !(view === "greening" && sitesOnly) || hasSensitiveSite(zone);
      }),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, level, view, sitesOnly]);

  const bounds = useMemo<LatLngBoundsExpression | null>(
    () => (data && data.features.length ? leafletGeoJSON(data).getBounds() : null),
    [data]
  );

  const counts = useMemo(() => {
    const result: Record<string, number> = { LOW: 0, MODERATE: 0, HIGH: 0 };
    zones.forEach((zone) => {
      const key = levelOf(zone);
      if (key in result) result[key] += 1;
    });
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zones, view]);

  // What most often pushes a zone into stress in this district.
  const leading = useMemo(() => {
    const result: Record<string, number> = {};
    zones.forEach((zone) => {
      const first = zone.drivers[0];
      if (first) result[first.label] = (result[first.label] || 0) + 1;
    });
    return Object.entries(result).sort((a, b) => b[1] - a[1]);
  }, [zones]);

  const topZones = useMemo(
    () =>
      zones
        .filter((zone) => zone.greening_rank !== null && (!sitesOnly || hasSensitiveSite(zone)))
        .sort((a, b) => (a.greening_rank as number) - (b.greening_rank as number))
        .slice(0, TOP_ZONES),
    [zones, sitesOnly]
  );

  const zonesWithSites = useMemo(
    () => zones.filter((zone) => zone.greening_rank !== null && hasSensitiveSite(zone)).length,
    [zones]
  );

  const greening = data?.greening;
  const colors = COLORS[view];

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Ecological stress</h1>
        <span className="page-sub">
          {view === "stress" ? "Where pressure is already high, and why" : "Where planting would do the most good"}
        </span>
      </div>

      <div className="split">
        <div className="map-card">
          <BaseMap>
            <ResizeWatcher />
            <FitBounds bounds={bounds} />
            {shown && (
              <GeoJSON
                key={`${district}-${view}-${level}-${sitesOnly}-${picked?.zone_id}`}
                data={shown}
                style={(feature) => {
                  const zone = feature?.properties as Zone;
                  const chosen = picked?.zone_id === zone.zone_id;
                  return {
                    color: "#142a28",
                    weight: chosen ? 3 : 0.4,
                    fillColor: colors[levelOf(zone)],
                    fillOpacity: levelOf(zone) === "NOT_APPLICABLE" ? 0.25 : 0.66,
                  };
                }}
                onEachFeature={(feature, layer) => {
                  layer.on("click", () => setPicked(feature.properties as Zone));
                }}
              />
            )}
          </BaseMap>

          <div className="map-overlay is-bottom-left">
            <div className="legend-title">{view === "stress" ? "Stress level" : "Greening priority"}</div>
            {(["HIGH", "MODERATE", "LOW"] as Level[]).map((key) => (
              <div className="legend-item" key={key}>
                <span className="swatch" style={{ background: colors[key] }} />
                {LEVEL_NAMES[key]}
              </div>
            ))}
            {view === "greening" && (
              <div className="legend-item">
                <span className="swatch" style={{ background: colors.NOT_APPLICABLE }} />
                Mostly water, not ranked
              </div>
            )}
          </div>
        </div>

        <Panel className="side">
          <Tabs<View>
            active={view}
            onChange={(next) => {
              setView(next);
              setLevel(null);
            }}
            tabs={[
              { id: "stress", label: "Stress" },
              { id: "greening", label: "Greening priority" },
            ]}
          />

          <DistrictSelect districts={districts} value={district} onChange={setDistrict} />

          {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
          {!data && !error && <p className="note" style={{ marginTop: 14 }}>Working out the zones...</p>}

          {data && view === "greening" && !greening?.available && (
            <p className="message" style={{ marginTop: 14 }}>
              Greening priority is not available here. {greening?.unavailable_reason}
            </p>
          )}

          {data && (view === "stress" || greening?.available) && (
            <PanelSection heading="Zones by level">
              <div className="chip-row">
                {(["HIGH", "MODERATE", "LOW"] as Level[]).map((key) => (
                  <button
                    key={key}
                    type="button"
                    className="chip"
                    aria-pressed={level === key}
                    onClick={() => setLevel(level === key ? null : key)}
                  >
                    <span className="dot" style={{ background: colors[key] }} />
                    {LEVEL_NAMES[key]} ({counts[key]})
                  </button>
                ))}
              </div>
              <p className="field-hint">Each zone is a 500 m square. Select a level to show only those zones.</p>

              {view === "greening" && zonesWithSites > 0 && (
                <div className="chip-row" style={{ marginTop: 10 }}>
                  <button
                    type="button"
                    className="chip"
                    aria-pressed={sitesOnly}
                    onClick={() => setSitesOnly(!sitesOnly)}
                  >
                    With a school or hospital ({zonesWithSites})
                  </button>
                </div>
              )}
            </PanelSection>
          )}

          {/* ---------- Stress ---------- */}
          {data && view === "stress" && (
            <>
              <PanelSection heading={picked ? picked.zone_id : "Select a zone on the map"}>
                {picked ? (
                  <>
                    <p style={{ marginBottom: 10 }}>
                      <span className={`badge is-${picked.stress_level.toLowerCase()}`}>
                        {LEVEL_NAMES[picked.stress_level]} stress
                      </span>{" "}
                      score {num(picked.stress_score, 2)} of 1
                    </p>

                    {picked.drivers.length > 0 && (
                      <p style={{ marginBottom: 12 }}>
                        Main drivers: {picked.drivers.map((driver) => driver.label.toLowerCase()).join(", ")}.
                      </p>
                    )}

                    <div className="stat-grid">
                      <Stat label="Surface temp." value={picked.mean_lst === null ? "—" : `${num(picked.mean_lst, 1)} °C`} />
                      <Stat label="Tree canopy" value={`${num(picked.canopy_cover_pct, 1)}%`} />
                      <Stat label="Under roofs" value={`${num(picked.built_up_density_pct, 1)}%`} />
                      <Stat label="Vegetation" value={num(picked.mean_ndvi, 2)} note="NDVI" />
                    </div>

                    <table className="table" style={{ marginTop: 12 }}>
                      <thead>
                        <tr><th>Indicator</th><th>Stress, 0 to 1</th><th>Weight</th></tr>
                      </thead>
                      <tbody>
                        {Object.entries(picked.indicator_scores).map(([key, score]) => (
                          <tr key={key}>
                            <td>{INDICATORS[key] || key}</td>
                            <td>{num(score, 2)}</td>
                            <td>{num((data.methodology.weights[key] || 0) * 100)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <p className="note">A zone shows its score, what drives it and the values behind it.</p>
                )}
              </PanelSection>

              <PanelSection heading="What drives stress here">
                {leading.map(([label, count]) => (
                  <p key={label} style={{ fontSize: 14 }}>
                    {label}: leading driver in {count} zones
                  </p>
                ))}
                <p className="note" style={{ marginTop: 10 }}>
                  Each indicator is scaled against the rest of the district, between its 10th and 90th
                  percentiles, then combined by fixed weights, shown when a zone is selected. This is a
                  screening index for comparing places inside one district, not an absolute measure.
                </p>
              </PanelSection>
            </>
          )}

          {/* ---------- Greening priority ---------- */}
          {data && view === "greening" && greening?.available && (
            <>
              <PanelSection heading={picked ? picked.zone_id : "Highest-ranked zones"}>
                {picked ? (
                  picked.greening_rank === null ? (
                    <p className="note">This zone is mostly water, so it is not ranked for planting.</p>
                  ) : (
                    <>
                      <p style={{ marginBottom: 10 }}>
                        Ranked <b>{picked.greening_rank}</b> of {greening.zones_ranked}, score{" "}
                        {num(picked.greening_priority, 2)} of 1
                      </p>

                      {picked.greening_reasons.length > 0 && (
                        <p style={{ marginBottom: 12 }}>Why: {picked.greening_reasons.join(", ").toLowerCase()}.</p>
                      )}
                      {hasSensitiveSite(picked) && <p style={{ marginBottom: 12 }}>Here: {sitesText(picked)}.</p>}

                      <div className="stat-grid">
                        <Stat label="Tree canopy" value={`${num(picked.canopy_cover_pct, 1)}%`} />
                        <Stat label="Surface temp." value={picked.mean_lst === null ? "—" : `${num(picked.mean_lst, 1)} °C`} />
                        <Stat label="Main roads" value={`${num(picked.main_road_pct, 1)}%`} note="Share of the zone" />
                        <Stat label="Under roofs" value={`${num(picked.built_up_density_pct, 1)}%`} />
                      </div>

                      <table className="table" style={{ marginTop: 12 }}>
                        <thead>
                          <tr><th>Factor</th><th>Standing, 0 to 1</th><th>Weight</th></tr>
                        </thead>
                        <tbody>
                          {Object.entries(picked.greening_factors).map(([key, value]) => (
                            <tr key={key}>
                              <td>{greening.labels[key] || key}</td>
                              <td>{num(value, 2)}</td>
                              <td>{num((greening.weights[key] || 0) * 100)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>

                      <button className="link-btn" style={{ marginTop: 10, fontSize: 13 }} onClick={() => setPicked(null)}>
                        Back to the highest-ranked zones
                      </button>
                    </>
                  )
                ) : (
                  <>
                    {topZones.map((zone) => (
                      <div className="report-item" key={zone.zone_id}>
                        <button className="link-btn" onClick={() => setPicked(zone)}>
                          {zone.greening_rank}. {zone.zone_id}
                        </button>
                        <p className="note">
                          {asSentence(zone.greening_reasons) || "No single factor stands out"}. Canopy{" "}
                          {num(zone.canopy_cover_pct, 1)}%, surface {num(zone.mean_lst, 1)} °C.
                          {hasSensitiveSite(zone) && ` Here: ${sitesText(zone)}.`}
                        </p>
                      </div>
                    ))}
                    <p className="field-hint">Select a zone here or on the map to see what sets its rank.</p>
                  </>
                )}
              </PanelSection>

              <PanelSection heading="Air">
                {air?.annual_mean_pm2_5 != null && (
                  <p style={{ fontSize: 14, marginBottom: 8 }}>
                    District air, past year: <b>{num(air.annual_mean_pm2_5, 0)} µg/m³</b> of fine particles on
                    average, over the daily standard on {num(air.days_over_standard)} of {num(air.days_with_data)} days.
                  </p>
                )}
                <p className="note">{greening.air_note}</p>
              </PanelSection>

              <PanelSection heading="Schools and hospitals">
                <p className="note">
                  Heat matters more where children and patients are. {greening.sensitive_note} They do not
                  change a zone's rank; use the filter above to see the ranked zones that have one.
                </p>
              </PanelSection>

              <PanelSection heading="How zones are ranked">
                <p className="note">
                  {greening.scoring} {greening.levels} Left out: {greening.left_out.toLowerCase()} A high rank
                  says a zone needs planting more than others in this district. It does not say land is free
                  to plant. Confidence: {greening.confidence.toLowerCase()}
                </p>
              </PanelSection>
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
