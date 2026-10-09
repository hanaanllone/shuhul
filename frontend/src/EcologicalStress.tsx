import { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  LayersControl,
  ZoomControl,
  ScaleControl,
  useMap,
} from "react-leaflet";
import type { FeatureCollection, Geometry } from "geojson";
import type { Layer } from "leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const { BaseLayer } = LayersControl;

type StressProperties = {
  zone_id: string;
  stress_level: "LOW" | "MODERATE" | "HIGH";
  stress_score: number;
  mean_ndvi: number | null;
  mean_ndwi: number | null;
  canopy_cover_pct: number | null;
  built_up_density_pct: number | null;
  mean_lst: number | null;
};

type StressData = FeatureCollection<Geometry, StressProperties>;

const API = import.meta.env.VITE_API_URL || "http://localhost:5000";

const districtCodes: Record<string, string> = {
  Anantnag: "ant",
  Budgom: "bdg",
  Bandpur: "bnd",
  Ganderbal: "gnd",
  Kolgoam: "klgm",
  Kopwoar: "kpwr",
  Pulwoam: "plwoam",
  Shupiyan: "shpyn",
  Srinagar: "sxr",
  SrinagarCity: "sr-c",
  Varmul: "var",
};

const COLORS = {
  HIGH: "#e34b4b",
  MODERATE: "#e9a62a",
  LOW: "#65a85c",
};

function FitStressBounds({ data }: { data: StressData | null }) {
  const map = useMap();

  useEffect(() => {
    if (!data?.features?.length) return;

    // GeoJSON returned by the backend is WGS84.
    // Fit only to the actual stress-zone layer, not the raw buffered raster.
    const layer = L.geoJSON(data as any);
    const bounds = layer.getBounds();

    if (bounds.isValid()) {
      map.fitBounds(bounds, {
        padding: [28, 28],
        maxZoom: 13,
      });
    }
  }, [data, map]);

  return null;
}

function fmt(v: number | null, suffix = "") {
  return v == null || Number.isNaN(v) ? "—" : `${v.toFixed(2)}${suffix}`;
}

export default function EcologicalStress({
  onNavigate,
}: {
  onNavigate: (target: string) => void;
}) {
  const [district, setDistrict] = useState("Srinagar");
  const [data, setData] = useState<StressData | null>(null);
  const [selected, setSelected] = useState<StressProperties | null>(null);
  const [filter, setFilter] =
    useState<"ALL" | "HIGH" | "MODERATE" | "LOW">("ALL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");
      setSelected(null);

      try {
        const response = await fetch(
          `${API}/api/stress/${districtCodes[district]}`
        );
        const json = await response.json();

        if (!response.ok) {
          throw new Error(
            json.error || "Could not load ecological stress data."
          );
        }

        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not load stress data."
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [district]);

  const visibleData = useMemo(() => {
    if (!data || filter === "ALL") return data;

    return {
      ...data,
      features: data.features.filter(
        (feature) => feature.properties.stress_level === filter
      ),
    };
  }, [data, filter]);

  const counts = useMemo(() => {
    const result = { HIGH: 0, MODERATE: 0, LOW: 0 };

    data?.features.forEach((feature) => {
      result[feature.properties.stress_level]++;
    });

    return result;
  }, [data]);

  const styleZone = (feature: any) => {
    const level =
      feature?.properties?.stress_level || "LOW";

    const isSelected =
      selected?.zone_id === feature?.properties?.zone_id;

    return {
      color: isSelected ? "#17275f" : COLORS[level as keyof typeof COLORS],
      weight: isSelected ? 3 : 1,
      fillColor: COLORS[level as keyof typeof COLORS],
      fillOpacity: isSelected ? 0.72 : 0.46,
    };
  };

  function onEachZone(feature: any, layer: Layer) {
    layer.on({
      click: () => setSelected(feature.properties),

      mouseover: (event: any) => {
        event.target.setStyle({
          weight: 3,
          fillOpacity: 0.72,
        });
      },

      mouseout: (event: any) => {
        event.target.setStyle(styleZone(feature));
      },
    });
  }

  return (
    <>
      <style>{`
        * {
          box-sizing: border-box;
        }

        body {
          margin: 0;
          font-family: Arial, Helvetica, sans-serif;
          color: #17275f;
          background: #f7f6f1;
        }

        .stress-dashboard {
          width: 100%;
          min-height: 100vh;
          padding: 24px 32px;
          background-color: #f7f6f1;
          background-image:
            linear-gradient(
              rgba(96, 190, 195, 0.16) 1px,
              transparent 1px
            ),
            linear-gradient(
              90deg,
              rgba(96, 190, 195, 0.16) 1px,
              transparent 1px
            );
          background-size: 25px 25px;
        }

        .stress-layout {
          display: grid;
          grid-template-columns: 180px 1fr;
          min-height: calc(100vh - 48px);
          border: 3px solid #17275f;
        }

        .stress-sidebar {
          border-right: 3px solid #17275f;
          background: #f7f6f1;
        }

        .logo-container {
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-bottom: 3px solid #17275f;
          
        }

        .logo {
          margin-left:0px;
          margin-top:5px;
          width: 60px;
        }

        .stress-menu {
          display: flex;
          flex-direction: column;
          gap: 28px;
          padding: 72px 8px;
        }

        .stress-menu button {
          padding: 0;
          border: none;
          text-align: left;
          color: #111;
          background: transparent;
          cursor: pointer;
          font-size: 14px;
        }

        .stress-menu button:hover,
        .stress-menu .active {
          color: #568f89;
        }

        .stress-content {
          min-width: 0;
          display: flex;
          flex-direction: column;
        }

        .stress-header {
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 20px;
          padding: 0 20px;
          border-bottom: 3px solid #17275f;
        }

        .stress-header h1 {
          margin: 0;
          font-size: 30px;
        }

        .stress-main {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 25px 30px 45px;
        }

        .stress-controls {
          width: min(1080px, 100%);
          display: flex;
          justify-content: space-between;
          align-items: end;
          gap: 15px;
          margin-bottom: 18px;
        }

        .control-label {
          display: block;
          margin-bottom: 7px;
          color: #17275f;
          font-size: 11px;
          font-weight: bold;
          text-transform: uppercase;
          letter-spacing: .05em;
        }

        .stress-select {
          min-width: 180px;
          height: 35px;
          padding: 7px 10px;
          border: none;
          background: #f3ddbd;
          color: #111;
          outline: none;
        }

        .stress-select:focus {
          outline: 2px solid #568f89;
        }

        .summary {
          width: min(1080px, 100%);
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 15px;
          margin-bottom: 18px;
        }

        .summary-card {
          padding: 16px 18px;
          background: #f7f6f1;
          border: 2px solid #17275f;
        }

        .summary-title {
          margin-bottom: 7px;
          color: #555;
          font-size: 11px;
        }

        .summary-value {
          color: #17275f;
          font-size: 25px;
          font-weight: bold;
        }

        .summary-high .summary-value { color: #d84848; }
        .summary-moderate .summary-value { color: #c78917; }
        .summary-low .summary-value { color: #4e9250; }

        .map-wrapper {
          width: min(1080px, 100%);
          height: 520px;
          position: relative;
          border: 1px solid #8aa4a5;
          overflow: hidden;
          background: #dfe7e3;
        }

        .map-container {
          width: 100%;
          height: 100%;
        }

        .leaflet-control-zoom {
          border: 2px solid #17275f !important;
        }

        .leaflet-control-zoom a {
          color: #17275f !important;
          background: #f7f6f1 !important;
        }

        .leaflet-control-layers {
          border: 2px solid #17275f !important;
          background: #f7f6f1 !important;
          color: #17275f;
        }

        .map-status {
          position: absolute;
          z-index: 1000;
          top: 15px;
          left: 50%;
          transform: translateX(-50%);
          padding: 9px 13px;
          background: rgba(247,246,241,.96);
          border: 1px solid #8aa4a5;
          color: #17275f;
          font-size: 11px;
        }

        .map-error {
          color: #a33;
        }

        .stress-legend {
          position: absolute;
          z-index: 800;
          left: 15px;
          bottom: 15px;
          padding: 12px 14px;
          background: rgba(247,246,241,.96);
          border: 1px solid #8aa4a5;
          color: #17275f;
          font-size: 11px;
        }

        .legend-title {
          margin-bottom: 7px;
          font-weight: bold;
        }

        .legend-row {
          display: flex;
          align-items: center;
          gap: 7px;
          margin-top: 5px;
          color: #555;
        }

        .legend-dot {
          width: 10px;
          height: 10px;
          border: 1px solid rgba(23,39,95,.4);
        }

        .selected-zone {
          width: min(1080px, 100%);
          margin-top: 20px;
          padding: 25px 30px 30px;
          border-top: 3px solid #17275f;
          background: #e7eee1;
        }

        .selected-inner {
          max-width: 900px;
          margin: auto;
        }

        .selected-top {
          display: flex;
          justify-content: space-between;
          align-items: start;
          gap: 15px;
          margin-bottom: 20px;
        }

        .selected-zone h2 {
          margin: 0;
          font-size: 25px;
        }

        .selected-zone p {
          margin: 6px 0 0;
          color: #555;
          font-size: 12px;
        }

        .stress-badge {
          padding: 7px 11px;
          border: 2px solid #17275f;
          background: #f3ddbd;
          color: #17275f;
          font-size: 11px;
          font-weight: bold;
        }

        .metric-grid {
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 12px;
        }

        .metric-card {
          padding: 16px;
          background: #f7f6f1;
          border: 2px solid #17275f;
        }

        .metric-title {
          margin-bottom: 10px;
          color: #555;
          font-size: 10px;
          font-weight: bold;
        }

        .metric-value {
          color: #17275f;
          font-size: 20px;
          font-weight: bold;
        }

        .metric-note {
          margin-top: 5px;
          color: #777;
          font-size: 9px;
        }

        .empty-zone {
          width: min(1080px, 100%);
          margin-top: 20px;
          padding: 22px;
          border: 1px solid #8aa4a5;
          background: #f7f6f1;
          color: #555;
          font-size: 12px;
          text-align: center;
        }

        @media (max-width: 900px) {
          .stress-layout {
            grid-template-columns: 1fr;
          }

          .stress-sidebar {
            display: none;
          }

          .stress-controls {
            align-items: stretch;
            flex-direction: column;
          }

          .summary {
            grid-template-columns: 1fr;
          }

          .metric-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }

        @media (max-width: 600px) {
          .stress-dashboard {
            padding: 12px;
          }

          .stress-main {
            padding: 18px 12px 30px;
          }

          .stress-header {
            padding: 0 12px;
          }

          .metric-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>

      <main className="stress-dashboard">
        <div className="stress-layout">
          <aside className="stress-sidebar">
            <div className="logo-container">
              <img className="logo" src="/logo.png" alt="Tshaai" />
            </div>

            <nav className="stress-menu">
              <button onClick={() => onNavigate("home")}>Home</button>
              <button onClick={() => onNavigate("aoi")}>AOI Analysis</button>
              <button onClick={() => onNavigate("environmental-watch")}>Environmental Watch</button>
              <button
                className="active"
                onClick={() => onNavigate("ecological-stress")}
              >
                Ecological Stress
              </button>
              <button onClick={() => onNavigate("home")}>Thermal Compensation</button>
              <button onClick={() => onNavigate("home")}>Environmental Analysis</button>
              <button onClick={() => onNavigate("settings")}>Settings</button>
            </nav>
          </aside>

          <section className="stress-content">
            <header className="stress-header">
              <h1>Ecological Stress</h1>
            </header>

            <div className="stress-main">
              <div className="stress-controls">
                <div>
                  <label className="control-label">District</label>
                  <select
                    className="stress-select"
                    value={district}
                    onChange={(e) => setDistrict(e.target.value)}
                  >
                    {Object.keys(districtCodes).map((name) => (
                      <option key={name}>{name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="control-label">Show zones</label>
                  <select
                    className="stress-select"
                    value={filter}
                    onChange={(e) =>
                      setFilter(
                        e.target.value as
                          | "ALL"
                          | "HIGH"
                          | "MODERATE"
                          | "LOW"
                      )
                    }
                  >
                    <option value="ALL">All zones</option>
                    <option value="HIGH">High stress</option>
                    <option value="MODERATE">Moderate stress</option>
                    <option value="LOW">Low stress</option>
                  </select>
                </div>
              </div>

              <div className="summary">
                <div className="summary-card summary-high">
                  <div className="summary-title">HIGH STRESS ZONES</div>
                  <div className="summary-value">{counts.HIGH}</div>
                </div>

                <div className="summary-card summary-moderate">
                  <div className="summary-title">MODERATE STRESS ZONES</div>
                  <div className="summary-value">{counts.MODERATE}</div>
                </div>

                <div className="summary-card summary-low">
                  <div className="summary-title">LOW STRESS ZONES</div>
                  <div className="summary-value">{counts.LOW}</div>
                </div>
              </div>

              <div className="map-wrapper">
                {loading && (
                  <div className="map-status">Generating stress map...</div>
                )}

                {error && (
                  <div className="map-status map-error">{error}</div>
                )}

                <MapContainer
                  center={[34.0837, 74.7973]}
                  zoom={12}
                  zoomControl={false}
                  className="map-container"
                  scrollWheelZoom
                >
                  <LayersControl position="topright">
                    <BaseLayer checked name="Humanitarian">
                      <TileLayer
                        url="https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png"
                        attribution="&copy; OpenStreetMap contributors"
                      />
                    </BaseLayer>

                    <BaseLayer name="OpenStreetMap">
                      <TileLayer
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        attribution="&copy; OpenStreetMap contributors"
                      />
                    </BaseLayer>
                  </LayersControl>

                  <ZoomControl position="bottomright" />
                  <ScaleControl position="bottomright" />

                  {visibleData && (
                    <>
                      <GeoJSON
                        key={`${district}-${filter}-${selected?.zone_id || "none"}`}
                        data={visibleData as any}
                        style={styleZone}
                        onEachFeature={onEachZone}
                      />
                      <FitStressBounds data={data} />
                    </>
                  )}
                </MapContainer>

                <div className="stress-legend">
                  <div className="legend-title">ECOLOGICAL STRESS</div>

                  {(["HIGH", "MODERATE", "LOW"] as const).map((level) => (
                    <div className="legend-row" key={level}>
                      <span
                        className="legend-dot"
                        style={{ background: COLORS[level] }}
                      />
                      {level.charAt(0) + level.slice(1).toLowerCase()}
                    </div>
                  ))}
                </div>
              </div>

              {selected ? (
                <section className="selected-zone">
                  <div className="selected-inner">
                    <div className="selected-top">
                      <div>
                        <div className="control-label">Selected area</div>
                        <h2>{selected.zone_id}</h2>
                        <p>
                          Environmental conditions within this analysis zone.
                        </p>
                      </div>

                      <div className="stress-badge">
                        {selected.stress_level} STRESS ·{" "}
                        {selected.stress_score.toFixed(2)}
                      </div>
                    </div>

                    <div className="metric-grid">
                      <div className="metric-card">
                        <div className="metric-title">NDVI</div>
                        <div className="metric-value">
                          {fmt(selected.mean_ndvi)}
                        </div>
                        <div className="metric-note">
                          Vegetation condition
                        </div>
                      </div>

                      <div className="metric-card">
                        <div className="metric-title">CANOPY</div>
                        <div className="metric-value">
                          {fmt(selected.canopy_cover_pct, "%")}
                        </div>
                        <div className="metric-note">Canopy cover</div>
                      </div>

                      <div className="metric-card">
                        <div className="metric-title">LST</div>
                        <div className="metric-value">
                          {fmt(selected.mean_lst, "°")}
                        </div>
                        <div className="metric-note">
                          Surface temperature
                        </div>
                      </div>

                      <div className="metric-card">
                        <div className="metric-title">BUILDING</div>
                        <div className="metric-value">
                          {fmt(selected.built_up_density_pct, "%")}
                        </div>
                        <div className="metric-note">
                          Built-up density
                        </div>
                      </div>

                      <div className="metric-card">
                        <div className="metric-title">NDWI</div>
                        <div className="metric-value">
                          {fmt(selected.mean_ndwi)}
                        </div>
                        <div className="metric-note">
                          Surface water signal
                        </div>
                      </div>
                    </div>
                  </div>
                </section>
              ) : (
                <div className="empty-zone">
                  Click a zone on the map to inspect its environmental
                  conditions.
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </>
  );
}
