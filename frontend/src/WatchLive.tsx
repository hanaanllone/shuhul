import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiFetch } from "./frontend_api";

interface Place {
  name: string;
  lat: number;
  lng: number;
  kind: string | null;
}

interface Issue {
  id: number;
  url: string;
  title: string;
  excerpt: string | null;
  published_at: string | null;
  source_name: string;
  category: string;
  category_label: string;
  district: string | null;
  district_code: string | null;
  lat: number | null;
  lng: number | null;
  location_precision: string | null;
  places: Place[];
  factors: string[];
}

interface WatchResponse {
  issues: Issue[];
  categories: Record<string, string>;
  last_fetched: string | null;
  refreshing: boolean;
  note: string;
}

interface Props {
  onNavigate: (path: string) => void;
}

// Eight hues for ten issue types, so two pairs share a hue. Colour is
// never the only cue: every marker and card also carries its label.
const CATEGORY_COLORS: Record<string, string> = {
  flooding: "#2a78d6",
  heat: "#eb6834",
  wetland_loss: "#1baf7a",
  waste: "#eda100",
  air_pollution: "#e87ba4",
  tree_loss: "#008300",
  construction: "#4a3aa7",
  land_degradation: "#4a3aa7",
  water_pollution: "#e34948",
  water_scarcity: "#e34948",
};

const KASHMIR_CENTER: [number, number] = [34.08, 74.8];

function formatDate(value: string | null) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value.slice(0, 10)
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export default function WatchLive({ onNavigate }: Props) {
  const [data, setData] = useState<WatchResponse | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [district, setDistrict] = useState("");
  const [query, setQuery] = useState("");

  async function load() {
    try {
      setData(await apiFetch("/api/watch/issues"));
      setError("");
    } catch {
      setError("Could not load live reports.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  // While the server is reading the outlets, check back for new reports.
  useEffect(() => {
    if (!data?.refreshing) return;
    const timer = window.setTimeout(load, 6000);
    return () => window.clearTimeout(timer);
  }, [data]);

  async function refresh() {
    try {
      await apiFetch("/api/watch/refresh", { method: "POST" });
      setData((previous) => (previous ? { ...previous, refreshing: true } : previous));
    } catch {
      setError("Could not start a refresh.");
    }
  }

  function openOnMap(issue: Issue) {
    sessionStorage.setItem(
      "shuhulFocus",
      JSON.stringify({
        lat: issue.lat,
        lng: issue.lng,
        title: issue.title,
        label: issue.category_label,
        layers: issue.factors,
      })
    );
    onNavigate("create");
  }

  const issues = data?.issues || [];

  const districts = useMemo(
    () => Array.from(new Set(issues.map((issue) => issue.district).filter(Boolean))).sort() as string[],
    [issues]
  );

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    issues.forEach((issue) => {
      result[issue.category] = (result[issue.category] || 0) + 1;
    });
    return result;
  }, [issues]);

  const shown = issues.filter(
    (issue) =>
      (!category || issue.category === category) &&
      (!district || issue.district === district) &&
      (!query || issue.title.toLowerCase().includes(query.toLowerCase()))
  );
  const located = shown.filter((issue) => issue.lat !== null && issue.lng !== null);

  return (
    <section className="wl">
      <style>{`
        .wl{margin:22px 22px 0;border:1px solid #8aa4a5;background:#fffdf8}
        .wl-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 18px;border-bottom:1px solid #8aa4a5;background:#e7eee1}
        .wl-head h2{margin:0;color:#17275f;font-size:17px}
        .wl-head p{margin:5px 0 0;color:#666;font-size:11px}
        .wl-filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 18px;border-bottom:1px solid #ddd}
        .wl-filters input,.wl-filters select{padding:7px 8px;border:1px solid #8aa4a5;background:#f7f6f1;font-size:12px}
        .wl-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border:1px solid #c4d2c1;background:#f7f6f1;color:#17275f;font-size:11px;cursor:pointer}
        .wl-chip.on{border-color:#17275f;background:#17275f;color:#fff}
        .wl-dot{width:10px;height:10px;border-radius:50%;flex:none}
        .wl-body{display:grid;grid-template-columns:minmax(360px,1.3fr) minmax(300px,1fr)}
        .wl-map{height:440px}
        .wl-list{height:440px;overflow:auto;border-left:1px solid #ddd}
        .wl-item{padding:12px 16px;border-bottom:1px solid #ddd}
        .wl-item a{color:#17275f;font-weight:bold;font-size:13px;text-decoration:none}
        .wl-item a:hover{text-decoration:underline}
        .wl-item p{margin:6px 0;color:#444;font-size:12px;line-height:1.5}
        .wl-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px;color:#777;font-size:10px}
        .wl-link{border:0;background:none;padding:0;color:#008b8b;font-size:11px;font-weight:bold;cursor:pointer}
        .wl-note{padding:9px 18px;border-top:1px solid #ddd;color:#666;font-size:11px}
        .wl-empty{padding:28px 18px;color:#666;font-size:12px}
        @media (max-width: 980px){.wl-body{grid-template-columns:1fr}.wl-list{border-left:0;border-top:1px solid #ddd}}
      `}</style>

      <div className="wl-head">
        <div>
          <h2>Live reports</h2>
          <p>
            {issues.length} environmental reports from Greater Kashmir, Free Press Kashmir and Kashmir Life
            {data?.last_fetched ? ` · last read ${formatDate(data.last_fetched)}` : ""}
          </p>
        </div>
        <button className="ew-secondary" onClick={refresh} disabled={data?.refreshing}>
          {data?.refreshing ? "READING OUTLETS..." : "CHECK FOR NEW REPORTS"}
        </button>
      </div>

      {error && <div className="ew-error">{error}</div>}

      <div className="wl-filters">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search headlines"
        />
        <select value={district} onChange={(event) => setDistrict(event.target.value)}>
          <option value="">All districts</option>
          {districts.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        {Object.entries(data?.categories || {})
          .filter(([key]) => counts[key])
          .map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`wl-chip ${category === key ? "on" : ""}`}
              onClick={() => setCategory(category === key ? "" : key)}
            >
              <span className="wl-dot" style={{ background: CATEGORY_COLORS[key] || "#777" }} />
              {label} ({counts[key]})
            </button>
          ))}
      </div>

      <div className="wl-body">
        <MapContainer center={KASHMIR_CENTER} zoom={9} className="wl-map">
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />
          {located.map((issue) => (
            <CircleMarker
              key={issue.id}
              center={[issue.lat as number, issue.lng as number]}
              radius={issue.location_precision === "place" ? 7 : 5}
              pathOptions={{
                color: "#ffffff",
                weight: 2,
                fillColor: CATEGORY_COLORS[issue.category] || "#777",
                fillOpacity: issue.location_precision === "place" ? 0.95 : 0.55,
              }}
            >
              <Popup>
                <div style={{ fontSize: 12, maxWidth: 240 }}>
                  <div style={{ color: "#008b8b", fontWeight: "bold", fontSize: 10 }}>
                    {issue.category_label.toUpperCase()}
                  </div>
                  <div style={{ fontWeight: "bold", margin: "4px 0" }}>{issue.title}</div>
                  <div style={{ color: "#666" }}>
                    {issue.source_name} · {formatDate(issue.published_at)}
                  </div>
                  <div style={{ color: "#666", marginTop: 4 }}>
                    {issue.location_precision === "place"
                      ? `Named in report: ${issue.places.map((place) => place.name).join(", ")}`
                      : `District only: ${issue.district}`}
                  </div>
                  <button className="wl-link" style={{ marginTop: 6 }} onClick={() => openOnMap(issue)}>
                    Open this location in Shuhul →
                  </button>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>

        <div className="wl-list">
          {!data ? (
            <div className="wl-empty">Loading live reports...</div>
          ) : shown.length === 0 ? (
            <div className="wl-empty">
              No reports yet. Use "Check for new reports" to read the three outlets.
            </div>
          ) : (
            shown.map((issue) => (
              <div className="wl-item" key={issue.id}>
                <div className="wl-meta">
                  <span className="wl-dot" style={{ background: CATEGORY_COLORS[issue.category] || "#777" }} />
                  <span>{issue.category_label}</span>
                  <span>{issue.source_name}</span>
                  <span>{formatDate(issue.published_at)}</span>
                  {issue.district && <span>{issue.district}</span>}
                </div>
                <p style={{ margin: "6px 0 0" }}>
                  <a href={issue.url} target="_blank" rel="noreferrer">{issue.title}</a>
                </p>
                {issue.excerpt && <p>{issue.excerpt}</p>}
                {issue.lat !== null && (
                  <button className="wl-link" onClick={() => openOnMap(issue)}>
                    Open this location in Shuhul →
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="wl-note">
        {data?.note} {located.length} of {shown.length} shown reports have a map location.
        Faded markers are placed at the district centre because the report names no specific place.
      </div>
    </section>
  );
}
