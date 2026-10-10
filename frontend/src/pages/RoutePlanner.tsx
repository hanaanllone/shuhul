import { useEffect, useState } from "react";
import { LayerNotes, LayerToggles, useLayerManifest } from "../components/MapLayers";
import type { ActiveLayers } from "../components/MapLayers";
import { Panel, PanelSection, Tabs } from "../components/ui";
import { api, errorMessage, post } from "../lib/api";
import type { LatLng, ProjectDetail, ProjectResult, ProjectStatus } from "../lib/types";
import PlannerMap, { ALL_ZONE_KINDS, INTERVENTIONS } from "./planner/PlannerMap";
import type { PointName, ZoneKinds } from "./planner/PlannerMap";
import { HeatPanel, MethodPanel, MitigationPanel, RoutesPanel } from "./planner/ResultPanels";
import SetupPanel, { DEFAULT_FORM } from "./planner/SetupPanel";
import type { PlannerForm } from "./planner/SetupPanel";

type TabId = "setup" | "layers" | "routes" | "heat" | "mitigation" | "method";

const POLL_MS = 1500;

interface Props {
  projectId?: string;
  onNavigate: (path: string) => void;
}

interface WatchFocus extends LatLng {
  title: string;
  label: string;
  layers?: string[];
}

// A location handed over from the Watch page, if there is one.
function readFocus(): WatchFocus | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem("shuhulFocus") || "null");
    return saved && saved.lat != null && saved.lng != null ? saved : null;
  } catch {
    return null;
  }
}

export default function RoutePlanner({ projectId }: Props) {
  const [focus] = useState(readFocus);
  const [form, setForm] = useState<PlannerForm>(DEFAULT_FORM);
  const [points, setPoints] = useState<Record<PointName, LatLng | null>>({ A: null, B: null });
  const [picking, setPicking] = useState<PointName | null>(null);

  const [running, setRunning] = useState<{ stage: string; progress: number } | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ProjectResult | null>(null);
  const [corridors, setCorridors] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedRoute, setSelectedRoute] = useState<string | null>(null);

  const [tab, setTab] = useState<TabId>("setup");
  const [activeLayers, setActiveLayers] = useState<ActiveLayers>(() =>
    Object.fromEntries((focus?.layers || []).map((name) => [name, true]))
  );
  const [show, setShow] = useState({ routes: true, corridors: true });
  const [zoneKinds, setZoneKinds] = useState<ZoneKinds>(ALL_ZONE_KINDS);
  const [highlightZone, setHighlightZone] = useState<string | null>(null);

  // A second press on the same zone lets go of it.
  function pickZone(zoneId: string) {
    setHighlightZone((previous) => (previous === zoneId ? null : zoneId));
  }

  const zoneChips = (
    <div className="chip-row">
      {Object.entries(INTERVENTIONS).map(([kind, spec]) => (
        <button
          key={kind}
          type="button"
          className="chip"
          aria-pressed={zoneKinds[kind]}
          onClick={() => setZoneKinds((previous) => ({ ...previous, [kind]: !previous[kind] }))}
        >
          <span className="dot" style={{ background: spec.color }} />
          {spec.label}
        </button>
      ))}
    </div>
  );

  const manifest = useLayerManifest(result?.district || "sxr");

  useEffect(() => {
    sessionStorage.removeItem("shuhulFocus");
  }, []);

  function accept(finished: ProjectResult) {
    setResult(finished);
    setSelectedRoute(Object.keys(finished.impact?.routes || {})[0] || null);
    setHighlightZone(null);
    setTab("routes");
  }

  function selectRoute(name: string | null) {
    setSelectedRoute(name);
    setHighlightZone(null);
  }

  // Open a saved project.
  useEffect(() => {
    if (!projectId) return;

    api<ProjectDetail>(`/api/projects/${projectId}`)
      .then((project) => {
        const payload = project.payload;
        setForm({
          projectName: payload.projectName || "",
          constructionType: payload.constructionType || "road",
          widthMeters: Number(payload.widthMeters) || 20,
          priorities: { ...DEFAULT_FORM.priorities, ...payload.softPreferences },
          constraints: { ...DEFAULT_FORM.constraints, ...payload.hardConstraints },
        });
        setPoints({ A: payload.start || null, B: payload.end || null });

        if (project.result) accept(project.result);
        else if (project.status === "failed") setError(project.error || "The analysis failed.");
        else if (project.status === "queued" || project.status === "running") follow(project.id);
      })
      .catch((problem) => setError(errorMessage(problem, "Could not open this project.")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Corridors are drawn by the server from the routes and the width.
  useEffect(() => {
    if (!result) return;

    api<GeoJSON.FeatureCollection>(`/api/projects/${result.projectId}/corridors`)
      .then(setCorridors)
      .catch(() => setCorridors(null));
  }, [result]);

  // Ask how the analysis is going until it finishes.
  async function follow(id: string) {
    setRunning({ stage: "Queued for analysis", progress: 0 });

    for (;;) {
      await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));

      let status: ProjectStatus;
      try {
        status = await api<ProjectStatus>(`/api/projects/${id}/status`);
      } catch (problem) {
        setError(errorMessage(problem, "Lost contact with the analysis."));
        setRunning(null);
        return;
      }

      if (status.status === "completed" && status.result) {
        setRunning(null);
        accept(status.result);
        return;
      }

      if (status.status === "failed") {
        setRunning(null);
        setError(status.error || "The analysis failed.");
        return;
      }

      setRunning({ stage: status.stage, progress: status.progress });
    }
  }

  async function run() {
    if (!points.A || !points.B) return;

    setError("");
    setResult(null);
    setCorridors(null);

    try {
      const created = await post<{ projectId: string }>("/api/projects", {
        projectName: form.projectName.trim() || "Untitled Project",
        constructionType: form.constructionType,
        widthMeters: form.widthMeters,
        start: points.A,
        end: points.B,
        softPreferences: form.priorities,
        hardConstraints: form.constraints,
      });

      // Keep the address in step without reloading the page.
      window.history.replaceState(null, "", `#/plan/${created.projectId}`);
      follow(created.projectId);
    } catch (problem) {
      setError(errorMessage(problem, "Could not start the analysis."));
    }
  }

  function pick(point: LatLng) {
    if (!picking) return;

    const next = { ...points, [picking]: point };
    setPoints(next);
    // After A, go straight on to B if it is still missing.
    setPicking(picking === "A" && !next.B ? "B" : null);
  }

  const hasResult = result !== null;

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Plan routes</h1>
        <span className="page-sub">{form.projectName.trim() || "Untitled Project"}</span>
      </div>

      <div className="split">
        <PlannerMap
          manifest={manifest}
          activeLayers={activeLayers}
          points={points}
          picking={picking}
          onPick={pick}
          result={result}
          corridors={corridors}
          selectedRoute={selectedRoute}
          show={show}
          zoneKinds={zoneKinds}
          highlightZone={highlightZone}
          onZoneClick={pickZone}
          focus={focus}
        />

        <Panel className="side">
          <Tabs<TabId>
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "setup", label: "Setup" },
              { id: "layers", label: "Layers" },
              { id: "routes", label: "Routes", disabled: !hasResult },
              { id: "heat", label: "Heat and flood", disabled: !hasResult },
              { id: "mitigation", label: "Mitigation", disabled: !hasResult },
              { id: "method", label: "Method", disabled: !hasResult },
            ]}
          />

          {tab === "setup" && (
            <>
              <h2 className="panel-title">Project Setup</h2>
              {focus && (
                <p className="note" style={{ marginTop: 8 }}>
                  Opened from Environmental Watch ({focus.label.toLowerCase()}): "{focus.title}". The
                  marked location is as reported, not verified.
                </p>
              )}
              <SetupPanel
                form={form}
                onChange={setForm}
                points={points}
                picking={picking}
                onPickPoint={setPicking}
                running={running}
                error={error}
                onRun={run}
              />
            </>
          )}

          {tab === "layers" && (
            <>
              <h2 className="panel-title">Map layers</h2>
              <LayerToggles
                manifest={manifest}
                active={activeLayers}
                onToggle={(name) => setActiveLayers((previous) => ({ ...previous, [name]: !previous[name] }))}
              />

              {hasResult && (
                <>
                  <PanelSection heading="This project">
                    <div className="chip-row">
                      {(["routes", "corridors"] as const).map((name) => (
                        <button
                          key={name}
                          type="button"
                          className="chip"
                          aria-pressed={show[name]}
                          onClick={() => setShow((previous) => ({ ...previous, [name]: !previous[name] }))}
                        >
                          {name === "routes" ? "Routes" : "Corridors"}
                        </button>
                      ))}
                    </div>
                  </PanelSection>

                  <PanelSection heading="Mitigation zones">
                    {zoneChips}
                    <p className="field-hint">Choose which kinds are drawn. The plan itself does not change.</p>
                  </PanelSection>
                </>
              )}

              <LayerNotes manifest={manifest} active={activeLayers} />
            </>
          )}

          {result && tab === "routes" && (
            <RoutesPanel result={result} selected={selectedRoute} onSelect={selectRoute} />
          )}
          {result && tab === "heat" && <HeatPanel result={result} selected={selectedRoute} />}
          {result && tab === "mitigation" && (
            <MitigationPanel
              result={result}
              selected={selectedRoute}
              zoneKinds={zoneKinds}
              zoneChips={zoneChips}
              highlightZone={highlightZone}
              onZoneClick={pickZone}
            />
          )}
          {result && tab === "method" && <MethodPanel result={result} />}
        </Panel>
      </div>
    </main>
  );
}
