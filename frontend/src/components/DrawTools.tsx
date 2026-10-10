import { useEffect, useRef } from "react";
import type { LatLng as LeafletLatLng, Polygon as LeafletPolygon } from "leaflet";
import { useMap } from "react-leaflet";
import "@geoman-io/leaflet-geoman-free";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import type { LatLng } from "../lib/types";

// What the pointer does on the map: nothing, draw a new area, or change
// the one already drawn.
export type DrawMode = "idle" | "rectangle" | "polygon" | "edit" | "move";

interface Props {
  mode: DrawMode;
  // Raised by the page to throw the drawn area away.
  clearKey: number;
  // The area as it stands, after any drawing, editing or moving.
  onShape: (shape: LatLng[] | null) => void;
  // A new area has just been finished.
  onDrawn: (shape: LatLng[]) => void;
}

const AREA_STYLE = { color: "#203c32", weight: 3, fillColor: "#203c32", fillOpacity: 0.08 };
const LINE_STYLE = { color: "#203c32", weight: 2, dashArray: "6 6" };

function corners(layer: LeafletPolygon): LatLng[] {
  const ring = layer.getLatLngs()[0] as LeafletLatLng[];
  return ring.map((point) => ({ lat: point.lat, lng: point.lng }));
}

// Drawing on the map: one rectangle or polygon at a time, with a line
// that follows the pointer while it is drawn.
export default function DrawTools({ mode, clearKey, onShape, onDrawn }: Props) {
  const map = useMap();
  const area = useRef<LeafletPolygon | null>(null);
  const handlers = useRef({ onShape, onDrawn });

  useEffect(() => {
    handlers.current = { onShape, onDrawn };
  });

  useEffect(() => {
    map.pm.setGlobalOptions({
      pathOptions: AREA_STYLE,
      templineStyle: LINE_STYLE,
      hintlineStyle: LINE_STYLE,
      allowSelfIntersection: false,
    });

    const onCreate = (event: { layer: unknown }) => {
      // A finished drawing replaces the one before it.
      if (area.current) map.removeLayer(area.current);

      const drawn = event.layer as LeafletPolygon;
      area.current = drawn;

      const changed = () => handlers.current.onShape(corners(drawn));
      drawn.on("pm:edit", changed);
      drawn.on("pm:dragend", changed);

      handlers.current.onShape(corners(drawn));
      handlers.current.onDrawn(corners(drawn));
    };

    map.on("pm:create", onCreate);

    return () => {
      map.off("pm:create", onCreate);
      map.pm.disableDraw();
      if (area.current) map.removeLayer(area.current);
      area.current = null;
    };
  }, [map]);

  useEffect(() => {
    map.pm.disableDraw();
    area.current?.pm.disable();
    area.current?.pm.disableLayerDrag();

    if (mode === "rectangle") map.pm.enableDraw("Rectangle");
    if (mode === "polygon") map.pm.enableDraw("Polygon");
    if (mode === "edit") area.current?.pm.enable({ allowSelfIntersection: false });
    if (mode === "move") area.current?.pm.enableLayerDrag();
  }, [map, mode]);

  useEffect(() => {
    if (clearKey === 0 || !area.current) return;
    map.removeLayer(area.current);
    area.current = null;
  }, [map, clearKey]);

  return null;
}
