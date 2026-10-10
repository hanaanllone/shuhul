import { useEffect, useMemo, useState } from "react";
import { geoJSON as leafletGeoJSON } from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { GeoJSON } from "react-leaflet";
import BaseMap, { FitBounds, ResizeWatcher } from "../components/BaseMap";
import DistrictSelect, { useDistricts } from "../components/DistrictSelect";
import { CheckField, Panel, PanelSection, SliderField, Stat } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num } from "../lib/format";

type Level = "GOOD" | "FAIR" | "POOR" | "RULED_OUT";

interface Zone {
  zone_id: string;
  site_level: Level;
  site_score: number | null;
  site_rank: number | null;
  site_factors: Record<string, number>;
  site_reasons: string[];
  site_ruled_out: string | null;
  open_land_ha: number | null;
  canopy_cover_pct: number | null;
  flood_prone_pct: number | null;
  warming_if_paved_c: number | null;
  mean_slope_deg: number | null;
  road_pct: number | null;
}

interface Sites extends GeoJSON.FeatureCollection {
  zones_ranked: number;
  method: {
    weights: Record<string, number>;
    labels: Record<string, string>;
    scoring: string;
    levels: string;
    always_left_out: string;
    open_land: string;
    confidence: string;
  };
}

// One hue, light to dark, so this map is not mistaken for the stress map.
const COLORS: Record<Level, string> = {
  GOOD: "#1d5c63",
  FAIR: "#7fb3ad",
  POOR: "#c5d8d0",
  RULED_OUT: "#b9c0bb",
};

const NAMES: Record<Level, string> = {
  GOOD: "Good",
  FAIR: "Fair",
  POOR: "Poor",
  RULED_OUT: "Ruled out",
};

const TOP_ZONES = 8;

function asSentence(reasons: string[]): string {
  const text = reasons.join(", ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export default function SiteFinder() {
  const districts = useDistricts();
  const [district, setDistrict] = useState("sr-c");
  const [minHa, setMinHa] = useState(2);
  const [needRoad, setNeedRoad] = useState(true);
  const [avoidFlood, setAvoidFlood] = useState(true);

  const [data, setData] = useState<Sites | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Zone | null>(null);

  useEffect(() => {
    setBusy(true);
    setError("");
    setPicked(null);

    // Wait for the slider to settle before asking.
    const timer = window.setTimeout(() => {
      api<Sites>(`/api/sites/${district}?min_ha=${minHa}&road=${needRoad ? 1 : 0}&flood=${avoidFlood ? 1 : 0}`)
        .then(setData)
        .catch((problem) => {
          setData(null);
          setError(errorMessage(problem, "Could not look for sites."));
        })
        .finally(() => setBusy(false));
    }, 350);

    return () => window.clearTimeout(timer);
  }, [district, minHa, needRoad, avoidFlood]);

  const zones = useMemo(() => (data?.features || []).map((feature) => feature.properties as Zone), [data]);

  const bounds = useMemo<LatLngBoundsExpression | null>(
    () => (data && data.features.length ? leafletGeoJSON(data).getBounds() : null),
    // Only when the district changes, so the map does not jump on every filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data?.features.length, district]
  );

  const counts = useMemo(() => {
    const result: Record<Level, number> = { GOOD: 0, FAIR: 0, POOR: 0, RULED_OUT: 0 };
    zones.forEach((zone) => {
      result[zone.site_level] += 1;
    });
    return result;
  }, [zones]);

  const top = useMemo(
    () =>
      zones
        .filter((zone) => zone.site_rank !== null)
        .sort((a, b) => (a.site_rank as number) - (b.site_rank as number))
        .slice(0, TOP_ZONES),
    [zones]
  );

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Where to build</h1>
        <span className="page-sub">Land that would cost the least to build on</span>
      </div>

      <div className="split">
        <div className="map-card">
          <BaseMap>
            <ResizeWatcher />
            <FitBounds bounds={bounds} />
            {data && (
              <GeoJSON
                key={`${district}-${minHa}-${needRoad}-${avoidFlood}-${picked?.zone_id}`}
                data={data}
                style={(feature) => {
                  const zone = feature?.properties as Zone;
                  const chosen = picked?.zone_id === zone.zone_id;
                  return {
                    color: "#142a28",
                    weight: chosen ? 3 : 0.4,
                    fillColor: COLORS[zone.site_level],
                    fillOpacity: zone.site_level === "RULED_OUT" ? 0.08 : 0.72,
                  };
                }}
                onEachFeature={(feature, layer) => {
                  layer.on("click", () => setPicked(feature.properties as Zone));
                }}
              />
            )}
          </BaseMap>

          <div className="map-overlay is-bottom-left">
            <div className="legend-title">Place to build</div>
            {(["GOOD", "FAIR", "POOR", "RULED_OUT"] as Level[]).map((key) => (
              <div className="legend-item" key={key}>
                <span className="swatch" style={{ background: COLORS[key] }} />
                {NAMES[key]}
              </div>
            ))}
          </div>
        </div>

        <Panel className="side" title="Where to build">
          <DistrictSelect districts={districts} value={district} onChange={setDistrict} />

          <PanelSection heading="What the project needs">
            <SliderField label="Open land" value={minHa} min={1} max={15} step={1} unit=" ha" onChange={setMinHa} />
            <CheckField
              label="A road in the zone"
              hint="Any motorable road, so the site can be reached"
              checked={needRoad}
              onChange={setNeedRoad}
            />
            <CheckField
              label="Stay off flood-prone land"
              hint="Leaves out zones where half or more is flood-prone"
              checked={avoidFlood}
              onChange={setAvoidFlood}
            />
          </PanelSection>

          {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
          {busy && !data && <p className="note" style={{ marginTop: 14 }}>Looking...</p>}

          {data && (
            <>
              <PanelSection heading={`${num(data.zones_ranked)} zones qualify`}>
                <p className="note">
                  {num(counts.GOOD)} good, {num(counts.FAIR)} fair, {num(counts.POOR)} poor.{" "}
                  {num(counts.RULED_OUT)} ruled out. Each zone is a 500 m square.
                </p>
              </PanelSection>

              <PanelSection heading={picked ? picked.zone_id : "Best places to look"}>
                {picked ? (
                  <>
                    {picked.site_rank === null ? (
                      <p style={{ marginBottom: 12 }}>Ruled out: {picked.site_ruled_out?.toLowerCase()}.</p>
                    ) : (
                      <>
                        <p style={{ marginBottom: 10 }}>
                          Ranked <b>{picked.site_rank}</b> of {data.zones_ranked}, score {num(picked.site_score, 2)} of 1
                        </p>
                        {picked.site_reasons.length > 0 && (
                          <p style={{ marginBottom: 12 }}>Why: {picked.site_reasons.join(", ").toLowerCase()}.</p>
                        )}
                      </>
                    )}

                    <div className="stat-grid">
                      <Stat label="Open land" value={`${num(picked.open_land_ha, 1)} ha`} />
                      <Stat label="Tree canopy" value={`${num(picked.canopy_cover_pct, 1)}%`} />
                      <Stat label="Flood-prone" value={`${num(picked.flood_prone_pct, 0)}%`} />
                      <Stat label="Warming if paved" value={`${num(picked.warming_if_paved_c, 2)} °C`} />
                      <Stat label="Slope" value={`${num(picked.mean_slope_deg, 1)}°`} />
                      <Stat label="Under roads" value={`${num(picked.road_pct, 1)}%`} />
                    </div>

                    {picked.site_rank !== null && (
                      <table className="table" style={{ marginTop: 12 }}>
                        <thead>
                          <tr><th>Factor</th><th>Standing, 0 to 1</th><th>Weight</th></tr>
                        </thead>
                        <tbody>
                          {Object.entries(picked.site_factors).map(([key, value]) => (
                            <tr key={key}>
                              <td>{data.method.labels[key] || key}</td>
                              <td>{num(value, 2)}</td>
                              <td>{num((data.method.weights[key] || 0) * 100)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}

                    <button className="link-btn" style={{ marginTop: 10, fontSize: 13 }} onClick={() => setPicked(null)}>
                      Back to the best places
                    </button>
                  </>
                ) : top.length === 0 ? (
                  <p className="note">No zone meets these needs. Ask for less open land or lift a condition.</p>
                ) : (
                  <>
                    {top.map((zone) => (
                      <div className="report-item" key={zone.zone_id}>
                        <button className="link-btn" onClick={() => setPicked(zone)}>
                          {zone.site_rank}. {zone.zone_id}
                        </button>
                        <p className="note">
                          {asSentence(zone.site_reasons) || "No single factor stands out"}. Open land{" "}
                          {num(zone.open_land_ha, 1)} ha, canopy {num(zone.canopy_cover_pct, 1)}%.
                        </p>
                      </div>
                    ))}
                    <p className="field-hint">Select a zone here or on the map to see what sets its rank.</p>
                  </>
                )}
              </PanelSection>

              <PanelSection heading="How zones are ranked">
                <p className="note">
                  {data.method.scoring} {data.method.levels} Always left out: {data.method.always_left_out.toLowerCase()}{" "}
                  {data.method.open_land} Confidence: {data.method.confidence.toLowerCase()}
                </p>
              </PanelSection>
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
