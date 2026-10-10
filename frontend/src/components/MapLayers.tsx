// Map layers that come from the server's layer manifest: the tiles on the
// map, the switches that turn them on, and the legend that explains them.

import { useEffect, useState } from "react";
import { ImageOverlay, TileLayer } from "react-leaflet";
import { api, apiUrl } from "../lib/api";
import type { LayerInfo, LayerManifest } from "../lib/types";

export type ActiveLayers = Record<string, boolean>;

// Load the layer manifest for a district. Null while loading or on failure.
export function useLayerManifest(district: string): LayerManifest | null {
  const [manifest, setManifest] = useState<LayerManifest | null>(null);

  useEffect(() => {
    let cancelled = false;

    api<LayerManifest>(`/api/layers/${district}/manifest`)
      .then((data) => {
        if (!cancelled) setManifest(data);
      })
      .catch(() => {
        if (!cancelled) setManifest(null);
      });

    return () => {
      cancelled = true;
    };
  }, [district]);

  return manifest;
}

function activeEntries(manifest: LayerManifest | null, active: ActiveLayers): [string, LayerInfo][] {
  return Object.entries(manifest?.layers || {}).filter(([name]) => active[name]);
}

// ---------- On the map ----------

interface LayerProps {
  manifest: LayerManifest | null;
  active: ActiveLayers;
}

export function RasterLayers({ manifest, active }: LayerProps) {
  if (!manifest) return null;

  return (
    <>
      {activeEntries(manifest, active).map(([name, layer]) =>
        layer.tiles ? (
          <TileLayer
            key={name}
            url={apiUrl(layer.tiles)}
            opacity={0.78}
            zIndex={10}
            minNativeZoom={manifest.min_zoom}
            maxNativeZoom={manifest.max_zoom}
            bounds={manifest.bounds}
          />
        ) : layer.url && layer.bounds ? (
          <ImageOverlay key={name} url={apiUrl(layer.url)} bounds={layer.bounds} opacity={0.6} zIndex={10} />
        ) : null
      )}
    </>
  );
}

// ---------- Switches ----------

interface ToggleProps extends LayerProps {
  onToggle: (name: string) => void;
}

export function LayerToggles({ manifest, active, onToggle }: ToggleProps) {
  if (!manifest) return <p className="note">Loading map layers...</p>;

  const groups: Record<string, [string, LayerInfo][]> = {};
  Object.entries(manifest.layers).forEach(([name, layer]) => {
    const group = layer.group || "Layers";
    (groups[group] = groups[group] || []).push([name, layer]);
  });

  return (
    <>
      {Object.entries(groups).map(([group, layers]) => (
        <div className="panel-section" key={group}>
          <h3 className="panel-heading">{group}</h3>
          <div className="chip-row">
            {layers.map(([name, layer]) => (
              <button
                key={name}
                type="button"
                className="chip"
                aria-pressed={Boolean(active[name])}
                title={layer.note || layer.source}
                onClick={() => onToggle(name)}
              >
                {layer.title}
              </button>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

// What each active layer is, where it came from and how far to trust it.
export function LayerNotes({ manifest, active }: LayerProps) {
  const entries = activeEntries(manifest, active);
  if (entries.length === 0) return null;

  return (
    <div className="panel-section">
      <h3 className="panel-heading">About the layers shown</h3>
      {entries.map(([name, layer]) => (
        <p className="note" key={name} style={{ marginBottom: 8 }}>
          <b>{layer.title}.</b> {layer.source}
          {layer.resolution_m ? `, ${layer.resolution_m} m` : ""}.
          {layer.note ? ` ${layer.note}` : ""}
          {layer.confidence ? ` Confidence: ${layer.confidence}.` : ""}
        </p>
      ))}
    </div>
  );
}

// ---------- Legend ----------

export function MapLegend({ manifest, active }: LayerProps) {
  const entries = activeEntries(manifest, active);
  if (entries.length === 0) return null;

  return (
    <div className="map-overlay is-bottom-left legend">
      {entries.map(([name, layer]) => (
        <div className="legend-block" key={name}>
          <div className="legend-title">
            {layer.title}
            {layer.legend?.type === "ramp" && layer.legend.unit ? ` (${layer.legend.unit})` : ""}
          </div>

          {layer.legend?.type === "ramp" && (
            <>
              <div
                className="legend-ramp"
                style={{ background: `linear-gradient(to right, ${layer.legend.colors.join(", ")})` }}
              />
              <div className="legend-range">
                <span>{layer.legend.min}</span>
                <span>{layer.legend.max}</span>
              </div>
            </>
          )}

          {layer.legend?.type === "swatches" &&
            layer.legend.items.map((item) => (
              <div className="legend-item" key={item.label}>
                <span className="swatch" style={{ background: item.color }} />
                {item.label}
              </div>
            ))}
        </div>
      ))}
    </div>
  );
}
