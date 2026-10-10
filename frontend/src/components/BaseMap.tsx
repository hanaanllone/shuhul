import { useEffect } from "react";
import type { ReactNode } from "react";
import type { LatLngBoundsExpression } from "leaflet";
import { MapContainer, ScaleControl, TileLayer, ZoomControl, useMap } from "react-leaflet";

export const SRINAGAR: [number, number] = [34.0837, 74.7973];

// OpenStreetMap in the Humanitarian style, used for every map in the app.
export const HOT_TILES = "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png";
export const HOT_ATTRIBUTION =
  '&copy; OpenStreetMap contributors, tiles in the Humanitarian style by HOT';

interface Props {
  center?: [number, number];
  zoom?: number;
  children?: ReactNode;
}

export default function BaseMap({ center = SRINAGAR, zoom = 12, children }: Props) {
  return (
    <MapContainer center={center} zoom={zoom} zoomControl={false}>
      <TileLayer url={HOT_TILES} attribution={HOT_ATTRIBUTION} maxZoom={19} />
      <ZoomControl position="bottomright" />
      <ScaleControl position="bottomright" />
      {children}
    </MapContainer>
  );
}

// Move the map to show some bounds whenever they change.
export function FitBounds({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();

  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [40, 40] });
  }, [map, bounds]);

  return null;
}

// The map measures itself once, so it needs telling when its box changes size.
export function ResizeWatcher() {
  const map = useMap();

  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);

  return null;
}
