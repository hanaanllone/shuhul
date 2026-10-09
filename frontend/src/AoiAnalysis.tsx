import { useCallback, useEffect, useRef, useState } from "react";
import type { Layer, Map as LeafletMap } from "leaflet";
import type { Feature, Polygon } from "geojson";

import {
  MapContainer,
  TileLayer,
  LayersControl,
  ZoomControl,
  ScaleControl,
  useMap,
} from "react-leaflet";

import "@geoman-io/leaflet-geoman-free";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import "leaflet/dist/leaflet.css";

const { BaseLayer } = LayersControl;
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
type AOISource = "district" | "custom";

interface AOIData {
  source: AOISource;
  district?: string;
  layer?: Layer;
  geojson?: Feature<Polygon>;
}
interface AOIAnalysisResult {
  district: string;
  scope: "district" | "aoi";

  area: {
    value_km2: number;
    value_m2: number;
  };

  mean_ndvi: number | null;
  mean_ndwi: number | null;

  canopy_cover: {
    percentage: number | null;
    area_m2: number | null;
  };

  built_up_density: {
    percentage: number | null;
    building_features_intersecting_aoi: number;
  };

  water_cover: {
    percentage: number | null;
    area_m2: number | null;
  };
}
interface MapDrawingControlsProps {
  onAOICreated: (aoi: AOIData | null) => void;
  onMapReady: (map: LeafletMap) => void;
}

interface GeomanCreateEvent {
  layer: Layer;
}

/*
 * Leaflet-Geoman extends Leaflet's Map with `pm`.
 * If TypeScript reports that `pm` does not exist on Map,
 * add src/types/leaflet-geoman.d.ts:
 *
 * import "leaflet";
 * declare module "leaflet" {
 *   interface Map {
 *     pm: any;
 *   }
 * }
 */

function MapDrawingControls({
  onAOICreated,
  onMapReady,
}: MapDrawingControlsProps) {
  const map = useMap();
  const currentLayerRef = useRef<Layer | null>(null);

  const publishCurrentAOI = useCallback(() => {
    const layer = currentLayerRef.current;

    if (!layer) return;

    const geojson = layer.toGeoJSON() as Feature<Polygon>;

    onAOICreated({
      source: "custom",
      layer,
      geojson,
    });
  }, [onAOICreated]);

  useEffect(() => {
    onMapReady(map);

    map.pm.addControls({
      position: "topleft",
      drawText: false,
      drawCircle: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawMarker: false,
      drawRectangle: true,
      drawPolygon: true,
      editMode: true,
      dragMode: true,
      cutPolygon: false,
      removalMode: true,
    });

    const handleCreate = (event: GeomanCreateEvent) => {
      const newLayer = event.layer;

      if (currentLayerRef.current) {
        map.removeLayer(currentLayerRef.current);
      }

      currentLayerRef.current = newLayer;

      newLayer.setStyle?.({
        color: "#17275f",
        weight: 3,
        fillColor: "#568f89",
        fillOpacity: 0.22,
      });

      publishCurrentAOI();
    };

    const handleEdit = () => {
      publishCurrentAOI();
    };

    const handleDragEnd = () => {
      publishCurrentAOI();
    };

    const handleRemove = () => {
      currentLayerRef.current = null;
      onAOICreated(null);
    };

    map.on("pm:create", handleCreate);
    map.on("pm:edit", handleEdit);
    map.on("pm:dragend", handleDragEnd);
    map.on("pm:remove", handleRemove);

    return () => {
      map.off("pm:create", handleCreate);
      map.off("pm:edit", handleEdit);
      map.off("pm:dragend", handleDragEnd);
      map.off("pm:remove", handleRemove);

      if (map.pm) {
        map.pm.removeControls();
      }
    };
  }, [map, onAOICreated, onMapReady, publishCurrentAOI]);

  return null;
}

interface AOIAnalysisProps {
  onNavigate?: (path: string) => void;
}

export default function AOIAnalysis({
  onNavigate = () => {},
}: AOIAnalysisProps) {
  const [selectedDistrict, setSelectedDistrict] = useState<string>("");
  const [aoi, setAoi] = useState<AOIData | null>(null);
  const [analysed, setAnalysed] = useState<boolean>(false);
  const [map, setMap] = useState<LeafletMap | null>(null);

  const [analysisResult, setAnalysisResult] =
    useState<AOIAnalysisResult | null>(null);

  const [analysisLoading, setAnalysisLoading] =
    useState<boolean>(false);

  const [analysisError, setAnalysisError] =
    useState<string>("");

  const resultsRef = useRef<HTMLElement | null>(null);

  const srinagarCenter: [number, number] = [34.0837, 74.7973];

  const districts: string[] = [
    "Srinagar",
    "Budgam",
    "Ganderbal",
    "Pulwama",
    "Baramulla",
    "Anantnag",
  ];

  const handleAOICreated = useCallback((newAOI: AOIData | null) => {
    setAoi(newAOI);
    setAnalysed(false);

    if (newAOI) {
      setSelectedDistrict("");
    }
  }, []);

  const handleMapReady = useCallback((mapInstance: LeafletMap) => {
    setMap(mapInstance);
  }, []);

  const clearCustomAOI = () => {
    if (map?.pm) {
      map.pm.disableDraw();
      map.pm.disableGlobalEditMode();
      map.pm.disableGlobalDragMode();
    }

    if (aoi?.layer && map) {
      map.removeLayer(aoi.layer);
    }

    setAoi(null);
    setAnalysed(false);
  };

  const startRectangle = () => {
    if (!map?.pm) return;

    setSelectedDistrict("");
    setAnalysed(false);

    map.pm.disableDraw();
    map.pm.enableDraw("Rectangle", {
      snappable: true,
      allowSelfIntersection: false,
    });
  };

  const startPolygon = () => {
    if (!map?.pm) return;

    setSelectedDistrict("");
    setAnalysed(false);

    map.pm.disableDraw();
    map.pm.enableDraw("Polygon", {
      snappable: true,
      allowSelfIntersection: false,
    });
  };

  const enableEdit = () => {
    if (!map?.pm || !aoi?.layer) return;

    map.pm.enableGlobalEditMode();
  };

  const enableDrag = () => {
    if (!map?.pm || !aoi?.layer) return;

    map.pm.enableGlobalDragMode();
  };

  const handleDistrictChange = (
    event: React.ChangeEvent<HTMLSelectElement>,
  ) => {
    const district = event.target.value;

    setSelectedDistrict(district);
    setAnalysed(false);

    if (district && aoi?.layer && map) {
      map.removeLayer(aoi.layer);
    }

    if (district) {
      setAoi({
        source: "district",
        district,
      });
    } else {
      setAoi(null);
    }
  };

  const scrollToResults = () => {
    window.setTimeout(() => {
      resultsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 100);
  };

  const handleAnalyse = async () => {
    if (!selectedDistrict && !aoi?.geojson) {
      alert("Please select a district or create your own AOI.");
      return;
    }
  
    setAnalysisLoading(true);
    setAnalysisError("");
    setAnalysed(false);
    setAnalysisResult(null);
  
    try {
      const apiBase =
        import.meta.env.VITE_API_URL || "http://localhost:5000";
    
      let payload: Record<string, unknown>;
      const districtCode = districtCodes[selectedDistrict];
      if (districtCode) {
        // --------------------------------------------------
        // DISTRICT ANALYSIS
        // --------------------------------------------------
        payload = {
          district: districtCode,
        };
      } else {
        // --------------------------------------------------
        // CUSTOM AOI ANALYSIS
        // --------------------------------------------------
        payload = {
          district:  "sxr",
          geometry: aoi?.geojson,
        };
      }
    
      const response = await fetch(
        `${apiBase}/api/aoi/analyse`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify(payload),
        }
      );
    
      const data = await response.json();
    
      if (!response.ok) {
        throw new Error(
          data?.error || "AOI analysis failed."
        );
      }
    
      setAnalysisResult(data);
      setAnalysed(true);
    
      scrollToResults();
    
    } catch (error) {
    
      console.error("AOI ANALYSIS ERROR:", error);
    
      setAnalysisError(
        error instanceof Error
          ? error.message
          : "Could not analyse AOI."
      );
    
    } finally {
      setAnalysisLoading(false);
    }

    /*
     * Later:
     *
     * District:
     *   POST /api/aoi/analyse
     *   { source: "district", district: selectedDistrict }
     *
     * Custom:
     *   POST /api/aoi/analyse
     *   { source: "custom", geometry: aoi.geojson }
     *
     * The backend will clip the aligned GIS layers and return
     * the real environmental statistics.
     */
  };

  const analysisLabel = selectedDistrict
    ? selectedDistrict
    : "Custom AOI";

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
          grid-template-columns: 180px 1fr;
          min-height: calc(100vh - 48px);
          border: 3px solid #17275f;
        }

        .sidebar {
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
          margin-left: 10px;
          margin-top: 8px;
          width: 60px;
        }

        .menu {
          display: flex;
          flex-direction: column;
          gap: 28px;
          padding: 72px 8px;
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

        .menu button:hover,
        .menu .active {
          color: #568f89;
        }

        .content {
          min-width: 0;
          display: flex;
          flex-direction: column;
        }

        .header {
          height: 56px;
          display: flex;
          align-items: center;
          padding: 0 20px;
          border-bottom: 3px solid #17275f;
        }

        .header h1 {
          margin: 0;
          font-size: 30px;
        }

        .main-area {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 25px 30px 45px;
        }

        .map-and-tools {
          width: min(1080px, 100%);
          display: grid;
          grid-template-columns: minmax(0, 1fr) 245px;
          gap: 18px;
          align-items: stretch;
        }

        .map-wrapper {
          position: relative;
          min-width: 0;
          border: 1px solid #8aa4a5;
          overflow: hidden;
        }

        .map-container {
          width: 100%;
          height: 520px;
        }

        .aoi-tools {
          padding: 22px 18px;
          background: #f3ddbd;
          color: #111;
        }

        .aoi-tools h2 {
          margin: 0 0 8px;
          color: #17275f;
          font-size: 21px;
        }

        .aoi-tools > p {
          margin: 0 0 22px;
          color: #555;
          font-size: 12px;
          line-height: 1.5;
        }

        .tool-label {
          margin: 18px 0 8px;
          color: #17275f;
          font-size: 13px;
          font-weight: bold;
        }

        .tool-buttons {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }

        .tool-button {
          min-height: 38px;
          border: 2px solid #17275f;
          background: #f7f6f1;
          color: #17275f;
          font-size: 11px;
          font-weight: bold;
          cursor: pointer;
        }

        .tool-button:hover {
          background: #e7eee1;
        }

        .tool-button:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }

        .tool-button.full {
          grid-column: span 2;
        }

        .aoi-status {
          margin-top: 18px;
          padding: 11px;
          border: 1px solid #8aa4a5;
          background: #f7f6f1;
          color: #555;
          font-size: 11px;
          line-height: 1.5;
        }

        .aoi-status strong {
          color: #17275f;
        }

        .analyse-custom-button {
          width: 100%;
          margin-top: 18px;
          padding: 12px;
          border: none;
          background: #568f89;
          color: white;
          font-size: 13px;
          font-weight: bold;
          cursor: pointer;
        }

        .analyse-custom-button:hover {
          background: #17275f;
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

        /*
         * Make Geoman feel closer to the rest of the interface.
         */

        .leaflet-pm-toolbar {
          border: 2px solid #17275f !important;
        }

        .leaflet-pm-toolbar a {
          background: #f7f6f1 !important;
        }

        .leaflet-pm-toolbar a:hover {
          background: #e7eee1 !important;
        }

        /*
         * District section
         */

        .district-section {
          width: min(1080px, 100%);
          margin-top: 20px;
        }

        .section-divider {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 18px 0;
          color: #777;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }

        .section-divider::before,
        .section-divider::after {
          content: "";
          height: 1px;
          flex: 1;
          background: #b7c4c2;
        }

        .district-title {
          margin: 0 0 8px;
          color: #111;
          font-size: 20px;
        }

        .district-row {
          display: grid;
          grid-template-columns: 1fr 105px;
          gap: 12px;
        }

        .district-select {
          height: 35px;
          padding: 8px 10px;
          border: none;
          background: #f3ddbd;
          color: #111;
          outline: none;
        }

        .district-select:focus {
          outline: 2px solid #568f89;
        }

        .analyse-button {
          height: 35px;
          border: none;
          background: #568f89;
          color: white;
          font-size: 13px;
          font-weight: bold;
          cursor: pointer;
        }

        .analyse-button:hover {
          background: #17275f;
        }

        .aoi-info {
          width: min(1080px, 100%);
          margin-top: 10px;
          color: #555;
          font-size: 11px;
        }

        /*
         * Results
         */

        .results {
          width: calc(100% + 60px);
          margin-top: 35px;
          padding: 35px 40px;
          border-top: 3px solid #17275f;
          background: #e7eee1;
        }

        .results-inner {
          max-width: 900px;
          margin: auto;
        }

        .results h2 {
          margin: 0 0 8px;
          font-size: 27px;
        }

        .results-subtitle {
          margin: 0 0 25px;
          color: #555;
          font-size: 13px;
        }

        .result-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 15px;
        }

        .result-card {
          padding: 20px;
          background: #f7f6f1;
          border: 2px solid #17275f;
        }

        .result-card-title {
          margin-bottom: 12px;
          color: #555;
          font-size: 12px;
        }

        .result-card-value {
          color: #17275f;
          font-size: 25px;
          font-weight: bold;
        }

        .result-card-unit {
          margin-left: 4px;
          color: #568f89;
          font-size: 12px;
        }

        .stress-card {
          grid-column: span 3;
          padding: 20px;
          background: #f3ddbd;
          border: 2px solid #17275f;
        }

        .stress-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 10px;
        }

        .stress-value {
          font-weight: bold;
          color: #568f89;
        }

        .stress-bar {
          width: 100%;
          height: 14px;
          background: #ddd;
        }

        .stress-fill {
          width: 64%;
          height: 100%;
          background: #568f89;
        }

        .methodology {
          margin-top: 25px;
          padding: 15px;
          border: 1px solid #8aa4a5;
          background: #f7f6f1;
          color: #555;
          font-size: 11px;
          line-height: 1.6;
        }

        @media (max-width: 900px) {
          .layout {
            grid-template-columns: 1fr;
          }

          .sidebar {
            display: none;
          }

          .map-and-tools {
            grid-template-columns: 1fr;
          }

          .result-grid {
            grid-template-columns: 1fr;
          }

          .stress-card {
            grid-column: span 1;
          }

          .results {
            width: 100%;
          }
        }

        @media (max-width: 600px) {
          .dashboard {
            padding: 12px;
          }

          .main-area {
            padding: 18px 12px 30px;
          }

          .district-row {
            grid-template-columns: 1fr;
          }

          .tool-buttons {
            grid-template-columns: 1fr 1fr;
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
                alt="Shehjar"
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
                  className={item === "AOI Analysis" ? "active" : ""}
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


          {/* CONTENT */}

          <section className="content">
            <header className="header">
              <h1>AOI Analysis</h1>
            </header>

            <div className="main-area">

              {/* MAP + CUSTOM AOI TOOLS */}

              <div className="map-and-tools">

                <div className="map-wrapper">
                  <MapContainer
                    center={srinagarCenter}
                    zoom={12}
                    zoomControl={false}
                    className="map-container"
                  >
                    <MapDrawingControls
                      onAOICreated={handleAOICreated}
                      onMapReady={handleMapReady}
                    />

                    <LayersControl position="topright">
                      <BaseLayer
                        checked
                        name="Humanitarian"
                      >
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
                  </MapContainer>
                </div>


                {/* CUSTOM AOI PANEL */}

                <aside className="aoi-tools">
                  <h2>Create Your Own AOI</h2>

                  <p>
                    Draw a custom area directly on the map.
                    You can edit, move, resize, or remove it
                    before analysing.
                  </p>

                  <div className="tool-label">
                    DRAW
                  </div>

                  <div className="tool-buttons">
                    <button
                      type="button"
                      className="tool-button"
                      onClick={startRectangle}
                    >
                      Rectangle
                    </button>

                    <button
                      type="button"
                      className="tool-button"
                      onClick={startPolygon}
                    >
                      Polygon
                    </button>
                  </div>

                  <div className="tool-label">
                    EDIT
                  </div>

                  <div className="tool-buttons">
                    <button
                      type="button"
                      className="tool-button"
                      disabled={!aoi?.geojson}
                      onClick={enableEdit}
                    >
                      Edit
                    </button>

                    <button
                      type="button"
                      className="tool-button"
                      disabled={!aoi?.geojson}
                      onClick={enableDrag}
                    >
                      Move
                    </button>

                    <button
                      type="button"
                      className="tool-button full"
                      disabled={!aoi?.geojson}
                      onClick={clearCustomAOI}
                    >
                      Delete AOI
                    </button>
                  </div>

                  <div className="aoi-status">
                    {aoi?.source === "custom" ? (
                      <>
                        <strong>Custom AOI ready.</strong>
                        <br />
                        Choose Edit or Move if you want to
                        adjust the boundary.
                      </>
                    ) : (
                      <>
                        <strong>No custom AOI.</strong>
                        <br />
                        Choose Rectangle or Polygon to
                        draw one on the map.
                      </>
                    )}
                  </div>

                  <button
                    type="button"
                    className="analyse-custom-button"
                    disabled={!aoi?.geojson}
                    onClick={handleAnalyse}
                  >
                    Analyse AOI
                  </button>
                </aside>
              </div>


              {/* DISTRICT OPTION */}

              <div className="district-section">
                <div className="section-divider">
                  OR
                </div>

                <h3 className="district-title">
                  Select District
                </h3>

                <div className="district-row">
                  <select
                    className="district-select"
                    value={selectedDistrict}
                    onChange={handleDistrictChange}
                  >
                    <option value="">
                      Select District
                    </option>

                    {districts.map((district) => (
                      <option
                        key={district}
                        value={district}
                      >
                        {district}
                      </option>
                    ))}
                  </select>

                  <button
                    type="button"
                    className="analyse-button"
                    disabled={!selectedDistrict}
                    onClick={handleAnalyse}
                  >
                    Analyse
                  </button>
                </div>

                <div className="aoi-info">
                  Select a district to analyse the existing
                  district boundary, or use the custom tools
                  above to analyse any area you draw yourself.
                </div>
              </div>


              {/* RESULTS */}
              {analysisLoading && (
                  <div className="aoi-info">
                    Calculating environmental indicators...
                  </div>
                )}

                {analysisError && (
                  <div
                    className="aoi-info"
                    style={{ color: "#b33" }}
                  >
                    {analysisError}
                  </div>
                )}
              {analysed && (
                <section
                  className="results"
                  ref={resultsRef}
                >
                  <div className="results-inner">
                    <h2>
                      AOI Environmental Analysis
                    </h2>

                    <p className="results-subtitle">
                      Environmental indicators for{" "}
                      <strong>{analysisLabel}</strong>.
                    </p>

                    <div className="result-grid">

                      <div className="result-card">
                        <div className="result-card-title">
                          AOI AREA
                        </div>
                        <div className="result-card-value">
                          {analysisResult?.area.value_km2?.toFixed(2) ?? "—"}
                          <span className="result-card-unit">
                            km²
                          </span>
                        </div>
                      </div>

                      <div className="result-card">
                        <div className="result-card-title">
                          MEAN NDVI
                        </div>

                        <div className="result-card-value">
                          {analysisResult?.mean_ndvi?.toFixed(3) ?? "—"}
                        </div>
                      </div>

                      <div className="result-card">
                        <div className="result-card-title">
                          MEAN NDWI
                        </div>

                        <div className="result-card-value">
                          {analysisResult?.mean_ndwi?.toFixed(3) ?? "—"}
                        </div>
                      </div>

                      <div className="result-card">
                        <div className="result-card-title">
                          CANOPY COVER
                        </div>

                        <div className="result-card-value">
                          {analysisResult?.canopy_cover.percentage?.toFixed(1) ?? "—"}
                          <span className="result-card-unit">
                            %
                          </span>
                        </div>
                      </div>

                      <div className="result-card">
                        <div className="result-card-title">
                          BUILT-UP DENSITY
                        </div>

                        <div className="result-card-value">
                          {analysisResult?.built_up_density.percentage?.toFixed(1) ?? "—"}
                          <span className="result-card-unit">
                            %
                          </span>
                        </div>
                      </div>

                      <div className="result-card">
                        <div className="result-card-title">
                          WATER COVER
                        </div>

                        <div className="result-card-value">
                          {analysisResult?.water_cover.percentage?.toFixed(1) ?? "—"}
                          <span className="result-card-unit">
                            %
                          </span>
                        </div>
                      </div>

                      <div className="stress-card">
                        <div className="stress-header">
                          <span>
                            ECOLOGICAL STRESS
                          </span>

                          <span className="stress-value">
                            Moderate
                          </span>
                        </div>

                        <div className="stress-bar">
                          <div className="stress-fill" />
                        </div>
                      </div>
                    </div>

                    <div className="methodology">
                      <strong>Methodology</strong>
                      <br />

                      Values are calculated from the aligned Shuhul
                      environmental datasets clipped to the selected
                      district or custom AOI. NDVI and NDWI are
                      calculated from raster pixels within the AOI.
                      Canopy cover is calculated from canopy/CHM
                      pixels greater than 0. Built-up density is
                      calculated from building footprint area within
                      the AOI. Water cover combines the explicit water
                      mask with areas where NDWI is at least 0.20
                    </div>
                  </div>
                </section>
              )}

            </div>
          </section>
        </div>
      </main>
    </>
  );
}
