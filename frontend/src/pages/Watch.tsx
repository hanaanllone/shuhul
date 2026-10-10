import { useEffect, useMemo, useState } from "react";
import { CircleMarker, Popup } from "react-leaflet";
import BaseMap, { ResizeWatcher } from "../components/BaseMap";
import { Panel, PanelSection, Tabs } from "../components/ui";
import { api, errorMessage, post } from "../lib/api";
import { day } from "../lib/format";

interface Place {
  name: string;
  lat: number;
  lng: number;
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
  lat: number | null;
  lng: number | null;
  location_precision: string | null;
  places: Place[];
  factors: string[];
}

interface WatchData {
  issues: Issue[];
  categories: Record<string, string>;
  last_fetched: string | null;
  refreshing: boolean;
  note: string;
}

interface Article {
  article_id: string;
  title: string;
  date?: string | null;
  source?: string | null;
}

interface Analysis {
  issue: { title: string; status: string; description: string };
  spatial_context: { named_places: string[]; district: string | null };
  reported_claims: { claim: string; attributed_to: string | null }[];
  action: { title: string; description: string };
  source?: { title?: string; date?: string | null; publisher?: string | null };
}

// What the map layers show around the place a report names.
interface Evidence {
  reading: string[];
  caution: string;
  scope: string;
}

type EvidenceState = { status: "loading" } | { status: "ready"; evidence: Evidence } | { status: "failed"; message: string };

// What the archive tab is showing: the list, one report, or the worked example.
type ArchiveView = { kind: "list" } | { kind: "article"; article: Article } | { kind: "example" };

type TabId = "live" | "archive";

// Eight hues for ten issue types, so two pairs share one. Colour is never
// the only cue: every marker and row also carries its label.
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

const KASHMIR: [number, number] = [34.08, 74.8];

function RecordView({ state, place }: { state?: EvidenceState; place?: string }) {
  if (!state) return null;
  if (state.status === "loading") return <p className="note" style={{ marginTop: 8 }}>Reading the record...</p>;
  if (state.status === "failed") return <p className="message" style={{ marginTop: 8 }}>{state.message}</p>;

  return (
    <div className="record">
      <div className="record-title">
        {place ? `${place}, ` : ""}
        {state.evidence.scope}
      </div>
      <ul>
        {state.evidence.reading.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="note">{state.evidence.caution}</p>
    </div>
  );
}

function AnalysisView({ analysis }: { analysis: Analysis }) {
  return (
    <>
      <PanelSection heading="Issue">
        <p style={{ fontWeight: 600 }}>{analysis.issue.title}</p>
        <p className="note" style={{ marginTop: 6 }}>{analysis.issue.description}</p>
        <p className="note" style={{ marginTop: 6 }}>
          Places named: {analysis.spatial_context.named_places.join(", ") || "none"}. District:{" "}
          {analysis.spatial_context.district || "not established"}.
        </p>
      </PanelSection>
      <PanelSection heading="Reported claims">
        {analysis.reported_claims.map((claim) => (
          <p key={claim.claim} style={{ fontSize: 14, marginBottom: 6 }}>
            {claim.claim} <span className="note">Attributed to {claim.attributed_to || "the report"}.</span>
          </p>
        ))}
        <p className="note">Claims are as reported. Shuhul has not checked them.</p>
      </PanelSection>
      <PanelSection heading="Suggested check">
        <p style={{ fontWeight: 600 }}>{analysis.action.title}</p>
        <p className="note" style={{ marginTop: 6 }}>{analysis.action.description}</p>
      </PanelSection>
    </>
  );
}

interface Props {
  onNavigate: (path: string) => void;
}

export default function Watch({ onNavigate }: Props) {
  const [tab, setTab] = useState<TabId>("live");
  const [data, setData] = useState<WatchData | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [district, setDistrict] = useState("");
  const [query, setQuery] = useState("");

  // The satellite record around each report that has been asked about.
  const [evidence, setEvidence] = useState<Record<number, EvidenceState>>({});

  const [articles, setArticles] = useState<Article[]>([]);
  const [archive, setArchive] = useState<ArchiveView>({ kind: "list" });
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [analysisError, setAnalysisError] = useState("");

  function load() {
    api<WatchData>("/api/watch/issues")
      .then((fresh) => {
        setData(fresh);
        setError("");
      })
      .catch((problem) => setError(errorMessage(problem, "Could not load reports.")));
  }

  useEffect(() => {
    load();
    api<{ articles: Article[] }>("/api/environmental-watch/articles")
      .then((result) => setArticles(result.articles || []))
      .catch(() => setArticles([]));
  }, []);

  // While the server is reading the outlets, check back for new reports.
  useEffect(() => {
    if (!data?.refreshing) return;
    const timer = window.setTimeout(load, 6000);
    return () => window.clearTimeout(timer);
  }, [data]);

  async function refresh() {
    try {
      await post("/api/watch/refresh");
      setData((previous) => (previous ? { ...previous, refreshing: true } : previous));
    } catch (problem) {
      setError(errorMessage(problem, "Could not start a refresh."));
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
    onNavigate("plan");
  }

  async function checkRecord(issue: Issue) {
    // A second press folds the answer away again.
    if (evidence[issue.id]) {
      setEvidence((previous) => {
        const next = { ...previous };
        delete next[issue.id];
        return next;
      });
      return;
    }

    setEvidence((previous) => ({ ...previous, [issue.id]: { status: "loading" } }));

    try {
      const found = await post<Evidence>("/api/area/around", { lat: issue.lat, lng: issue.lng });
      setEvidence((previous) => ({ ...previous, [issue.id]: { status: "ready", evidence: found } }));
    } catch (problem) {
      setEvidence((previous) => ({
        ...previous,
        [issue.id]: { status: "failed", message: errorMessage(problem, "The record could not be read.") },
      }));
    }
  }

  function openArchive(view: ArchiveView) {
    setArchive(view);
    setAnalysis(null);
    setAnalysisError("");

    if (view.kind === "example") {
      api<Analysis>("/api/environmental-watch/demo-analysis")
        .then(setAnalysis)
        .catch(() => setAnalysisError("The worked example could not be loaded."));
    }
  }

  async function analyse(chosen: Article) {
    setAnalysing(true);
    setAnalysisError("");

    try {
      const result = await post<{ analysis: Analysis }>(`/api/environmental-watch/analyse/${chosen.article_id}`);
      setAnalysis(result.analysis);
    } catch {
      setAnalysisError(
        "This report could not be analysed. Reading a report needs the language model, which is not connected yet."
      );
    } finally {
      setAnalysing(false);
    }
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
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Environmental watch</h1>
        <span className="page-sub">{issues.length} reports from three Kashmir outlets</span>
      </div>

      <div className="split">
        <div className="map-card">
          <BaseMap center={KASHMIR} zoom={9}>
            <ResizeWatcher />
            {located.map((issue) => (
              <CircleMarker
                key={issue.id}
                center={[issue.lat as number, issue.lng as number]}
                radius={issue.location_precision === "place" ? 8 : 6}
                pathOptions={{
                  color: "#f8f8f4",
                  weight: 2,
                  fillColor: CATEGORY_COLORS[issue.category] || "#647068",
                  fillOpacity: issue.location_precision === "place" ? 0.95 : 0.55,
                }}
              >
                <Popup>
                  <div style={{ maxWidth: 240 }}>
                    <b style={{ fontSize: 11, letterSpacing: "0.06em" }}>{issue.category_label.toUpperCase()}</b>
                    <div style={{ fontWeight: 600, margin: "4px 0" }}>{issue.title}</div>
                    <div>{issue.source_name} · {day(issue.published_at)}</div>
                    <div>
                      {issue.location_precision === "place"
                        ? `Named in the report: ${issue.places.map((place) => place.name).join(", ")}`
                        : `District only: ${issue.district}`}
                    </div>
                    <button className="link-btn" style={{ marginTop: 6 }} onClick={() => openOnMap(issue)}>
                      Open in the route planner
                    </button>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </BaseMap>

          <div className="map-overlay is-bottom-left">
            {located.length} of {shown.length} reports have a map location. Faded markers sit at the
            district centre because the report names no specific place.
          </div>
        </div>

        <Panel className="side">
          <Tabs<TabId>
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "live", label: "Live reports" },
              { id: "archive", label: "Curated archive" },
            ]}
          />

          {tab === "live" && (
            <>
              <input
                className="input"
                value={query}
                placeholder="Search headlines"
                onChange={(event) => setQuery(event.target.value)}
              />
              <select
                className="select"
                style={{ marginTop: 10 }}
                value={district}
                onChange={(event) => setDistrict(event.target.value)}
                aria-label="District"
              >
                <option value="">All districts</option>
                {districts.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>

              <div className="chip-row" style={{ marginTop: 12 }}>
                {Object.entries(data?.categories || {})
                  .filter(([key]) => counts[key])
                  .map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      className="chip"
                      aria-pressed={category === key}
                      onClick={() => setCategory(category === key ? "" : key)}
                    >
                      <span className="dot" style={{ background: CATEGORY_COLORS[key] }} />
                      {label} ({counts[key]})
                    </button>
                  ))}
              </div>

              {error && <p className="message" style={{ marginTop: 12 }}>{error}</p>}

              <PanelSection>
                {!data && !error && <p className="note">Loading reports...</p>}
                {data && shown.length === 0 && (
                  <p className="note">No reports match. Check for new reports to read the three outlets.</p>
                )}

                {shown.map((issue) => (
                  <div className="report-item" key={issue.id}>
                    <div className="report-meta">
                      <span className="dot" style={{ background: CATEGORY_COLORS[issue.category] }} />
                      <span>{issue.category_label}</span>
                      <span>{issue.source_name}</span>
                      <span>{day(issue.published_at)}</span>
                      {issue.district && <span>{issue.district}</span>}
                    </div>
                    <a href={issue.url} target="_blank" rel="noreferrer">{issue.title}</a>
                    {issue.excerpt && <p className="note" style={{ marginTop: 4 }}>{issue.excerpt}</p>}
                    <div className="chip-row" style={{ gap: 14 }}>
                      {issue.lat !== null && (
                        <button className="link-btn" style={{ fontSize: 12 }} onClick={() => openOnMap(issue)}>
                          Open in the route planner
                        </button>
                      )}
                      {issue.lat !== null && issue.location_precision === "place" && (
                        <button className="link-btn" style={{ fontSize: 12 }} onClick={() => checkRecord(issue)}>
                          {evidence[issue.id] ? "Hide the satellite record" : "What the satellite record shows"}
                        </button>
                      )}
                    </div>

                    <RecordView state={evidence[issue.id]} place={issue.places[0]?.name} />
                  </div>
                ))}
              </PanelSection>

              <PanelSection>
                <button className="btn is-dark is-block" onClick={refresh} disabled={data?.refreshing}>
                  {data?.refreshing ? "Reading the outlets..." : "Check for new reports"}
                </button>
                <p className="note" style={{ marginTop: 10 }}>
                  {data?.note} Reports are sorted by keywords for now, so some are filed under the
                  wrong type. Last read {day(data?.last_fetched)}.
                </p>
              </PanelSection>
            </>
          )}

          {tab === "archive" && archive.kind === "list" && (
            <>
              <p className="note" style={{ marginBottom: 8 }}>
                {articles.length} hand-picked reports used to build and test the analysis.
              </p>
              <button className="btn is-dark is-small" onClick={() => openArchive({ kind: "example" })}>
                See a worked example
              </button>

              <PanelSection>
                {articles.map((item) => (
                  <div className="report-item" key={item.article_id}>
                    <button
                      className="link-btn"
                      style={{ textAlign: "left" }}
                      onClick={() => openArchive({ kind: "article", article: item })}
                    >
                      {item.title}
                    </button>
                    <div className="report-meta">
                      <span>{item.date || "Date unavailable"}</span>
                      <span>{item.source || "Source in article"}</span>
                    </div>
                  </div>
                ))}
              </PanelSection>
            </>
          )}

          {tab === "archive" && archive.kind !== "list" && (
            <>
              <button className="link-btn" onClick={() => openArchive({ kind: "list" })}>Back to the archive</button>

              {archive.kind === "article" && (
                <>
                  <h2 className="panel-title" style={{ margin: "12px 0 6px" }}>{archive.article.title}</h2>
                  <div className="report-meta">
                    <span>{archive.article.date || "Date unavailable"}</span>
                    <span>{archive.article.source || "Source in article"}</span>
                  </div>

                  {!analysis && (
                    <button
                      className="btn is-dark is-block"
                      style={{ marginTop: 16 }}
                      disabled={analysing}
                      onClick={() => analyse(archive.article)}
                    >
                      {analysing ? "Reading the report..." : "Analyse this report"}
                    </button>
                  )}
                </>
              )}

              {archive.kind === "example" && (
                <>
                  <h2 className="panel-title" style={{ margin: "12px 0 6px" }}>Worked example</h2>
                  {analysis?.source && (
                    <div className="report-meta">
                      <span>{analysis.source.publisher}</span>
                      <span>{analysis.source.date}</span>
                    </div>
                  )}
                  {!analysis && !analysisError && <p className="note">Loading...</p>}
                </>
              )}

              {analysisError && <p className="message" style={{ marginTop: 14 }}>{analysisError}</p>}
              {analysis && <AnalysisView analysis={analysis} />}
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
