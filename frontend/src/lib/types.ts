// Shapes of what the Shuhul API returns. Only the fields the app reads.

export interface LatLng {
  lat: number;
  lng: number;
}

export interface User {
  id: number;
  email: string;
  organisation: string;
  name?: string | null;
}

export interface District {
  code: string;
  name: string;
  has_tiles: boolean;
  has_heat: boolean;
}

// ---------- Map layers ----------

export interface LegendRamp {
  type: "ramp";
  colors: string[];
  min: number;
  max: number;
  unit?: string;
}

export interface LegendSwatches {
  type: "swatches";
  items: { label: string; color: string }[];
}

export interface LayerInfo {
  title: string;
  group?: string;
  kind?: string;
  unit?: string;
  source?: string;
  resolution_m?: number;
  confidence?: string;
  note?: string;
  legend?: LegendRamp | LegendSwatches;
  tiles?: string;
  url?: string;
  bounds?: [[number, number], [number, number]];
}

export interface LayerManifest {
  district: string;
  bounds?: [[number, number], [number, number]];
  min_zoom?: number;
  max_zoom?: number;
  layers: Record<string, LayerInfo>;
}

// ---------- Projects ----------

export interface ProjectPreview {
  start?: LatLng | null;
  end?: LatLng | null;
  routes: { name: string; points: [number, number][] }[];
}

export interface ProjectSummary {
  id: string;
  project_name: string;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  construction_type?: string;
  preview: ProjectPreview;
}

export interface ProjectPayload {
  projectName: string;
  constructionType: string;
  widthMeters: number;
  start: LatLng;
  end: LatLng;
  softPreferences: Record<string, number>;
  hardConstraints: Record<string, boolean>;
}

export interface ScenarioZone {
  area_ha: number;
  observed_lst_c: number | null;
  estimated_lst_c: number | null;
  mean_change_c: number;
  heat_added_degree_ha: number;
  heat_removed_degree_ha: number;
  canopy_pct: number;
  ndvi: number;
  built_up_pct: number;
}

export interface RouteHeat {
  available: boolean;
  scenarios?: Record<string, { footprint: ScenarioZone | null; impact_zone: ScenarioZone | null }>;
  impact_zone_m?: number;
  heat_added_degree_ha?: number;
  heat_remaining_degree_ha?: number;
  heat_repaid_pct?: number | null;
  corridor_change_c?: number;
  corridor_change_after_mitigation_c?: number;
  method?: Record<string, string | number>;
}

export interface RouteFlood {
  available: boolean;
  low_m2?: number;
  moderate_m2?: number;
  high_m2?: number;
  very_high_m2?: number;
  flood_prone_m2?: number;
  flood_prone_pct?: number | null;
  lost_water_m2?: number | null;
  recorded_water_m2?: number | null;
  note?: string;
}

export interface MitigationPlan {
  status: string;
  canopy_removed_m2: number;
  canopy_ratio: number;
  canopy_owed_m2: number;
  allocated_m2: number;
  available_nearby_m2: number;
  heat_repaid_pct?: number | null;
  zones: {
    zone_id: string;
    intervention: string;
    distance_m: number;
    available_m2: number;
    allocated_m2: number;
  }[];
  note: string;
}

export interface RouteImpact {
  route_length_km?: number;
  impact_corridor_area_m2?: number;
  green_space?: { green_area_m2?: number };
  canopy?: { canopy_area_m2?: number; estimated_tree_equivalent?: number };
  water?: { combined_water_area_m2?: number; estimated_crossings?: number };
  slope?: { mean_slope_deg?: number; high_slope_percentage?: number };
  buildings?: { count?: number | null };
  heritage?: { count?: number | null };
  environmental_cost?: { environmental_cost_index?: number | null };
  heat?: RouteHeat;
  flood?: RouteFlood;
  mitigation_plan?: MitigationPlan;
}

export interface ProjectResult {
  projectId: string;
  project: ProjectPayload;
  district: string;
  routeGeoJSON?: GeoJSON.FeatureCollection | null;
  impact?: { routes: Record<string, RouteImpact>; assumptions?: Record<string, unknown> };
  mitigation?: { geojson?: GeoJSON.FeatureCollection };
  costSurface?: { weights?: Record<string, number>; layers_used?: Record<string, boolean> };
}

export interface ProjectStatus {
  projectId: string;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  result?: ProjectResult | null;
}

export interface ProjectDetail extends ProjectSummary {
  payload: ProjectPayload;
  result?: ProjectResult;
}
