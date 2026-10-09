import { useEffect, useState } from "react";
import { apiFetch } from "./frontend_api";
import {
  MapContainer,
  TileLayer,
  ImageOverlay,
  GeoJSON,
  LayersControl,
  ScaleControl,
  ZoomControl,
  CircleMarker,
  Popup,
  useMapEvents,
  useMap,
} from "react-leaflet";

import { geoJSON as leafletGeoJSON } from "leaflet";

import "leaflet/dist/leaflet.css";

const { BaseLayer, Overlay } = LayersControl;

function MapPointSelector({ selectingPoints, onPointSelect }) {
  useMapEvents({
    click(e) {
      if (!selectingPoints) return;

      onPointSelect({
        lat: e.latlng.lat,
        lng: e.latlng.lng,
      });
    },
  });

  return null;
}

function FitResultsToMap({ routeGeoJSON }) {
  const map = useMap();

  useEffect(() => {
    if (
      !routeGeoJSON ||
      !routeGeoJSON.features ||
      routeGeoJSON.features.length === 0
    ) {
      return;
    }

    const layer = leafletGeoJSON(routeGeoJSON);
    const bounds = layer.getBounds();

    if (bounds.isValid()) {
      map.fitBounds(bounds, {
        padding: [35, 35],
        maxZoom: 16,
      });
    }
  }, [map, routeGeoJSON]);

  return null;
}


function formatReportNumber(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : String(value);
}

function getMitigationRoutes(result) {
  return Array.isArray(result?.mitigation?.routes)
    ? result.mitigation.routes
    : [];
}

function getMitigationZones(result) {
  return getMitigationRoutes(result).flatMap((route) =>
    (route?.selected_zones || route?.zones || route?.candidates || []).map(
      (zone, index) => ({
        ...zone,
        route: zone?.route || route?.route || "Route",
        zone_id: zone?.zone_id || zone?.zone || `Zone ${index + 1}`,
      })
    )
  );
}

function getInterventionLabel(zone) {
  const raw = String(
    zone?.intervention ||
      zone?.candidate_type ||
      zone?.type ||
      zone?.category ||
      "Mitigation"
  ).toLowerCase();

  if (raw.includes("tree")) return "Tree restoration";
  if (raw.includes("bush") || raw.includes("shrub")) return "Bush / shrub";
  if (raw.includes("roof")) return "Green roof";
  return zone?.intervention || zone?.candidate_type || "Mitigation";
}

function getReportRouteRows(result) {
  const routes: Record<string, any> = result?.impact?.routes || result?.routes || {};
  return Object.entries(routes).map(([name, data]) => ({
    name: data?.route || name,
    length: data?.route_length_km ?? data?.length_km ?? data?.distance_km,
    corridor:
      data?.impact_corridor_area_ha ??
      (data?.impact_corridor_area_m2 != null
        ? Number(data.impact_corridor_area_m2) / 10000
        : null),
    green:
      data?.green_space?.green_area_m2 ??
      data?.green_space?.area_m2 ??
      data?.green_space_area_m2,
    canopy:
      data?.canopy?.canopy_area_m2 ??
      data?.canopy?.area_m2 ??
      data?.canopy_area_m2,
    water:
      data?.water?.combined_water_area_m2 ??
      data?.water?.water_area_m2 ??
      data?.water?.area_m2 ??
      data?.water_area_m2,
    crossings:
      data?.water?.estimated_crossings ??
      data?.water?.crossings ??
      data?.water_crossings,
    buildings: data?.buildings?.count ?? data?.buildings_affected,
    heritage: data?.heritage?.count ?? data?.heritage_conflicts,
    slope: data?.slope?.mean_slope_deg ?? data?.mean_slope_deg,
    highSlope:
      data?.slope?.high_slope_percentage ??
      data?.high_slope_percentage,
    env:
      data?.environmental_cost?.environmental_cost_index ??
      data?.environmental_cost?.sum ??
      data?.environmental_cost_index,
    treeEquivalent: data?.canopy?.estimated_tree_equivalent,
  }));
}

function buildDownloadableReport(result) {
  const project = result?.project || {};
  const rows = getReportRouteRows(result);
  const summary = result?.report?.summary;
  const reportSummary =
    typeof summary === "string"
      ? summary
      : summary && typeof summary === "object"
        ? `Analysis completed for ${summary.routes_analyzed ?? rows.length} routes, with ${formatReportNumber(summary.mitigation_zones_across_routes, 0)} mitigation zones and ${formatReportNumber(summary.mitigation_capacity_m2_across_routes, 0)} m² of mitigation capacity identified.`
        : "Shuhul sustainable infrastructure planning analysis.";

  const mitigationRoutes = getMitigationRoutes(result);

  const routeRows = rows.map((r) => `
    <tr>
      <td>${r.name}</td>
      <td>${formatReportNumber(r.length, 3)} km</td>
      <td>${formatReportNumber(r.corridor, 2)} ha</td>
      <td>${formatReportNumber(r.green, 0)} m²</td>
      <td>${formatReportNumber(r.canopy, 0)} m²</td>
      <td>${formatReportNumber(r.water, 0)} m²</td>
      <td>${formatReportNumber(r.crossings, 0)}</td>
      <td>${formatReportNumber(r.buildings, 0)}</td>
      <td>${formatReportNumber(r.env, 2)}</td>
    </tr>`).join("");

  const impactRows = rows.map((r) => `
    <tr>
      <td>${r.name}</td>
      <td>${formatReportNumber(r.treeEquivalent, 1)}</td>
      <td>${formatReportNumber(r.slope, 2)}°</td>
      <td>${formatReportNumber(r.highSlope, 1)}%</td>
      <td>${formatReportNumber(r.buildings, 0)}</td>
      <td>${formatReportNumber(r.heritage, 0)}</td>
      <td>${formatReportNumber(r.water, 0)} m²</td>
      <td>${formatReportNumber(r.crossings, 0)}</td>
    </tr>`).join("");

  const mitigationRows = mitigationRoutes.flatMap((route) =>
    (route?.selected_zones || route?.zones || route?.candidates || []).map((zone) => `
      <tr>
        <td>${route?.route || "Route"}</td>
        <td>${zone?.zone_id || zone?.zone || "Zone"}</td>
        <td>${zone?.intervention || zone?.candidate_type || zone?.type || "Mitigation"}</td>
        <td>${formatReportNumber(zone?.capacity_m2 ?? zone?.area_m2, 1)} m²</td>
        <td>${formatReportNumber(zone?.distance_m ?? zone?.distance_to_construction_m, 1)} m</td>
      </tr>`)
  ).join("");

  const safe = (value) =>
    String(value ?? "").replace(/[<>&"]/g, (c) =>
      ({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c])
    );

  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${safe(project.projectName || "Shuhul Project Report")}</title>
<style>
body{font-family:Arial,sans-serif;color:#17275f;margin:40px;line-height:1.5}
h1{margin-bottom:4px}h2{margin-top:30px;border-bottom:2px solid #568f89;padding-bottom:6px}
table{border-collapse:collapse;width:100%;margin-top:12px}
th,td{border:1px solid #ccd5d5;padding:8px;text-align:left;font-size:12px}
th{background:#e7eee1}.meta{background:#f3ddbd;padding:14px;margin:18px 0}
.note{font-size:12px;color:#555}.summary{font-size:15px}
</style></head>
<body>
<h1>${safe(project.projectName || "Shuhul Project Report")}</h1>
<div class="meta"><b>Construction:</b> ${safe(project.constructionType || "—")} &nbsp; <b>Width:</b> ${formatReportNumber(project.widthMeters, 1)} m &nbsp; <b>District:</b> ${safe(result?.district || "—")}</div>
<h2>Executive Summary</h2><p class="summary">${safe(reportSummary)}</p>
<h2>Route Comparison</h2>
<table><thead><tr><th>Route</th><th>Length</th><th>Corridor</th><th>Green space</th><th>Canopy</th><th>Water</th><th>Crossings</th><th>Buildings</th><th>Environmental cost</th></tr></thead><tbody>${routeRows || '<tr><td colspan="9">No route metrics available.</td></tr>'}</tbody></table>
<h2>Environmental Impact</h2>
<table><thead><tr><th>Route</th><th>Tree-equivalent canopy</th><th>Mean slope</th><th>High slope</th><th>Buildings</th><th>Heritage</th><th>Water area</th><th>Water crossings</th></tr></thead><tbody>${impactRows || '<tr><td colspan="8">No impact metrics available.</td></tr>'}</tbody></table>
<h2>Mitigation Opportunities</h2>
<table><thead><tr><th>Route</th><th>Zone</th><th>Intervention</th><th>Capacity</th><th>Distance</th></tr></thead><tbody>${mitigationRows || '<tr><td colspan="5">No mitigation zone details available.</td></tr>'}</tbody></table>
<h2>Methodology & Assumptions</h2><pre style="white-space:pre-wrap;font-size:11px">${safe(JSON.stringify(result?.impact?.assumptions || result?.mitigation?.assumptions || result?.report?.data?.assumptions || {}, null, 2))}</pre>
<p class="note">Generated by Shuhul. Results are planning-level spatial estimates and should be validated with detailed engineering, ecological and field assessments before implementation.</p>
</body></html>`;
}


interface CreateProjectProps {
  onNavigate: (target: string) => void;
  projectId?: string;
}

export default function CreateProject({
  onNavigate,
  projectId,
}: CreateProjectProps) {
  const [locationA, setLocationA] = useState("");
  const [locationB, setLocationB] = useState("");

  const [projectName, setProjectName] = useState("Untitled Project");
  const [constructionType, setConstructionType] = useState("road");
  const [widthMeters, setWidthMeters] = useState(20);

  const [parameters, setParameters] = useState({
    trees: 60,
    greenery: 60,
    water: 60,
    shortest: 50,
    construction: 50,
  });

  const [selectingPoints, setSelectingPoints] = useState(false);

  const [selectedPoints, setSelectedPoints] = useState({
    A: null,
    B: null,
  });

  const [hardPriorities, setHardPriorities] = useState({
    heritage: false,
    water: false,
    forest: false,
  });

  const [loading, setLoading] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisProjectId, setAnalysisProjectId] = useState(null);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStage, setAnalysisStage] = useState("Preparing analysis...");
  const [errorMessage, setErrorMessage] = useState("");
  useEffect(() => {
  if (!projectId) return;

  async function loadSavedProject() {
    try {
      setLoading(true);
      setErrorMessage("");
      setAnalysisStage("Loading saved project...");

      const project = await apiFetch(`/api/projects/${projectId}`);

      console.log("SHUHUL SAVED PROJECT:", project);

      const result = project?.result;

      if (!result) {
        throw new Error("This project has no saved analysis result.");
      }

      // Restore project inputs
      const savedProject = result.project || project.payload || {};

      if (savedProject.projectName) {
        setProjectName(savedProject.projectName);
      }

      if (savedProject.constructionType) {
        setConstructionType(savedProject.constructionType);
      }

      if (savedProject.widthMeters != null) {
        setWidthMeters(Number(savedProject.widthMeters));
      }

      // Restore Location A / B
      if (savedProject.start) {
        setSelectedPoints((previous) => ({
          ...previous,
          A: savedProject.start,
        }));
      }

      if (savedProject.end) {
        setSelectedPoints((previous) => ({
          ...previous,
          B: savedProject.end,
        }));
      }

      // Restore the COMPLETE saved analysis.
      // This contains:
      // routes, routeGeoJSON, impact, mitigation and report.
      setAnalysisResult(result);

      setAnalysisProjectId(projectId);
      setAnalysisProgress(100);
      setAnalysisStage("Analysis, mitigation and report complete");

    } catch (error) {
      console.error("SHUHUL LOAD PROJECT ERROR:", error);

      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Could not load the saved project."
      );
    } finally {
      setLoading(false);
    }
  }

  loadSavedProject();
}, [projectId]);
  const [mapLayers, setMapLayers] = useState({
    ndvi: false,
    canopy: false,
    water: false,
    slope: false,
    buildings: false,
    routes: true,
    corridors: true,
    mitigation: true,
  });

  const [mitigationLayers, setMitigationLayers] = useState({
    tree: true,
    bush: true,
    roof: true,
  });

  const toggleMapLayer = (name) => {
    setMapLayers((previous) => ({
      ...previous,
      [name]: !previous[name],
    }));
  };

  const toggleMitigationLayer = (name) => {
    setMitigationLayers((previous) => ({
      ...previous,
      [name]: !previous[name],
    }));
  };


  /*
   * Srinagar approximate center.
   * Later this will come from the actual AOI.
   */
  const srinagarCenter = [34.0837, 74.7973];

  // Real raster layer metadata is supplied by Flask after analysis.
  // The backend returns the actual PNG URL + geographic bounds for each raster.
  const [layerManifest, setLayerManifest] = useState(null);
  const [buildingGeoJSON, setBuildingGeoJSON] = useState(null);
  const [corridorGeoJSON, setCorridorGeoJSON] = useState(null);

  useEffect(() => {
    const district =
      analysisResult?.district ||
      analysisResult?.project?.district ||
      analysisResult?.result?.district;

    if (!district) {
      setLayerManifest(null);
      return;
    }

    const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000";
    let cancelled = false;

    fetch(`${apiBase}/api/layers/${district}/manifest`, {
      credentials: "include",
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Layer manifest request failed (${response.status})`);
        return response.json();
      })
      .then((data) => {
        if (!cancelled) setLayerManifest(data);
      })
      .catch((error) => {
        console.error("SHUHUL MAP LAYER MANIFEST ERROR:", error);
        if (!cancelled) setLayerManifest(null);
      });

    return () => {
      cancelled = true;
    };
  }, [analysisResult]);

  useEffect(() => {
    if (!mapLayers.buildings || !analysisResult?.district) return;

    const district = encodeURIComponent(analysisResult.district);
    const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000";

    fetch(`${apiBase}/api/layers/${district}/buildings`, {
      credentials: "include",
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || "Could not load buildings.");
        }
        return data;
      })
      .then((data) => setBuildingGeoJSON(data))
      .catch((error) => {
        console.error("SHUHUL BUILDING LAYER ERROR:", error);
        setBuildingGeoJSON(null);
      });
  }, [mapLayers.buildings, analysisResult?.district]);

  // Construction corridor is generated server-side from the actual Route A/B/C
  // geometries using widthMeters / 2 as the buffer radius.
  useEffect(() => {
    if (!analysisResult?.projectId) return;

    const projectId = encodeURIComponent(analysisResult.projectId);
    const width = Number(
      analysisResult.project.widthMeters || widthMeters || 20
    );
    const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000";

    fetch(
      `${apiBase}/api/projects/${projectId}/corridors?width=${encodeURIComponent(width)}`,
      { credentials: "include" }
    )
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || "Could not load construction corridors.");
        }
        return data;
      })
      .then((data) => setCorridorGeoJSON(data))
      .catch((error) => {
        console.error("SHUHUL CORRIDOR LAYER ERROR:", error);
        setCorridorGeoJSON(null);
      });
  }, [
    analysisResult?.projectId,
    analysisResult?.project?.widthMeters,
    widthMeters,
  ]);

  const rasterLayer = (name) => layerManifest?.layers?.[name] || null;
  const rasterUrl = (name) => {
    const layer = rasterLayer(name);
    if (!layer?.url) return null;
    const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000";
    return layer.url.startsWith("http") ? layer.url : `${apiBase}${layer.url}`;
  };

  const updateParameter = (name, value) => {
    setParameters((previous) => ({
      ...previous,
      [name]: Number(value),
    }));
  };
  const handlePointSelect = (point) => {
    if (!selectedPoints.A) {
    setSelectedPoints({
      A: point,
      B: null,
    });

      return;
    }

    if (!selectedPoints.B) {
    setSelectedPoints((previous) => ({
      ...previous,
      B: point,
    }));

      setSelectingPoints(false);
    }
  };

  const handleSelectPoints = () => {
    setSelectedPoints({
    A: null,
    B: null,
    });

    setLocationA("");
    setLocationB("");

    setSelectingPoints(true);
  };

  const toggleHardPriority = (name) => {
    setHardPriorities((previous) => ({
    ...previous,
    [name]: !previous[name],
    }));
  };

  const handleSubmit = async () => {
    if (!selectedPoints.A || !selectedPoints.B) {
      setErrorMessage("Please select both Location A and Location B.");
      return;
    }

    if (!widthMeters || widthMeters <= 0) {
      setErrorMessage("Please enter a valid project width.");
      return;
    }

    const projectData = {
      projectName,
      constructionType,
      widthMeters: Number(widthMeters),

      start: {
        lat: selectedPoints.A.lat,
        lng: selectedPoints.A.lng,
      },

      end: {
        lat: selectedPoints.B.lat,
        lng: selectedPoints.B.lng,
      },

      softPreferences: {
        treePriority: parameters.trees,
        greeneryPriority: parameters.greenery,
        waterPriority: parameters.water,
        shortestPriority: parameters.shortest,
        constructionPriority: parameters.construction,
      },

      hardConstraints: {
        heritage: hardPriorities.heritage,
        water: hardPriorities.water,
        forest: hardPriorities.forest,
      },
    };

    setLoading(true);
    setErrorMessage("");
    setAnalysisResult(null);
    setAnalysisProjectId(null);
    setAnalysisProgress(5);
    setAnalysisStage("Starting Shuhul analysis...");

    try {
      const apiBase =
        import.meta.env.VITE_API_URL || "http://localhost:5000";

      // The backend starts the long-running pipeline and returns 202.
      const response = await fetch(
        `${apiBase}/api/projects/analyze`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(projectData),
        }
      );

      const created = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          created.message ||
          created.error ||
          "Project analysis could not be started."
        );
      }

      const projectId =
        created.project_id ||
        created.projectId ||
        created.id ||
        created.project?.id;

      if (!projectId) {
        throw new Error(
          "Backend started the analysis but did not return a project ID."
        );
      }

      setAnalysisProjectId(projectId);
      setAnalysisProgress(5);
      setAnalysisStage("Analysis started. Preparing project...");

      // Poll until the background pipeline finishes.
      const maxAttempts = 240; // ~6 minutes at 1.5s
      let completedResult = null;

      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));

        const statusResponse = await fetch(
          `${apiBase}/api/projects/${projectId}/status`,
          {
            credentials: "include",
          }
        );

        const statusData = await statusResponse
          .json()
          .catch(() => ({}));

        if (!statusResponse.ok) {
          throw new Error(
            statusData.message ||
            statusData.error ||
            "Could not read project analysis status."
          );
        }

        // Support both { project: {...} } and a flat status response.
        const project =
          statusData.project ||
          statusData.data ||
          statusData;

        const status = String(
          project.status || statusData.status || ""
        ).toLowerCase();

        // The backend already publishes stage + progress after every major
        // pipeline step. Surface that information instead of showing a
        // static "Analyzing..." message.
        const rawProgress =
          project.progress ??
          statusData.progress ??
          project.progress_percent ??
          statusData.progress_percent;

        const numericProgress = Number(rawProgress);
        if (Number.isFinite(numericProgress)) {
          setAnalysisProgress(Math.max(0, Math.min(100, numericProgress)));
        }

        const currentStage =
          project.stage ||
          statusData.stage ||
          (status === "completed" ? "Analysis complete" : "Running analysis...");
        setAnalysisStage(currentStage);

        if (status === "failed" || status === "error") {
          throw new Error(
            project.error ||
            statusData.error ||
            "Project analysis failed on the backend."
          );
        }

        if (
          status === "completed" ||
          status === "complete"
        ) {
          let result =
            project.result ||
            project.result_json ||
            statusData.result ||
            statusData.result_json;

          if (typeof result === "string") {
            try {
              result = JSON.parse(result);
            } catch {
              throw new Error(
                "Backend completed the project, but its result could not be parsed."
              );
            }
          }

          if (!result) {
            throw new Error(
              "Backend completed the project but returned no analysis result."
            );
          }

          completedResult = result;
          setAnalysisProgress(100);
          setAnalysisStage("Analysis, mitigation and report complete");
          break;
        }
      }

      if (!completedResult) {
        throw new Error(
          "Analysis is taking longer than expected. Please check the project status."
        );
      }

      console.log("SHUHUL FINAL ANALYSIS:", completedResult);
      setAnalysisResult(completedResult);
    } catch (error) {
      console.error("SHUHUL ANALYSIS ERROR:", error);

      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Could not complete the Shuhul analysis."
      );
    } finally {
      setLoading(false);
    }
  };


  const handleDownloadReport = () => {
    if (!analysisResult) return;
    const html = buildDownloadableReport(analysisResult);
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(projectName || "shuhul-project").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-report.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };


  // Later:
  // send projectData to your backend
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

        .dashboard {
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

        .layout {
          display: grid;
          grid-template-columns: 185px 1fr;

          min-height: calc(100vh - 48px);

          border: 3px solid #17275f;
        }

        .sidebar {
          border-right: 3px solid #17275f;
          background: #f7f6f1;
        }

        .logo-container {
          height: 65px;

          display: flex;
          align-items: center;
          justify-content: center;

          border-bottom: 3px solid #17275f;

          background: #e7eee1;
        }

        .logo {
          max-height: 48px;
          width: auto;
        }

        .menu {
          display: flex;
          flex-direction: column;

          gap: 28px;

          padding: 85px 12px;
        }

        .menu button {
          padding: 0;

          border: none;

          text-align: left;

          color: #111;

          background: transparent;

          cursor: pointer;

          font-size: 14px;
        }

        .menu button:hover {
          color: #568f89;
        }

        .content {
          display: flex;
          flex-direction: column;

          min-width: 0;
        }

        .header {
          height: 65px;

          display: flex;
          align-items: center;

          padding: 0 24px;

          border-bottom: 3px solid #17275f;
        }

        .header h1 {
          margin: 0;

          font-size: 32px;
        }

        .main-area {
          display: grid;

          grid-template-columns:
            minmax(400px, 1fr)
            300px;

          gap: 28px;

          padding: 24px 26px 18px 30px;
        }

        .map-section {
          min-width: 0;
        }

        .map-wrapper {
          position: relative;

          width: 100%;

          border: 1px solid #8aa4a5;

          overflow: hidden;
        }

        .map-container {
          width: 100%;
          height: 560px;
        }

        /*
         * Leaflet controls
         */

        .leaflet-control-zoom {
          border: 2px solid #17275f !important;
        }

        .leaflet-control-zoom a {
          color: #17275f !important;
          background: #f7f6f1 !important;
        }

        .leaflet-control-layers {
          border: 1px solid rgba(23, 39, 95, 0.18) !important;
          border-radius: 10px !important;
          background: rgba(255, 255, 255, 0.94) !important;
          box-shadow: 0 8px 22px rgba(23, 39, 95, 0.12) !important;
        }

        .map-layer-panel {
          position: absolute;
          top: 14px;
          right: 14px;
          z-index: 1000;
          width: 190px;
          padding: 10px;
          border: 1px solid rgba(23, 39, 95, 0.15);
          border-radius: 12px;
          background: rgba(255, 255, 255, 0.94);
          box-shadow: 0 8px 24px rgba(23, 39, 95, 0.14);
          backdrop-filter: blur(8px);
        }

        .map-layer-title {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin: 0 2px 8px;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: .08em;
          text-transform: uppercase;
          color: #17275f;
        }

        .map-layer-list {
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
        }

        .map-layer-toggle {
          border: 1px solid #d8dfdf;
          border-radius: 999px;
          padding: 5px 9px;
          background: #fff;
          color: #53606a;
          font-size: 10px;
          line-height: 1;
          cursor: pointer;
          transition: .16s ease;
        }

        .map-layer-toggle:hover {
          border-color: #568f89;
          color: #315f4f;
        }

        .map-layer-toggle.active {
          border-color: #568f89;
          background: #568f89;
          color: #fff;
        }

        .map-layer-toggle.route.active {
          background: #17275f;
          border-color: #17275f;
        }

        .map-layer-toggle.mitigation.active {
          background: #315f4f;
          border-color: #315f4f;
        }

        .mitigation-filter {
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid #e5e8e7;
        }

        .mitigation-filter-label {
          margin-bottom: 5px;
          font-size: 9px;
          color: #77807f;
          text-transform: uppercase;
          letter-spacing: .06em;
        }

        /*
         * Legend
         */

        .map-legend {
          position: absolute;

          left: 12px;
          bottom: 12px;

          z-index: 1000;

          padding: 12px;

          min-width: 150px;

          background: rgba(247, 246, 241, 0.94);

          border: 2px solid #17275f;

          font-size: 12px;

          color: #17275f;
        }

        .legend-title {
          font-weight: bold;

          margin-bottom: 8px;
        }

        .legend-gradient {
          height: 12px;

          width: 120px;

          margin-bottom: 4px;

          background:
            linear-gradient(
              to right,
              #d73027,
              #fee08b,
              #66bd63,
              #1a9850
            );
        }

        .legend-labels {
          display: flex;
          justify-content: space-between;

          width: 120px;
        }

        /*
         * Inputs
         */

        .input-title {
          margin: 20px 0 8px;

          color: #111;

          font-size: 20px;
        }

        .input-row {
          display: grid;

          grid-template-columns:
            1fr
            60px
            1fr;

          align-items: center;

          gap: 12px;
        }

        .input-row input {
          height: 35px;

          padding: 8px 10px;

          border: none;

          background: #f3ddbd;

          outline: none;
        }

        .input-row input:focus {
          outline: 2px solid #568f89;
        }

        .input-row span {
          text-align: center;

          color: #111;

          font-weight: bold;
        }

        /*
         * Parameters
         */

        .parameters {
          min-height: auto;

          padding: 24px 18px;

          background: #f3ddbd;

          color: #111;
        }

        .parameters h2 {
          margin: 0 0 35px;

          font-size: 20px;
        }

        .project-details {
          margin-bottom: 30px;
          padding-bottom: 24px;
          border-bottom: 2px solid rgba(23, 39, 95, 0.2);
        }

        .project-details h3 {
          margin: 0 0 18px;
          font-size: 17px;
        }

        .project-details label {
          display: block;
          margin: 14px 0 7px;
          font-size: 12px;
          font-weight: bold;
        }

        .project-details input,
        .project-details select {
          width: 100%;
          height: 38px;
          padding: 8px 10px;
          border: none;
          background: #f7f6f1;
          color: #17275f;
          outline: none;
          font-size: 13px;
        }

        .project-details input:focus,
        .project-details select:focus {
          outline: 2px solid #568f89;
        }

        .analysis-status {
          margin-top: 14px;
          padding: 10px;
          border: 1px solid rgba(23, 39, 95, 0.25);
          background: rgba(247, 246, 241, 0.75);
          font-size: 12px;
          line-height: 1.5;
        }

        .analysis-progress {
          margin-top: 14px;
          padding: 12px;
          border: 2px solid #17275f;
          background: rgba(247, 246, 241, 0.92);
        }

        .analysis-progress-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 8px;
          color: #17275f;
          font-size: 12px;
          font-weight: bold;
        }

        .analysis-progress-stage {
          margin-bottom: 9px;
          color: #315f4f;
          font-size: 12px;
          line-height: 1.35;
        }

        .analysis-progress-track {
          width: 100%;
          height: 10px;
          overflow: hidden;
          background: #ddd6c9;
          border: 1px solid rgba(23, 39, 95, 0.25);
        }

        .analysis-progress-fill {
          height: 100%;
          background: #568f89;
          transition: width 0.35s ease;
        }

        .analysis-progress-hint {
          margin-top: 7px;
          color: #666;
          font-size: 10px;
        }

        .analysis-error {
          color: #a32626;
          border-color: #a32626;
        }

        .analysis-success {
          color: #315f4f;
          border-color: #568f89;
        }


        .parameter {
          margin-bottom: 28px;
        }

        .parameter-header {
          display: flex;

          justify-content: space-between;

          margin-bottom: 8px;
        }

        .parameter label {
          font-size: 14px;
        }

        .parameter-value {
          font-size: 13px;

          font-weight: bold;

          color: #568f89;
        }

        .parameter input {
          width: 100%;

          accent-color: #568f89;

          cursor: pointer;
        }

        .select-points-button {
          position: absolute;
          top: 12px;
          left: 12px;
          z-index: 1000;
          padding: 10px 16px;
          border: 2px solid #17275f;
          background: #f7f6f1;
          color: #17275f;
          font-size: 13px;
          font-weight: bold;
          cursor: pointer;
        }

        .select-points-button:hover {
          background: #e7eee1;
        }

        .select-points-button.active {
          background: #568f89;
          color: white;
        }

        .hard-priorities {
          margin-top: 38px;
        }

        .hard-priorities h3 {
          margin: 0 0 16px;
          font-size: 15px;
          font-weight: normal;
        }

        .hard-priority-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px 8px;
        }

        .hard-priority-grid label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          cursor: pointer;
        }

        .hard-priority-grid input {
          width: auto;
          margin: 0;
          accent-color: #568f89;
          cursor: pointer;
        }

        .submit-button {
          width: 100%;
          margin-top: 30px;
          padding: 13px 16px;
          border: 2px solid #17275f;
          background: #17275f;
          color: #f7f6f1;
          font-size: 15px;
          font-weight: bold;
          cursor: pointer;
        }

        .submit-button:hover:not(:disabled) {
          background: #568f89;
          border-color: #568f89;
        }

        .submit-button:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }


        .report-section {
          padding: 0 40px 30px;
        }

        .report-panel {
          margin-top: 0;
          padding: 24px;
          background: #f7f6f1;
          border: 2px solid #568f89;
          color: #17275f;
        }

        .report-title-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 12px;
        }

        .report-title-row h2 {
          margin: 0;
          font-size: 24px;
        }

        .report-subtitle {
          margin: 5px 0 0;
          font-size: 12px;
          color: #568f89;
        }

        .report-summary {
          margin: 0 0 14px;
          font-size: 12px;
          line-height: 1.5;
        }

        .report-table-wrap {
          overflow-x: auto;
        }

        .report-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 10px;
          min-width: 650px;
        }

        .report-table th,
        .report-table td {
          padding: 6px;
          border: 1px solid rgba(23, 39, 95, 0.18);
          text-align: left;
          white-space: nowrap;
        }

        .report-table th {
          background: #e7eee1;
        }

        .report-download {
          border: 2px solid #17275f;
          background: #17275f;
          color: #f7f6f1;
          padding: 10px 16px;
          font-size: 12px;
          font-weight: bold;
          cursor: pointer;
        }

        .report-download:hover {
          background: #568f89;
          border-color: #568f89;
        }

        .report-footer-note {
          margin-top: 12px;
          font-size: 11px;
          line-height: 1.5;
          color: #568f89;
        }

        .report-section-heading {
          margin: 20px 0 8px;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: .08em;
          text-transform: uppercase;
          color: #315f4f;
        }

        .impact-card-grid,
        .mitigation-report-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 10px;
        }

        .impact-card,
        .mitigation-report-card {
          border: 1px solid #e1e7e5;
          border-radius: 10px;
          background: #fff;
          padding: 12px;
        }

        .impact-card-title {
          margin-bottom: 9px;
          font-size: 12px;
          font-weight: 800;
        }

        .impact-metrics {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px 10px;
          color: #64706e;
          font-size: 10px;
        }

        .impact-metrics b {
          color: #17275f;
        }

        .mitigation-report-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          font-size: 11px;
        }

        .mitigation-report-header span {
          padding: 3px 7px;
          border-radius: 999px;
          background: #e7eee1;
          color: #315f4f;
          font-size: 9px;
        }

        .mitigation-report-capacity {
          margin: 7px 0 9px;
          color: #315f4f;
          font-size: 10px;
          font-weight: 700;
        }

        .mitigation-report-capacity span {
          font-weight: 400;
          color: #7b8583;
        }

        .mitigation-zone-list {
          display: flex;
          flex-direction: column;
          gap: 5px;
        }

        .mitigation-zone-row {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: center;
          gap: 7px;
          padding: 6px 0;
          border-top: 1px solid #edf0ef;
          color: #596361;
          font-size: 10px;
        }

        .zone-badge {
          padding: 3px 6px;
          border-radius: 5px;
          background: #f3ddbd;
          color: #17275f;
          font-weight: 800;
          font-size: 9px;
        }


        @media (max-width: 900px) {

          .layout {
            grid-template-columns: 1fr;
          }

          .sidebar {
            display: none;
          }

          .main-area {
            grid-template-columns: 1fr;

            padding: 20px;
          }

          .parameters {
            min-height: auto;
          }

          .report-section {
            padding: 0 20px 20px;
          }

          .report-title-row {
            align-items: flex-start;
            flex-direction: column;
          }

          .report-download {
            width: 100%;
          }

          .impact-card-grid,
          .mitigation-report-grid {
            grid-template-columns: 1fr;
          }

        }

      `}</style>

      <main className="dashboard">

        <div className="layout">

          {/* SIDEBAR */}

          <aside className="sidebar">

            <div className="logo-container">
              <img
                className="logo"
                src="/logo.png"
                alt="Shuhul"
              />
            </div>

            <nav className="menu">

              {[
                "Home",
                "AOI Analysis",
                "Environmental Watch",
                "Ecological Stress",
                "Thermal Compensation",
                "Environmental Analysis",
                "Settings",
              ].map((item) => (
                <button
                  key={item}
                  onClick={() =>
                    onNavigate(
                      item === "Home"
                        ? "home"
                        : item === "AOI Analysis"
                        ? "aoi"
                        : item === "Environmental Watch"
                        ? "environmental-watch"
                        : item === "Ecological Stress"
                        ? "ecological-stress"
                        : item === "Settings"
                        ? "settings"
                        : "home"
                    )
                  }
                >
                  {item}
                </button>
              ))}

            </nav>

          </aside>


          {/* MAIN CONTENT */}

          <section className="content">

            <header className="header">
              <h1>{projectName}</h1>
            </header>


            <div className="main-area">

              {/* MAP */}

              <section className="map-section">

               <div className="map-wrapper">

                  <button
                    type="button"
                    className={`select-points-button ${
                      selectingPoints ? "active" : ""
                    }`}
                    onClick={handleSelectPoints}
                  >
                    {selectingPoints
                      ? selectedPoints.A
                        ? "Select Location B"
                        : "Select Location A"
                      : "Select Points"}
                  </button>
                    
                  <MapContainer
                    center={srinagarCenter}
                    zoom={12}
                    zoomControl={false}
                    className="map-container"
                  >
                  <MapPointSelector
                    selectingPoints={selectingPoints}
                    onPointSelect={handlePointSelect}
                  />
                  <FitResultsToMap
                    routeGeoJSON={analysisResult?.routeGeoJSON}
                  />
                  {selectedPoints.A && (
                  <CircleMarker
                    center={[
                      selectedPoints.A.lat,
                      selectedPoints.A.lng,
                    ]}
                    radius={9}
                    pathOptions={{
                      color: "#17275f",
                      fillColor: "#17275f",
                      fillOpacity: 1,
                    }}
                  >
                    <Popup>
                      <strong>Location A</strong>
                      <br />
                      {selectedPoints.A.lat.toFixed(5)},{" "}
                      {selectedPoints.A.lng.toFixed(5)}
                    </Popup>
                  </CircleMarker>
                  )}

                  {selectedPoints.B && (
                  <CircleMarker
                    center={[
                      selectedPoints.B.lat,
                      selectedPoints.B.lng,
                    ]}
                    radius={9}
                    pathOptions={{
                      color: "#568f89",
                      fillColor: "#568f89",
                      fillOpacity: 1,
                    }}
                  >
                    <Popup>
                      <strong>Location B</strong>
                      <br />
                      {selectedPoints.B.lat.toFixed(5)},{" "}
                      {selectedPoints.B.lng.toFixed(5)}
                    </Popup>
                  </CircleMarker>
                  )}
                  
                    {/* BASE MAP */}
                    <LayersControl position="bottomright">
                      <BaseLayer checked name="Humanitarian">
                        <TileLayer
                          url="https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png"
                          attribution='&copy; OpenStreetMap contributors, Tiles style by Humanitarian OSM Team'
                        />
                      </BaseLayer>
                      <BaseLayer name="OpenStreetMap">
                        <TileLayer
                          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                          attribution="&copy; OpenStreetMap contributors"
                        />
                      </BaseLayer>
                    </LayersControl>

                    {mapLayers.ndvi && rasterLayer("ndvi") && (
                      <ImageOverlay
                        url={rasterUrl("ndvi")}
                        bounds={rasterLayer("ndvi").bounds}
                        opacity={0.58}
                        zIndex={10}
                      />
                    )}

                    {mapLayers.canopy && rasterLayer("canopy") && (
                      <ImageOverlay
                        url={rasterUrl("canopy")}
                        bounds={rasterLayer("canopy").bounds}
                        opacity={0.52}
                        zIndex={11}
                      />
                    )}

                    {mapLayers.water && rasterLayer("water") && (
                      <ImageOverlay
                        url={rasterUrl("water")}
                        bounds={rasterLayer("water").bounds}
                        opacity={0.68}
                        zIndex={12}
                      />
                    )}

                    {mapLayers.slope && rasterLayer("slope") && (
                      <ImageOverlay
                        url={rasterUrl("slope")}
                        bounds={rasterLayer("slope").bounds}
                        opacity={0.48}
                        zIndex={9}
                      />
                    )}

                    {mapLayers.buildings && buildingGeoJSON && (
                      <GeoJSON
                        data={buildingGeoJSON}
                        style={{
                          color: "#17275f",
                          weight: 1,
                          fillColor: "#ffffff",
                          fillOpacity: 0.18,
                        }}
                      />
                    )}

                    {mapLayers.corridors && corridorGeoJSON && (
                      <GeoJSON
                        data={corridorGeoJSON}
                        style={(feature) => {
                          const route = String(feature?.properties?.route || "");
                          if (route.startsWith("Route A")) {
                            return {
                              color: "#d73027",
                              weight: 1,
                              fillColor: "#d73027",
                              fillOpacity: 0.12,
                            };
                          }
                          if (route.startsWith("Route B")) {
                            return {
                              color: "#f2b134",
                              weight: 1,
                              fillColor: "#f2b134",
                              fillOpacity: 0.12,
                            };
                          }
                          return {
                            color: "#168aad",
                            weight: 1,
                            fillColor: "#168aad",
                            fillOpacity: 0.12,
                          };
                        }}
                      />
                    )}

                    {mapLayers.routes && analysisResult?.routeGeoJSON && (
                      <GeoJSON
                        data={analysisResult.routeGeoJSON}
                        style={(feature) => {
                          const route = String(feature?.properties?.route || "");
                          if (route.startsWith("Route A")) {
                            return { color: "#d73027", weight: 5, opacity: 0.95 };
                          }
                          if (route.startsWith("Route B")) {
                            return { color: "#f2b134", weight: 5, opacity: 0.95 };
                          }
                          return { color: "#168aad", weight: 5, opacity: 0.95 };
                        }}
                        onEachFeature={(feature, layer) => {
                          const p = feature.properties || {};
                          layer.bindPopup(`
                            <strong>${p.route || "Route"}</strong><br/>
                            Distance: ${p.distance_km ?? "—"} km<br/>
                            Environmental Cost: ${p.environmental_cost ?? "—"}
                          `);
                        }}
                      />
                    )}

                    {mapLayers.mitigation && analysisResult?.mitigation?.geojson && (
                      <GeoJSON
                        data={analysisResult.mitigation.geojson}
                        filter={(feature) => {
                          const intervention = String(
                            feature?.properties?.intervention ||
                            feature?.properties?.candidate_type ||
                            feature?.properties?.type ||
                            ""
                          ).toLowerCase();

                          if (intervention.includes("tree")) return mitigationLayers.tree;
                          if (intervention.includes("bush") || intervention.includes("shrub")) return mitigationLayers.bush;
                          if (intervention.includes("roof")) return mitigationLayers.roof;
                          return true;
                        }}
                        style={(feature) => {
                          const intervention = String(
                            feature?.properties?.intervention ||
                            feature?.properties?.candidate_type ||
                            feature?.properties?.type ||
                            ""
                          ).toLowerCase();

                          if (intervention.includes("tree")) {
                            return { color: "#1b7f3a", weight: 2, fillColor: "#1b7f3a", fillOpacity: 0.30 };
                          }
                          if (intervention.includes("bush") || intervention.includes("shrub")) {
                            return { color: "#8bc34a", weight: 2, fillColor: "#8bc34a", fillOpacity: 0.30 };
                          }
                          if (intervention.includes("roof")) {
                            return { color: "#9c27b0", weight: 2, fillColor: "#9c27b0", fillOpacity: 0.30 };
                          }
                          return { color: "#607d8b", weight: 2, fillOpacity: 0.25 };
                        }}
                        onEachFeature={(feature, layer) => {
                          const p = feature.properties || {};
                          const intervention =
                            p.intervention || p.candidate_type || p.type || "Mitigation zone";
                          const zone = p.zone_id || p.zone || "Mitigation Zone";
                          layer.bindPopup(`
                            <strong>${zone}</strong><br/>
                            ${intervention}<br/>
                            Capacity: ${p.capacity_m2 ?? p.area_m2 ?? "—"} m²
                          `);
                        }}
                      />
                    )}

                    {/* MAP LAYERS */}
                    <div className="map-layer-panel">
                      <div className="map-layer-title">
                        <span>Map layers</span>
                        <span style={{ opacity: .45 }}>●</span>
                      </div>

                      <div className="map-layer-list">
                        {[
                          ["ndvi", "NDVI"],
                          ["canopy", "Canopy"],
                          ["water", "Water"],
                          ["slope", "Slope"],
                          ["buildings", "Buildings"],
                          ["routes", "Routes A / B / C"],
                          ["corridors", "20 m Corridors"],
                          ["mitigation", "Mitigation"],
                        ].map(([key, label]) => (
                          <button
                            key={key}
                            type="button"
                            className={`map-layer-toggle ${key === "routes" ? "route" : ""} ${key === "mitigation" ? "mitigation" : ""} ${mapLayers[key] ? "active" : ""}`}
                            onClick={() => toggleMapLayer(key)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>

                      {mapLayers.mitigation && (
                        <div className="mitigation-filter">
                          <div className="mitigation-filter-label">Mitigation type</div>
                          <div className="map-layer-list">
                            {[
                              ["tree", "Trees"],
                              ["bush", "Bushes"],
                              ["roof", "Roofs"],
                            ].map(([key, label]) => (
                              <button
                                key={key}
                                type="button"
                                className={`map-layer-toggle ${mitigationLayers[key] ? "active" : ""}`}
                                onClick={() => toggleMitigationLayer(key)}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* MAP CONTROLS */}

                    <ZoomControl position="bottomright" />

                    <ScaleControl position="bottomright" />

                  </MapContainer>


                  {/* LEGEND */}

                  <div className="map-legend">

                    <div className="legend-title">
                      NDVI
                    </div>

                    <div className="legend-gradient" />

                    <div className="legend-labels">
                      <span>Low</span>
                      <span>High</span>
                    </div>

                  </div>

                </div>


                {/* LOCATION INPUT */}

                <h3 className="input-title">
                  Input
                </h3>


                <div className="input-row">

                  <input
                    value={
                      selectedPoints.A
                        ? `${selectedPoints.A.lat.toFixed(5)}, ${selectedPoints.A.lng.toFixed(5)}`
                        : locationA
                    }
                    onChange={(e) => setLocationA(e.target.value)}
                    placeholder="Location A"
                  />

                  <span>
                    to
                  </span>

                  <input
                    value={
                      selectedPoints.B
                        ? `${selectedPoints.B.lat.toFixed(5)}, ${selectedPoints.B.lng.toFixed(5)}`
                        : locationB
                    }
                    onChange={(e) => setLocationB(e.target.value)}
                    placeholder="Location B"
                  />

                </div>

                <div style={{
                  marginTop: "8px",
                  fontSize: "11px",
                  color: "#568f89"
                }}>
                  Select points on the map or enter coordinates.
                </div>

              </section>


              {/* PARAMETERS */}

              <aside className="parameters">

                <h2>
                  Project Setup
                </h2>

                <div className="project-details">

                  <h3>Project Details</h3>

                  <input
                    type="text"
                    value={projectName}
                    onChange={(e) =>
                      setProjectName(e.target.value)
                    }
                    placeholder="Project Name"
                  />

                  <label htmlFor="construction-type">
                    Construction Type
                  </label>

                  <select
                    id="construction-type"
                    value={constructionType}
                    onChange={(e) =>
                      setConstructionType(e.target.value)
                    }
                  >
                    <option value="road">Road</option>
                    <option value="bridge">Bridge</option>
                    <option value="flyover">Flyover</option>
                  </select>

                  <label htmlFor="width-meters">
                    Project Width (metres)
                  </label>

                  <input
                    id="width-meters"
                    type="number"
                    min="1"
                    max="200"
                    step="0.5"
                    value={widthMeters}
                    onChange={(e) =>
                      setWidthMeters(Number(e.target.value))
                    }
                  />

                </div>

                <h2>
                  Parameters
                </h2>

                <div className="parameter">

                  <div className="parameter-header">
                    <label>Tree Priority</label>

                    <span className="parameter-value">
                      {parameters.trees}
                    </span>
                  </div>

                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={parameters.trees}
                    onChange={(e) =>
                      updateParameter("trees", e.target.value)
                    }
                  />

                </div>

                <div className="parameter">

                  <div className="parameter-header">
                    <label>Greenery Priority</label>

                    <span className="parameter-value">
                      {parameters.greenery}
                    </span>
                  </div>

                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={parameters.greenery}
                    onChange={(e) =>
                      updateParameter("greenery", e.target.value)
                    }
                  />

                </div>

                <div className="parameter">

                  <div className="parameter-header">
                    <label>Water Priority</label>

                    <span className="parameter-value">
                      {parameters.water}
                    </span>
                  </div>

                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={parameters.water}
                    onChange={(e) =>
                      updateParameter("water", e.target.value)
                    }
                  />

                </div>

                <div className="parameter">

                  <div className="parameter-header">
                    <label>Shortest Route Priority</label>

                    <span className="parameter-value">
                      {parameters.shortest}
                    </span>
                  </div>

                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={parameters.shortest}
                    onChange={(e) =>
                      updateParameter("shortest", e.target.value)
                    }
                  />

                </div>

                <div className="parameter">

                  <div className="parameter-header">
                    <label>Construction Cost Priority</label>

                    <span className="parameter-value">
                      {parameters.construction}
                    </span>
                  </div>

                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={parameters.construction}
                    onChange={(e) =>
                      updateParameter(
                        "construction",
                        e.target.value
                      )
                    }
                  />

                </div>

                <div className="hard-priorities">

                  <h3>
                    Hard Constraints
                  </h3>

                  <div className="hard-priority-grid">

                    <label>
                      <input
                        type="checkbox"
                        checked={hardPriorities.heritage}
                        onChange={() =>
                          toggleHardPriority("heritage")
                        }
                      />
                      Heritage Buildings
                    </label>

                    <label>
                      <input
                        type="checkbox"
                        checked={hardPriorities.water}
                        onChange={() =>
                          toggleHardPriority("water")
                        }
                      />
                      Water Bodies
                    </label>

                    <label>
                      <input
                        type="checkbox"
                        checked={hardPriorities.forest}
                        onChange={() =>
                          toggleHardPriority("forest")
                        }
                      />
                      Forest / Vegetation
                    </label>

                  </div>

                </div>

                <button
                  type="button"
                  className="submit-button"
                  onClick={handleSubmit}
                  disabled={
                    !selectedPoints.A ||
                    !selectedPoints.B ||
                    loading
                  }
                >
                  {loading
                    ? "Analyzing Project..."
                    : "Analyze Project"}
                </button>

                {loading && (
                  <div className="analysis-progress">
                    <div className="analysis-progress-header">
                      <span>Shuhul Analysis</span>
                      <span>{Math.round(analysisProgress)}%</span>
                    </div>

                    <div className="analysis-progress-stage">
                      {analysisStage}
                    </div>

                    <div
                      className="analysis-progress-track"
                      role="progressbar"
                      aria-valuemin="0"
                      aria-valuemax="100"
                      aria-valuenow={Math.round(analysisProgress)}
                    >
                      <div
                        className="analysis-progress-fill"
                        style={{ width: `${Math.max(2, analysisProgress)}%` }}
                      />
                    </div>

                    <div className="analysis-progress-hint">
                      Cost surface → Route A/B/C → environmental impact
                      → mitigation → report
                    </div>

                    {analysisProjectId && (
                      <div className="analysis-progress-hint">
                        Project ID: {analysisProjectId}
                      </div>
                    )}
                  </div>
                )}

                {errorMessage && !loading && (
                  <div className="analysis-status analysis-error">
                    {errorMessage}
                  </div>
                )}

                {analysisResult && !loading && (
                  <div className="analysis-status analysis-success">
                    <strong>Analysis complete.</strong>
                    <br />
                    Route A, Route B, Route C and mitigation results are now
                    displayed on the map.
                  </div>
                )}

              </aside>

            </div>

            {analysisResult && !loading && (
              <section className="report-section">
                <div className="report-panel">
                  <div className="report-title-row">
                    <div>
                      <h2>Project Report</h2>
                      <p className="report-subtitle">
                        Route comparison, environmental impact and mitigation summary
                      </p>
                    </div>
                    <button
                      type="button"
                      className="report-download"
                      onClick={handleDownloadReport}
                    >
                      Download Report
                    </button>
                  </div>

                  <p className="report-summary">
                    {(() => {
                      const summary = analysisResult?.report?.summary;
                      if (typeof summary === "string") return summary;
                      if (summary && typeof summary === "object") {
                        return `Analysis completed for ${summary.routes_analyzed ?? getReportRouteRows(analysisResult).length} routes, with ${formatReportNumber(summary.mitigation_zones_across_routes, 0)} mitigation zones and ${formatReportNumber(summary.mitigation_capacity_m2_across_routes, 0)} m² of mitigation capacity identified.`;
                      }
                      return "The analysis report has been prepared from the route, impact and mitigation results.";
                    })()}
                  </p>

                  <div className="report-section-heading">Route comparison</div>
                  <div className="report-table-wrap">
                    <table className="report-table">
                      <thead>
                        <tr>
                          <th>Route</th>
                          <th>Length</th>
                          <th>Corridor</th>
                          <th>Green</th>
                          <th>Canopy</th>
                          <th>Water</th>
                          <th>Crossings</th>
                          <th>Buildings</th>
                          <th>Env. Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {getReportRouteRows(analysisResult).map((row) => (
                          <tr key={row.name}>
                            <td>{row.name}</td>
                            <td>{formatReportNumber(row.length, 3)} km</td>
                            <td>{formatReportNumber(row.corridor, 2)} ha</td>
                            <td>{formatReportNumber(row.green, 0)} m²</td>
                            <td>{formatReportNumber(row.canopy, 0)} m²</td>
                            <td>{formatReportNumber(row.water, 0)} m²</td>
                            <td>{formatReportNumber(row.crossings, 0)}</td>
                            <td>{formatReportNumber(row.buildings, 0)}</td>
                            <td>{formatReportNumber(row.env, 2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="report-section-heading">Environmental impact</div>
                  <div className="impact-card-grid">
                    {getReportRouteRows(analysisResult).map((row) => (
                      <div className="impact-card" key={`impact-${row.name}`}>
                        <div className="impact-card-title">{row.name}</div>
                        <div className="impact-metrics">
                          <span><b>{formatReportNumber(row.treeEquivalent, 1)}</b> tree-equivalent canopy</span>
                          <span><b>{formatReportNumber(row.green, 0)} m²</b> green space</span>
                          <span><b>{formatReportNumber(row.canopy, 0)} m²</b> canopy</span>
                          <span><b>{formatReportNumber(row.water, 0)} m²</b> water</span>
                          <span><b>{formatReportNumber(row.crossings, 0)}</b> water crossings</span>
                          <span><b>{formatReportNumber(row.buildings, 0)}</b> buildings</span>
                          <span><b>{formatReportNumber(row.heritage, 0)}</b> heritage conflicts</span>
                          <span><b>{formatReportNumber(row.slope, 2)}°</b> mean slope</span>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="report-section-heading">Mitigation opportunities</div>
                  <div className="mitigation-report-grid">
                    {getMitigationRoutes(analysisResult).map((route) => (
                      <div className="mitigation-report-card" key={`mitigation-${route.route}`}>
                        <div className="mitigation-report-header">
                          <strong>{route.route}</strong>
                          <span>
                            {formatReportNumber(route?.candidate_summary?.selected_zone_count, 0)} zones
                          </span>
                        </div>
                        <div className="mitigation-report-capacity">
                          {formatReportNumber(route?.candidate_summary?.selected_capacity_m2, 0)} m² capacity
                          <span> · search radius {formatReportNumber(route?.search_radius_m, 0)} m</span>
                        </div>
                        <div className="mitigation-zone-list">
                          {(route?.selected_zones || []).map((zone, index) => (
                            <div className="mitigation-zone-row" key={zone?.zone_id || index}>
                              <span className="zone-badge">{zone?.zone_id || `Zone ${index + 1}`}</span>
                              <span>{getInterventionLabel(zone)}</span>
                              <span>{formatReportNumber(zone?.capacity_m2 ?? zone?.area_m2, 0)} m²</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="report-footer-note">
                    Planning-level spatial analysis. Thermal compensation is not yet run in this pipeline.
                    Environmental and mitigation results should be validated with detailed engineering,
                    ecological and field assessments before implementation.
                  </div>
                </div>
              </section>
            )}

          </section>

        </div>

      </main>
    </>
  );
}