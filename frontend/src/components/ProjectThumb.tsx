import { latLngBounds } from "leaflet";
import { CircleMarker, MapContainer, Polyline, TileLayer } from "react-leaflet";
import { ROUTE_COLORS, routeParts } from "../lib/format";
import type { ProjectPreview } from "../lib/types";
import { HOT_TILES } from "./BaseMap";

// A still picture of the place a project is about: its routes once it
// has them, otherwise the two points the planner picked.
export default function ProjectThumb({ preview }: { preview: ProjectPreview }) {
  const ends = [preview.start, preview.end].filter(
    (point): point is { lat: number; lng: number } => Boolean(point && point.lat !== undefined)
  );

  const points: [number, number][] = [
    ...preview.routes.flatMap((route) => route.points),
    ...ends.map((point): [number, number] => [point.lat, point.lng]),
  ];

  if (points.length === 0) {
    return <div className="thumb thumb-empty" aria-hidden="true" />;
  }

  return (
    <div className="thumb" aria-hidden="true">
      <MapContainer
        bounds={latLngBounds(points).pad(0.25)}
        zoomControl={false}
        attributionControl={false}
        dragging={false}
        scrollWheelZoom={false}
        doubleClickZoom={false}
        touchZoom={false}
        boxZoom={false}
        keyboard={false}
      >
        <TileLayer url={HOT_TILES} />

        {preview.routes.map((route) => (
          <Polyline
            key={route.name}
            positions={route.points}
            pathOptions={{ color: ROUTE_COLORS[routeParts(route.name).letter] || "#203c32", weight: 3 }}
          />
        ))}

        {ends.map((point, index) => (
          <CircleMarker
            key={index}
            center={[point.lat, point.lng]}
            radius={5}
            pathOptions={{ color: "#f8f8f4", weight: 2, fillColor: "#203c32", fillOpacity: 1 }}
          />
        ))}
      </MapContainer>
    </div>
  );
}
