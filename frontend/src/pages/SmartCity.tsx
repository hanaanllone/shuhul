import { useEffect, useMemo, useState } from "react";
import { geoJSON as leafletGeoJSON } from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { GeoJSON } from "react-leaflet";
import BaseMap, { FitBounds, ResizeWatcher } from "../components/BaseMap";
import { Panel, PanelSection, Stat, Tabs } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num, signed } from "../lib/format";

interface Block {
  block_id: string;
  kind: string;
  mixed: boolean;
  ndvi_then: number | null;
  ndvi_now: number | null;
  ndvi_change: number;
  heat_then_c: number | null;
  heat_now_c: number | null;
  heat_change_c: number;
  ndvi: (number | null)[];
  heat_c: (number | null)[];
}

interface CityYear {
  year: number;
  ndvi: number | null;
  green_pct: number | null;
  heat_c: number | null;
  lst_c: number | null;
}

interface Link {
  blocks: number;
  r: number | null;
  heat_per_tenth_ndvi_c: number | null;
}

interface Group {
  blocks: number;
  ndvi_change: number | null;
  heat_change_c: number | null;
}

interface CityChange extends GeoJSON.FeatureCollection {
  years: number[];
  then_years: number[];
  now_years: number[];
  block_m: number;
  city: CityYear[];
  relation: {
    blocks: number;
    now: Link;
    change: Link;
    mixed: Link & { ndvi_from: number; ndvi_to: number; lost: Group; steady: Group; gained: Group };
    lost_and_hotter_pct: number | null;
    gained_and_hotter_pct: number | null;
  };
  kinds: { key: string; label: string; blocks: number }[];
  steady: { ndvi: number; heat_c: number };
  green_ndvi: number;
  method: string;
  caution: string;
}

type View = "green" | "heat" | "both";

interface Step {
  label: string;
  color: string;
  test: (value: number) => boolean;
}

// Browns to greens for vegetation, blues to reds for heat, so the two
// maps cannot be mistaken for each other.
const GREEN_STEPS: Step[] = [
  { label: "Lost a lot, over 0.10", color: "#8c510a", test: (value) => value <= -0.1 },
  { label: "Lost some", color: "#d8b365", test: (value) => value <= -0.03 },
  { label: "Little change", color: "#e8e6dc", test: (value) => value < 0.03 },
  { label: "Gained some", color: "#7fb089", test: (value) => value < 0.1 },
  { label: "Gained a lot, over 0.10", color: "#1c5a3c", test: () => true },
];

const HEAT_STEPS: Step[] = [
  { label: "Much cooler, over 1 °C", color: "#2166ac", test: (value) => value <= -1 },
  { label: "Cooler", color: "#8fbfdc", test: (value) => value <= -0.3 },
  { label: "Little change", color: "#e8e6dc", test: (value) => value < 0.3 },
  { label: "Hotter", color: "#ef8a62", test: (value) => value < 1 },
  { label: "Much hotter, over 1 °C", color: "#b2182b", test: () => true },
];

const KIND_COLORS: Record<string, string> = {
  lost_hotter: "#b2182b",
  lost: "#d8b365",
  hotter: "#ef8a62",
  gained_cooler: "#1c5a3c",
  gained: "#7fb089",
  cooler: "#8fbfdc",
  steady: "#e8e6dc",
  water: "#b9c0bb",
};

function stepColor(steps: Step[], value: number): string {
  return (steps.find((step) => step.test(value)) || steps[steps.length - 1]).color;
}

// [2017, 2018, 2019] -> "2017–19"
function span(years: number[]): string {
  if (!years.length) return "";
  const last = years[years.length - 1];
  return years.length === 1 ? String(last) : `${years[0]}–${String(last).slice(2)}`;
}

function average(rows: CityYear[], years: number[], key: "ndvi" | "green_pct" | "heat_c" | "lst_c"): number | null {
  const values = rows
    .filter((row) => years.includes(row.year))
    .map((row) => row[key])
    .filter((value): value is number => value !== null);
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

// One line over the years, with its lowest and highest value marked.
function YearChart({ years, values, color, digits, label }: {
  years: number[];
  values: (number | null)[];
  color: string;
  digits: number;
  label: string;
}) {
  const points = values
    .map((value, index) => ({ value, index }))
    .filter((point): point is { value: number; index: number } => point.value !== null);
  if (points.length < 2) return null;

  const low = Math.min(...points.map((point) => point.value));
  const high = Math.max(...points.map((point) => point.value));
  const range = high - low || 1;
  const x = (index: number) => 40 + (index / (years.length - 1)) * 250;
  const y = (value: number) => 10 + (1 - (value - low) / range) * 58;
  const path = points
    .map((point, order) => `${order ? "L" : "M"}${x(point.index).toFixed(1)} ${y(point.value).toFixed(1)}`)
    .join(" ");

  return (
    <svg viewBox="0 0 300 92" width="100%" role="img" aria-label={label} style={{ display: "block", marginTop: 6 }}>
      <line x1="40" y1="68" x2="290" y2="68" stroke="currentColor" strokeOpacity="0.25" />
      <line x1="40" y1="10" x2="290" y2="10" stroke="currentColor" strokeOpacity="0.12" />
      <text x="34" y="14" textAnchor="end" fontSize="10" fill="currentColor">{num(high, digits)}</text>
      <text x="34" y="71" textAnchor="end" fontSize="10" fill="currentColor">{num(low, digits)}</text>
      <path d={path} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
      {points.map((point) => (
        <circle key={point.index} cx={x(point.index)} cy={y(point.value)} r="2.4" fill={color} />
      ))}
      {years.map((year, index) =>
        index === 0 || index === years.length - 1 || index === Math.floor(years.length / 2) ? (
          <text key={year} x={x(index)} y="86" textAnchor="middle" fontSize="10" fill="currentColor">{year}</text>
        ) : null
      )}
    </svg>
  );
}

// Every land block as a dot: green lost or gained across, heat up or down.
function Scatter({ blocks, picked }: { blocks: Block[]; picked: Block | null }) {
  const x = (value: number) => 34 + ((Math.max(-0.25, Math.min(0.15, value)) + 0.25) / 0.4) * 256;
  const y = (value: number) => 10 + ((4 - Math.max(-4, Math.min(4, value))) / 8) * 150;

  return (
    <svg
      viewBox="0 0 300 190"
      width="100%"
      role="img"
      aria-label="Each block by its change in vegetation and its change in heat"
      style={{ display: "block", marginTop: 8 }}
    >
      <line x1={x(0)} y1="10" x2={x(0)} y2="160" stroke="currentColor" strokeOpacity="0.3" />
      <line x1="34" y1={y(0)} x2="290" y2={y(0)} stroke="currentColor" strokeOpacity="0.3" />
      {blocks.map((block) => (
        <circle
          key={block.block_id}
          cx={x(block.ndvi_change)}
          cy={y(block.heat_change_c)}
          r="1.7"
          fill={block.mixed ? "#1c5a3c" : "#8a948d"}
          fillOpacity={block.mixed ? 0.6 : 0.3}
        />
      ))}
      {picked && picked.kind !== "water" && (
        <circle cx={x(picked.ndvi_change)} cy={y(picked.heat_change_c)} r="5" fill="none" stroke="#b2182b" strokeWidth="2" />
      )}
      <text x="30" y="16" textAnchor="end" fontSize="10" fill="currentColor">+4°</text>
      <text x="30" y="163" textAnchor="end" fontSize="10" fill="currentColor">−4°</text>
      <text x="34" y="178" fontSize="10" fill="currentColor">← lost green</text>
      <text x="290" y="178" textAnchor="end" fontSize="10" fill="currentColor">gained green →</text>
      <text x="38" y="22" fontSize="10" fill="currentColor">hotter ↑</text>
    </svg>
  );
}

export default function SmartCity() {
  const [data, setData] = useState<CityChange | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("both");
  const [kind, setKind] = useState<string | null>(null);
  const [picked, setPicked] = useState<Block | null>(null);

  useEffect(() => {
    api<CityChange>("/api/city/change")
      .then(setData)
      .catch((problem) => setError(errorMessage(problem, "Could not load the city record.")));
  }, []);

  const blocks = useMemo(() => (data?.features || []).map((feature) => feature.properties as Block), [data]);
  const land = useMemo(() => blocks.filter((block) => block.kind !== "water"), [blocks]);

  const shown = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!data) return null;
    return {
      type: "FeatureCollection",
      features: data.features.filter((feature) => !kind || (feature.properties as Block).kind === kind),
    };
  }, [data, kind]);

  const bounds = useMemo<LatLngBoundsExpression | null>(
    () => (data && data.features.length ? leafletGeoJSON(data).getBounds() : null),
    [data]
  );

  function colorOf(block: Block): string {
    if (block.kind === "water") return KIND_COLORS.water;
    if (view === "green") return stepColor(GREEN_STEPS, block.ndvi_change);
    if (view === "heat") return stepColor(HEAT_STEPS, block.heat_change_c);
    return KIND_COLORS[block.kind] || KIND_COLORS.steady;
  }

  const then = data ? span(data.then_years) : "";
  const now = data ? span(data.now_years) : "";
  const relation = data?.relation;
  const kindLabel = (key: string) => data?.kinds.find((entry) => entry.key === key)?.label || key;

  const legend =
    view === "green"
      ? GREEN_STEPS.map((step) => ({ label: step.label, color: step.color }))
      : view === "heat"
        ? HEAT_STEPS.map((step) => ({ label: step.label, color: step.color }))
        : (data?.kinds || []).map((entry) => ({ label: entry.label, color: KIND_COLORS[entry.key] }));

  return (
    <main className="page">
      <div className="page-head">
        <h1 className="page-title">Smart city Srinagar</h1>
        <span className="page-sub">How green cover and surface heat have moved since 2017, block by block</span>
      </div>

      <div className="split">
        <div className="map-card">
          <BaseMap>
            <ResizeWatcher />
            <FitBounds bounds={bounds} />
            {shown && (
              <GeoJSON
                key={`${view}-${kind}-${picked?.block_id}`}
                data={shown}
                style={(feature) => {
                  const block = feature?.properties as Block;
                  const chosen = picked?.block_id === block.block_id;
                  return {
                    color: "#142a28",
                    weight: chosen ? 3 : 0.2,
                    fillColor: colorOf(block),
                    fillOpacity: block.kind === "water" ? 0.3 : 0.72,
                  };
                }}
                onEachFeature={(feature, layer) => {
                  layer.on("click", () => setPicked(feature.properties as Block));
                }}
              />
            )}
          </BaseMap>

          <div className="map-overlay is-bottom-left">
            <div className="legend-title">
              {view === "green" ? `Vegetation, ${then} to ${now}` : view === "heat" ? `Heat, ${then} to ${now}` : "Green and heat together"}
            </div>
            {legend.map((entry) => (
              <div className="legend-item" key={entry.label}>
                <span className="swatch" style={{ background: entry.color }} />
                {entry.label}
              </div>
            ))}
          </div>
        </div>

        <Panel className="side">
          <Tabs<View>
            active={view}
            onChange={(next) => {
              setView(next);
              setKind(null);
            }}
            tabs={[
              { id: "both", label: "Green and heat" },
              { id: "green", label: "Green cover" },
              { id: "heat", label: "Heat" },
            ]}
          />

          {error && <p className="message" style={{ marginTop: 14 }}>{error}</p>}
          {!data && !error && <p className="note" style={{ marginTop: 14 }}>Reading nine summers of the city...</p>}

          {data && relation && (
            <>
              <PanelSection heading={`The city, ${then} to ${now}`}>
                <div className="stat-grid">
                  <Stat
                    label="Green cover"
                    value={`${num(average(data.city, data.then_years, "green_pct"), 1)}% → ${num(average(data.city, data.now_years, "green_pct"), 1)}%`}
                    note={`Land with a vegetation index over ${data.green_ndvi}`}
                  />
                  <Stat
                    label="Vegetation index"
                    value={`${num(average(data.city, data.then_years, "ndvi"), 2)} → ${num(average(data.city, data.now_years, "ndvi"), 2)}`}
                    note="City average, NDVI"
                  />
                  <Stat
                    label="Summer surface"
                    value={`${num(average(data.city, data.then_years, "lst_c"), 1)} → ${num(average(data.city, data.now_years, "lst_c"), 1)} °C`}
                    note="Varies with the weather of each summer"
                  />
                  <Stat
                    label="Blocks that lost green"
                    value={`${num(data.kinds.filter((entry) => entry.key === "lost" || entry.key === "lost_hotter").reduce((sum, entry) => sum + entry.blocks, 0))} of ${num(relation.blocks)}`}
                    note={`${num(relation.lost_and_hotter_pct)}% of them also got hotter`}
                  />
                </div>

                <p className="field-hint" style={{ marginTop: 12 }}>Green cover, % of the city, each summer</p>
                <YearChart
                  years={data.years}
                  values={data.city.map((row) => row.green_pct)}
                  color="#1c5a3c"
                  digits={0}
                  label="Green cover of the city by year"
                />
                <p className="field-hint" style={{ marginTop: 8 }}>Summer surface temperature, °C</p>
                <YearChart
                  years={data.years}
                  values={data.city.map((row) => row.lst_c)}
                  color="#b2182b"
                  digits={1}
                  label="Summer surface temperature of the city by year"
                />
              </PanelSection>

              <PanelSection heading={picked ? `Block ${picked.block_id}` : "Select a block on the map"}>
                {picked ? (
                  <>
                    <p style={{ marginBottom: 10 }}>
                      <span className="dot" style={{ background: KIND_COLORS[picked.kind], display: "inline-block", marginRight: 6 }} />
                      {kindLabel(picked.kind)}
                    </p>
                    <div className="stat-grid">
                      <Stat
                        label="Vegetation index"
                        value={`${num(picked.ndvi_then, 2)} → ${num(picked.ndvi_now, 2)}`}
                        note={`${signed(picked.ndvi_change, 2)} since ${then}`}
                      />
                      <Stat
                        label="Heat against the valley floor"
                        value={`${signed(picked.heat_then_c, 1)} → ${signed(picked.heat_now_c, 1)} °C`}
                        note={`${signed(picked.heat_change_c, 1)} °C since ${then}`}
                      />
                    </div>
                    <p className="field-hint" style={{ marginTop: 12 }}>Vegetation index of this block</p>
                    <YearChart years={data.years} values={picked.ndvi} color="#1c5a3c" digits={2} label="Vegetation index of the block by year" />
                    <p className="field-hint" style={{ marginTop: 8 }}>Heat against the valley floor, °C</p>
                    <YearChart years={data.years} values={picked.heat_c} color="#b2182b" digits={1} label="Heat of the block by year" />
                  </>
                ) : (
                  <p className="note">
                    Each block is a {data.block_m} m square. A block shows its vegetation and heat for every summer.
                  </p>
                )}
              </PanelSection>

              <PanelSection heading="Does heat follow green?">
                <p style={{ fontSize: 14, marginBottom: 10 }}>
                  Today, greener blocks are cooler. Each 0.1 more of the vegetation index goes with a surface{" "}
                  <b>{num(Math.abs(relation.now.heat_per_tenth_ndvi_c || 0), 1)} °C cooler</b> (r {num(relation.now.r, 2)},{" "}
                  {num(relation.now.blocks)} blocks).
                </p>
                <p style={{ fontSize: 14, marginBottom: 10 }}>
                  In the {num(relation.mixed.blocks)} blocks that were part green and part built in {then}, each 0.1 of
                  the index lost came with <b>{num(Math.abs(relation.mixed.heat_per_tenth_ndvi_c || 0), 1)} °C more heat</b>{" "}
                  (r {num(relation.mixed.r, 2)}).
                </p>

                <table className="table">
                  <thead>
                    <tr><th>Part-built blocks that</th><th>Blocks</th><th>Heat moved</th></tr>
                  </thead>
                  <tbody>
                    {([["Lost green", relation.mixed.lost], ["Stayed the same", relation.mixed.steady], ["Gained green", relation.mixed.gained]] as [string, Group][]).map(
                      ([label, group]) => (
                        <tr key={label}>
                          <td>{label}</td>
                          <td>{num(group.blocks)}</td>
                          <td>{group.heat_change_c === null ? "—" : `${signed(group.heat_change_c, 2)} °C`}</td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>

                <Scatter blocks={land} picked={picked} />
                <p className="field-hint">
                  One dot is one block. Dark dots are the part-built blocks{picked ? "; the ring is the block selected" : ""}.
                </p>

                <p className="note" style={{ marginTop: 10 }}>
                  Across all {num(relation.change.blocks)} land blocks the two changes do not line up (r{" "}
                  {num(relation.change.r, 2)}). Farmland and wetland lose green to water and wet fields, which cools
                  them, and blocks that were already bare had little left to lose.
                </p>
              </PanelSection>

              {view === "both" && (
                <PanelSection heading="Blocks by what happened">
                  <div className="chip-row">
                    {data.kinds.map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        className="chip"
                        aria-pressed={kind === entry.key}
                        onClick={() => setKind(kind === entry.key ? null : entry.key)}
                      >
                        <span className="dot" style={{ background: KIND_COLORS[entry.key] }} />
                        {entry.label} ({entry.blocks})
                      </button>
                    ))}
                  </div>
                  <p className="field-hint">
                    Select one to show only those blocks. A change under {data.steady.ndvi} of the index or{" "}
                    {data.steady.heat_c} °C counts as none.
                  </p>
                </PanelSection>
              )}

              <PanelSection heading="How this is worked out">
                <p className="note">{data.method} {data.caution}</p>
              </PanelSection>
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
