import { useEffect, useMemo, useState } from "react";
import { geoJSON as leafletGeoJSON } from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { GeoJSON } from "react-leaflet";
import BaseMap, { FitBounds, ResizeWatcher } from "../components/BaseMap";
import DistrictSelect, { useDistricts } from "../components/DistrictSelect";
import { Panel, PanelSection, Stat } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num } from "../lib/format";

interface Zone {
  zone_id: string;
  stress_level: "LOW" | "MODERATE" | "HIGH";
  stress_score: number;
  drivers: { key: string; label: string; score: number }[];
  indicator_scores: Record<string, number>;
  mean_ndvi: number | null;
  canopy_cover_pct: number | null;
  built_up_density_pct: number | null;
  mean_lst: number | null;
}

interface StressData extends GeoJSON.FeatureCollection {
  methodology: { weights: Record<string, number>; normalization: string };
}

const LEVELS: Record<string, { label: string; color: string }> = {
  LOW: { label: "Low", color: "#5f9b6b" },
  MODERATE: { label: "Moderate", color: "#d9a441" },
  HIGH: { label: "High", color: "#c0563a" },
};

const INDICATORS: Record<string, string> = {
  lst: "Surface temperature",
  ndvi: "Vegetation",
  canopy: "Tree canopy",
  buildings: "Built-up density",
  ndwi: "Surface moisture",
};

export default function EcologicalStress() {
  const districts = useDistricts();
  const [district, setDistrict] = useState("sr-c");
  const [data, setData] = useState<StressData | null>(null);
  const [error, setError] = useState("");
  const [level, setLevel] = useState<string | null>(null);
  const [picked, setPicked] = useState<Zone | null>(null);

  useEffect(() => {
    setData(null);
    setPicked(null);
    setError("");

    api<StressData>(`/api/stress/${district}`)
      .then(setData)
      .catch((problem) => setError(errorMessage(problem, "Could not load ecological stress.")));
  }, [district]);

  const zones = useMemo(() => (data?.features || []).map((feature) => feature.properties as Zone), [data]);

  const shown = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!data) return null;
    return {
      type: "FeatureCollection",
      features: data.features.filter((feature) => !level || feature.properties?.stress_level === level),
    };
  }, [data, level]);

  const bounds = useMemo<LatLngBoundsExpression | null>(
    () => (data && data.features.length ? leafletGeoJSON(data).getBounds() : null),
    [data]
  );

  const counts = useMemo(() => {
    const result: Record<string, number> = { LOW: 0, MODERATE: 0, HIGH: 0 };
    zones.forEach((zone) => {
      result[zone.stress_level] += 1;
    });
    return result;
  }, [zones]);

  // What most often pushes a zone into stress in this district.
  const leading = useMemo(() => {
    const result: Record<string, number> = {};
    zones.forEach((zone) => {
      const first = zone.drivers[0];
      if (first) result[first.label] = (result[first.label] || 0) + 1;
    });
    return Object.entries(result).sort((a, b) => b[1] - a[1]);
  }, [zones]);

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Ecological stress</h1>
        <span className="page-sub">Where pressure is already high, and why</span>
      </div>

      <div className="split">
        <div className="map-card">
          <BaseMap>
            <ResizeWatcher />
            <FitBounds bounds={bounds} />
            {shown && (
              <GeoJSON
                key={`${district}-${level}`}
                data={shown}
                style={(feature) => ({
                  color: "#142a28",
                  weight: 0.4,
                  fillColor: LEVELS[feature?.properties?.stress_level]?.color,
                  fillOpacity: 0.62,
                })}
                onEachFeature={(feature, layer) => {
                  layer.on("click", () => setPicked(feature.properties as Zone));
                }}
              />
            )}
          </BaseMap>

          <div className="map-overlay is-bottom-left">
            <div className="legend-title">Stress level</div>
            {Object.entries(LEVELS).map(([key, value]) => (
              <div className="legend-item" key={key}>
                <span className="swatch" style={{ background: value.color }} />
                {value.label}
              </div>
            ))}
          </div>
        </div>

        <Panel className="side" title="Ecological stress">
          <DistrictSelect districts={districts} value={district} onChange={setDistrict} />

          {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
          {!data && !error && <p className="note" style={{ marginTop: 14 }}>Working out stress zones...</p>}

          {data && (
            <>
              <PanelSection heading="Zones by level">
                <div className="chip-row">
                  {Object.entries(LEVELS).map(([key, value]) => (
                    <button
                      key={key}
                      type="button"
                      className="chip"
                      aria-pressed={level === key}
                      onClick={() => setLevel(level === key ? null : key)}
                    >
                      <span className="dot" style={{ background: value.color }} />
                      {value.label} ({counts[key]})
                    </button>
                  ))}
                </div>
                <p className="field-hint">Each zone is a 500 m square. Select a level to show only those zones.</p>
              </PanelSection>

              <PanelSection heading={picked ? picked.zone_id : "Select a zone on the map"}>
                {picked ? (
                  <>
                    <p style={{ marginBottom: 10 }}>
                      <span className={`badge is-${picked.stress_level.toLowerCase()}`}>
                        {LEVELS[picked.stress_level].label} stress
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
                  percentiles, then combined by fixed weights, shown when a zone is selected. This is a screening index for
                  comparing places inside one district, not an absolute measure.
                </p>
              </PanelSection>
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
