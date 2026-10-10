import { useMemo } from "react";
import { latLngBounds } from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { CircleMarker, GeoJSON, Polyline, Tooltip, useMapEvents } from "react-leaflet";
import BaseMap, { FitBounds, ResizeWatcher } from "../../components/BaseMap";
import { MapLegend, RasterLayers } from "../../components/MapLayers";
import type { ActiveLayers } from "../../components/MapLayers";
import { ROUTE_COLORS, routeParts } from "../../lib/format";
import type { LatLng, LayerManifest, ProjectResult } from "../../lib/types";

export type PointName = "A" | "B";

export const INTERVENTIONS: Record<string, { label: string; color: string }> = {
  tree_restoration: { label: "Tree planting", color: "#2f8f6b" },
  bush_restoration: { label: "Shrubs along roads", color: "#8a9a3b" },
  green_roof: { label: "Green roofs", color: "#6a5aae" },
};

interface Props {
  manifest: LayerManifest | null;
  activeLayers: ActiveLayers;
  points: Record<PointName, LatLng | null>;
  picking: PointName | null;
  onPick: (point: LatLng) => void;
  result: ProjectResult | null;
  corridors: GeoJSON.FeatureCollection | null;
  selectedRoute: string | null;
  show: { routes: boolean; corridors: boolean; mitigation: boolean };
  focus?: (LatLng & { title: string; label: string }) | null;
}

function ClickToPick({ active, onPick }: { active: boolean; onPick: (point: LatLng) => void }) {
  useMapEvents({
    click(event) {
      if (active) onPick({ lat: event.latlng.lat, lng: event.latlng.lng });
    },
  });
  return null;
}

function lineOf(feature: GeoJSON.Feature): [number, number][] {
  const geometry = feature.geometry as GeoJSON.LineString;
  return geometry.coordinates.map(([lng, lat]): [number, number] => [lat, lng]);
}

export default function PlannerMap({
  manifest,
  activeLayers,
  points,
  picking,
  onPick,
  result,
  corridors,
  selectedRoute,
  show,
  focus,
}: Props) {
  const routes = useMemo(
    () => (result?.routeGeoJSON?.features || []).filter((feature) => feature.geometry?.type === "LineString"),
    [result]
  );

  // Bring every route into view when a result arrives.
  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    const all = routes.flatMap(lineOf);
    return all.length ? latLngBounds(all) : null;
  }, [routes]);

  const zones = useMemo(() => {
    const features = result?.mitigation?.geojson?.features || [];
    return features.filter((feature) => !selectedRoute || feature.properties?.route === selectedRoute);
  }, [result, selectedRoute]);

  return (
    <div className="map-card">
      <BaseMap center={focus ? [focus.lat, focus.lng] : undefined} zoom={focus ? 14 : 12}>
        <ResizeWatcher />
        <ClickToPick active={picking !== null} onPick={onPick} />
        <FitBounds bounds={bounds} />
        <RasterLayers manifest={manifest} active={activeLayers} />

        {show.corridors && corridors && (
          <GeoJSON
            key={`corridors-${result?.projectId}`}
            data={corridors}
            style={(feature) => {
              const name = String(feature?.properties?.route);
              const color = ROUTE_COLORS[routeParts(name).letter] || "#203c32";
              const selected = !selectedRoute || selectedRoute === name;
              return { color, weight: 1, opacity: 0.5, fillColor: color, fillOpacity: selected ? 0.3 : 0.1 };
            }}
            // Corridors arrive after the routes, so they are sent underneath.
            eventHandlers={{ add: (event) => event.target.bringToBack() }}
          />
        )}

        {show.mitigation && zones.length > 0 && (
          <GeoJSON
            key={`zones-${result?.projectId}-${selectedRoute}`}
            data={{ type: "FeatureCollection", features: zones } as GeoJSON.FeatureCollection}
            style={(feature) => {
              const color = INTERVENTIONS[feature?.properties?.intervention]?.color || "#2f8f6b";
              return { color, weight: 2, fillColor: color, fillOpacity: 0.35 };
            }}
            onEachFeature={(feature, layer) => {
              const kind = INTERVENTIONS[feature.properties?.intervention]?.label || "Mitigation";
              layer.bindTooltip(`${feature.properties?.zone_id}: ${kind}`);
            }}
          />
        )}

        {show.routes &&
          routes.map((feature) => {
            const name = String(feature.properties?.route);
            const selected = !selectedRoute || selectedRoute === name;

            return (
              <Polyline
                key={name}
                positions={lineOf(feature)}
                pathOptions={{
                  color: ROUTE_COLORS[routeParts(name).letter] || "#203c32",
                  weight: selected ? 6 : 3,
                  opacity: selected ? 0.95 : 0.55,
                }}
              >
                <Tooltip sticky>{name}</Tooltip>
              </Polyline>
            );
          })}

        {(["A", "B"] as PointName[]).map(
          (name) =>
            points[name] && (
              <CircleMarker
                key={name}
                center={[points[name]!.lat, points[name]!.lng]}
                radius={9}
                pathOptions={{ color: "#f8f8f4", weight: 3, fillColor: "#203c32", fillOpacity: 1 }}
              >
                <Tooltip permanent direction="top" offset={[0, -8]}>{name}</Tooltip>
              </CircleMarker>
            )
        )}

        {focus && (
          <CircleMarker
            center={[focus.lat, focus.lng]}
            radius={12}
            pathOptions={{ color: "#203c32", weight: 3, fillColor: "#f8f8f4", fillOpacity: 0.85 }}
          >
            <Tooltip>{focus.label}: {focus.title}</Tooltip>
          </CircleMarker>
        )}
      </BaseMap>

      {picking && (
        <div className="map-overlay is-top-left">
          Click the map to place point <b>{picking}</b>.
        </div>
      )}

      <MapLegend manifest={manifest} active={activeLayers} />
    </div>
  );
}
