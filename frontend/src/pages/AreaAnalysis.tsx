import { useEffect, useState } from "react";
import { Polygon, Polyline, useMapEvents } from "react-leaflet";
import BaseMap, { ResizeWatcher } from "../components/BaseMap";
import DistrictSelect, { useDistricts } from "../components/DistrictSelect";
import { LayerToggles, MapLegend, RasterLayers, useLayerManifest } from "../components/MapLayers";
import type { ActiveLayers } from "../components/MapLayers";
import { Panel, PanelSection, SelectField, SliderField, Stat, Tabs } from "../components/ui";
import { errorMessage, post } from "../lib/api";
import { num, signed } from "../lib/format";
import type { LatLng } from "../lib/types";

interface YearRow {
  year: number;
  ndvi: number | null;
  ndbi: number | null;
  lst_rel: number | null;
  clear_looks: number | null;
}

interface Environment {
  scope: string;
  area_km2: number;
  vegetation: { mean_ndvi: number | null };
  heat?: { mean_lst_c?: number; p90_lst_c?: number; max_lst_c?: number; mean_warming_if_paved_c?: number; note?: string };
  trees?: { canopy_pct: number | null; canopy_km2: number | null; mean_height_m: number | null };
  buildings?: { roof_cover_pct: number | null };
  landcover?: { name: string; pct: number }[];
  flood?: { classes: { name: string; pct: number }[]; flood_prone_pct: number; note: string };
  water?: { recorded_water_km2: number | null; lost_water_km2: number | null; note: string };
  change?: { years: YearRow[]; note: string };
}

// The original area analysis, kept for its water figures.
interface Legacy {
  mean_ndwi?: number;
  water_cover?: { percentage?: number };
}

interface ZoneChange {
  area_ha: number;
  now_c: number | null;
  after_c: number | null;
  change_c: number;
  noticeably_cooler_ha: number;
  noticeably_warmer_ha: number;
  canopy_pct_now: number;
  canopy_pct_after: number;
}

interface WhatIf {
  label: string;
  share: number;
  land: string;
  available_pct: number;
  changed_ha: number;
  inside: ZoneChange;
  around: ZoneChange | null;
  around_m: number;
  method: { what: string; held_out_error_c: number; tree_note: string; spread: string };
}

type TabId = "area" | "whatif" | "layers";

const CHANGES = [
  { value: "trees", label: "Plant trees on open land" },
  { value: "shrubs", label: "Plant shrubs and grass on open land" },
  { value: "green_roofs", label: "Green the roofs" },
  { value: "pave", label: "Pave the unbuilt land" },
  { value: "build", label: "Build on the unbuilt land" },
];

// A smaller answer than this is not called a change.
const NOTICEABLE_C = 0.25;

function verdict(change: number): string {
  if (change <= -NOTICEABLE_C) return "cooler";
  if (change >= NOTICEABLE_C) return "warmer";
  return "no noticeable change";
}

function ClickToDraw({ active, onAdd }: { active: boolean; onAdd: (point: LatLng) => void }) {
  useMapEvents({
    click(event) {
      if (active) onAdd({ lat: event.latlng.lat, lng: event.latlng.lng });
    },
  });
  return null;
}

export default function AreaAnalysis() {
  const districts = useDistricts();
  const [district, setDistrict] = useState("sr-c");
  const [tab, setTab] = useState<TabId>("area");
  const [drawing, setDrawing] = useState(false);
  const [vertices, setVertices] = useState<LatLng[]>([]);
  const [activeLayers, setActiveLayers] = useState<ActiveLayers>({});

  const [environment, setEnvironment] = useState<Environment | null>(null);
  const [legacy, setLegacy] = useState<Legacy | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [change, setChange] = useState("trees");
  const [share, setShare] = useState(50);
  const [whatIf, setWhatIf] = useState<WhatIf | null>(null);
  const [whatIfBusy, setWhatIfBusy] = useState(false);
  const [whatIfError, setWhatIfError] = useState("");

  const manifest = useLayerManifest(district);
  const hasShape = vertices.length >= 3;

  function polygonOf(shape: LatLng[]) {
    return shape.length >= 3
      ? {
          type: "Polygon",
          coordinates: [[...shape, shape[0]].map((point) => [point.lng, point.lat])],
        }
      : undefined;
  }

  async function analyse(shape: LatLng[]) {
    setBusy(true);
    setError("");
    setWhatIf(null);
    setWhatIfError("");

    const geometry = polygonOf(shape);

    try {
      const [fresh, original] = await Promise.all([
        post<Environment>("/api/area/environment", { district, geometry }),
        post<Legacy>("/api/aoi/analyse", { district, geometry }).catch(() => null),
      ]);
      setEnvironment(fresh);
      setLegacy(original);
    } catch (problem) {
      setEnvironment(null);
      setError(errorMessage(problem, "Could not analyse this area."));
    } finally {
      setBusy(false);
    }
  }

  async function estimate() {
    setWhatIfBusy(true);
    setWhatIfError("");

    try {
      setWhatIf(
        await post<WhatIf>("/api/area/what-if", {
          district,
          geometry: polygonOf(vertices),
          change,
          share: share / 100,
        })
      );
    } catch (problem) {
      setWhatIf(null);
      setWhatIfError(errorMessage(problem, "Could not estimate this change."));
    } finally {
      setWhatIfBusy(false);
    }
  }

  // A district is analysed as soon as it is chosen.
  useEffect(() => {
    setVertices([]);
    setDrawing(false);
    analyse([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [district]);

  const years = environment?.change?.years.filter((row) => row.ndvi !== null) || [];
  const first = years[0];
  const last = years[years.length - 1];
  const ndviChange =
    first && last && first.ndvi && last.ndvi ? (100 * (last.ndvi - first.ndvi)) / first.ndvi : null;

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Area analysis</h1>
        <span className="page-sub">
          {environment ? `${num(environment.area_km2, 2)} km², ${environment.scope}` : "Measure any area"}
        </span>
      </div>

      <div className="split">
        <div className="map-card">
          <BaseMap>
            <ResizeWatcher />
            <ClickToDraw active={drawing} onAdd={(point) => setVertices((previous) => [...previous, point])} />
            <RasterLayers manifest={manifest} active={activeLayers} />

            {hasShape && !drawing && (
              <Polygon
                positions={vertices.map((point): [number, number] => [point.lat, point.lng])}
                pathOptions={{ color: "#203c32", weight: 3, fillOpacity: 0.08 }}
              />
            )}
            {drawing && vertices.length > 0 && (
              <Polyline
                positions={vertices.map((point): [number, number] => [point.lat, point.lng])}
                pathOptions={{ color: "#203c32", weight: 3, dashArray: "6 6" }}
              />
            )}
          </BaseMap>

          {drawing && (
            <div className="map-overlay is-top-left">
              Click the map to mark corners. {vertices.length} so far; three or more make an area.
            </div>
          )}
          <MapLegend manifest={manifest} active={activeLayers} />
        </div>

        <Panel className="side">
          <Tabs<TabId>
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "area", label: "Area" },
              { id: "whatif", label: "What if" },
              { id: "layers", label: "Layers" },
            ]}
          />

          {tab === "whatif" && (
            <>
              <h2 className="panel-title">What if this area changed?</h2>

              {!hasShape || drawing ? (
                <p className="note" style={{ marginTop: 10 }}>
                  Draw an area on the Area tab first. The estimate is for a drawn area of 25 km² or less,
                  where surface temperature has been mapped.
                </p>
              ) : (
                <>
                  <PanelSection>
                    <SelectField label="Change" value={change} options={CHANGES} onChange={setChange} />
                    <SliderField
                      label="How much of that land"
                      value={share}
                      min={10}
                      max={100}
                      step={10}
                      unit="%"
                      onChange={setShare}
                    />
                    <button
                      type="button"
                      className="btn is-dark is-block"
                      style={{ marginTop: 14 }}
                      disabled={whatIfBusy}
                      onClick={estimate}
                    >
                      {whatIfBusy ? "Estimating..." : "Estimate the effect"}
                    </button>
                  </PanelSection>

                  {whatIfError && <p className="message" style={{ marginTop: 14 }}>{whatIfError}</p>}

                  {whatIf && (
                    <>
                      <PanelSection heading="Inside the area">
                        <div className="stat-grid">
                          <Stat label="Surface now" value={`${num(whatIf.inside.now_c, 1)} °C`} />
                          <Stat
                            label="After"
                            value={`${num(whatIf.inside.after_c, 1)} °C`}
                            note={`${signed(whatIf.inside.change_c)} °C, ${verdict(whatIf.inside.change_c)}`}
                          />
                          <Stat
                            label="Land changed"
                            value={`${num(whatIf.changed_ha, 1)} ha`}
                            note={`${num(whatIf.available_pct, 1)}% of the area could take it`}
                          />
                          <Stat
                            label="Tree canopy"
                            value={`${num(whatIf.inside.canopy_pct_after, 1)}%`}
                            note={`Now ${num(whatIf.inside.canopy_pct_now, 1)}%`}
                          />
                        </div>
                        <p className="note" style={{ marginTop: 8 }}>
                          Counts {whatIf.land}. Noticeably cooler over {num(whatIf.inside.noticeably_cooler_ha, 1)} ha,
                          noticeably warmer over {num(whatIf.inside.noticeably_warmer_ha, 1)} ha, of{" "}
                          {num(whatIf.inside.area_ha, 1)} ha.
                        </p>
                      </PanelSection>

                      {whatIf.around && (
                        <PanelSection heading={`Area and ${num(whatIf.around_m)} m around it`}>
                          <p>
                            Average change <b>{signed(whatIf.around.change_c)} °C</b>, {verdict(whatIf.around.change_c)}.
                          </p>
                        </PanelSection>
                      )}

                      <PanelSection heading="How to read this">
                        <p className="note">
                          {whatIf.method.what} {whatIf.method.spread} {whatIf.method.tree_note} Changes smaller
                          than {NOTICEABLE_C} °C are not called a change. Model error on land it was not trained
                          on: {num(whatIf.method.held_out_error_c, 2)} °C.
                        </p>
                      </PanelSection>
                    </>
                  )}
                </>
              )}
            </>
          )}

          {tab === "layers" && (
            <LayerToggles
              manifest={manifest}
              active={activeLayers}
              onToggle={(name) => setActiveLayers((previous) => ({ ...previous, [name]: !previous[name] }))}
            />
          )}

          {tab === "area" && (
            <>
              <DistrictSelect districts={districts} value={district} onChange={setDistrict} />

              <div className="chip-row" style={{ marginTop: 14 }}>
                {!drawing ? (
                  <button
                    type="button"
                    className="btn is-dark is-small"
                    onClick={() => {
                      setVertices([]);
                      setDrawing(true);
                    }}
                  >
                    Draw an area
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn is-dark is-small"
                    disabled={!hasShape}
                    onClick={() => {
                      setDrawing(false);
                      analyse(vertices);
                    }}
                  >
                    Analyse this area
                  </button>
                )}
                {(drawing || hasShape) && (
                  <button
                    type="button"
                    className="btn is-ghost is-small"
                    onClick={() => {
                      setVertices([]);
                      setDrawing(false);
                      analyse([]);
                    }}
                  >
                    Back to whole district
                  </button>
                )}
              </div>

              {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
              {busy && <p className="note" style={{ marginTop: 14 }}>Measuring...</p>}

              {environment && !busy && (
                <>
                  <PanelSection heading="Heat">
                    {environment.heat?.mean_lst_c !== undefined ? (
                      <>
                        <div className="stat-grid">
                          <Stat label="Average" value={`${num(environment.heat.mean_lst_c, 1)} °C`} />
                          <Stat label="Hottest tenth" value={`${num(environment.heat.p90_lst_c, 1)} °C`} note="and above" />
                          <Stat
                            label="Warming if paved"
                            value={`${signed(environment.heat.mean_warming_if_paved_c)} °C`}
                            note="Modelled average"
                          />
                        </div>
                        <p className="note" style={{ marginTop: 8 }}>{environment.heat.note}</p>
                      </>
                    ) : (
                      <p className="note">No temperature layer for this district yet.</p>
                    )}
                  </PanelSection>

                  <PanelSection heading="Green and built">
                    <div className="stat-grid">
                      <Stat label="Tree canopy" value={environment.trees ? `${num(environment.trees.canopy_pct, 1)}%` : "—"} />
                      <Stat label="Vegetation" value={num(environment.vegetation.mean_ndvi, 2)} note="Mean NDVI" />
                      <Stat
                        label="Under roofs"
                        value={environment.buildings ? `${num(environment.buildings.roof_cover_pct, 1)}%` : "—"}
                      />
                    </div>

                    {environment.landcover && (
                      <table className="table" style={{ marginTop: 12 }}>
                        <tbody>
                          {environment.landcover.map((item) => (
                            <tr key={item.name}>
                              <td>{item.name}</td>
                              <td>{num(item.pct, 1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </PanelSection>

                  <PanelSection heading="Water and flood">
                    <div className="stat-grid">
                      <Stat
                        label="Open water"
                        value={`${num(legacy?.water_cover?.percentage, 1)}%`}
                        note="From the water index"
                      />
                      <Stat
                        label="Flood-prone"
                        value={environment.flood ? `${num(environment.flood.flood_prone_pct, 1)}%` : "—"}
                        note="High and very high"
                      />
                      <Stat
                        label="Lost water"
                        value={environment.water ? `${num(environment.water.lost_water_km2, 2)} km²` : "—"}
                        note="Since 1984"
                      />
                    </div>
                    {environment.flood && <p className="note" style={{ marginTop: 8 }}>{environment.flood.note} Confidence: low.</p>}
                  </PanelSection>

                  {years.length > 1 && (
                    <PanelSection heading="Change over time">
                      {ndviChange !== null && first && last && (
                        <p style={{ marginBottom: 10 }}>
                          Vegetation index {ndviChange < 0 ? "fell" : "rose"} {num(Math.abs(ndviChange), 1)}% between{" "}
                          {first.year} and {last.year}.
                        </p>
                      )}
                      <div className="table-scroll">
                        <table className="table">
                          <thead>
                            <tr><th>Year</th><th>Vegetation</th><th>Built-up</th><th>Temp. vs valley</th><th>Clear looks</th></tr>
                          </thead>
                          <tbody>
                            {years.map((row) => (
                              <tr key={row.year}>
                                <td>{row.year}</td>
                                <td>{num(row.ndvi, 3)}</td>
                                <td>{num(row.ndbi, 3)}</td>
                                <td>{row.lst_rel === null ? "—" : `${signed(row.lst_rel, 1)} °C`}</td>
                                <td>{num(row.clear_looks, 1)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <p className="note" style={{ marginTop: 8 }}>{environment.change?.note}</p>
                    </PanelSection>
                  )}
                </>
              )}
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
