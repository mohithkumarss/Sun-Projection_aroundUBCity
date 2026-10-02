/**
 * Explicit TypeScript types for the scientific data model.
 *
 * Every field that carries scientific meaning is typed. `any` is not used for
 * any GIS or scientific structure, by design (brief section 31).
 *
 * The runtime shape of these types is guaranteed by the Python pipeline and
 * re-validated by `tests/test_simulation.py`.
 */

// ---------------------------------------------------------------------------
// Coordinate reference systems
// ---------------------------------------------------------------------------

/** WGS 84 geographic, used for storage and GeoJSON interchange. */
export const CRS_STORAGE = "EPSG:4326" as const;
/** WGS 84 / UTM zone 43N, used for every metric computation. */
export const CRS_METRIC = "EPSG:32643" as const;

export type CrsCode = typeof CRS_STORAGE | typeof CRS_METRIC;

/** Positional accuracy is tracked separately from solar accuracy. */
export type PositionalAccuracy = "unknown" | "osm_community_survey";

// ---------------------------------------------------------------------------
// Buildings
// ---------------------------------------------------------------------------

/**
 * How a building's height was established.
 * - `documented`      published by an external, citable document
 * - `survey`          measured by survey
 * - `lidar`           derived from a lidar / DEM dataset
 * - `OSM_exact`       an exact height is tagged in OpenStreetMap
 * - `derived_from_levels` floor count converted with an assumed floor height
 * - `unresolved`      no documented height available
 */
export type HeightMethod =
  | "documented"
  | "survey"
  | "lidar"
  | "OSM_exact"
  | "derived_from_levels"
  | "unresolved";

export type HeightConfidence = "high" | "medium" | "low" | "none";

/** A vertical prism forming part of a building's massing. */
export interface BuildingPrism {
  part_osm_id: number | null;
  geometry_wgs84: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  z_bottom_m: number;
  z_top_m: number;
  height_m: number;
  height_method: HeightMethod;
  height_confidence: HeightConfidence;
}

/** A preserved disagreement between height sources. Never hidden. */
export interface HeightConflict {
  field: string;
  issue: string;
  values?: Record<string, number>;
  raw_value?: string;
  resolution_rule?: string;
}

export interface BuildingAddress {
  "addr:housenumber"?: string;
  "addr:street"?: string;
  "addr:city"?: string;
  "addr:postcode"?: string;
  [key: string]: string | undefined;
}

export interface BuildingProperties {
  id: string;
  name: string | null;
  name_en: string | null;
  building_type: string | null;
  levels: number | null;
  height_m: number | null;
  min_height_m: number;
  height_method: HeightMethod;
  height_confidence: HeightConfidence;
  height_source: string;
  height_source_url: string;
  height_source_ref: string;
  height_conflicts: HeightConflict[];
  /** Null until an approved DEM is integrated. Never invented. */
  ground_elevation_m: number | null;
  footprint_area_m2: number;
  footprint_perimeter_m: number;
  shadow_casting: boolean;
  vertical_model: "building_parts" | "single_prism" | "none";
  building_part_ids: number[];
  prisms: BuildingPrism[];
  address: BuildingAddress;
  operator: string | null;
  brand: string | null;
  website: string | null;
  wikidata: string | null;
  wikipedia: string | null;
  source: "OpenStreetMap";
  source_tags: Record<string, string>;
  osm_id: number;
  osm_type: "way";
  osm_version: number | null;
  source_osm_timestamp: string | null;
}

export interface BuildingFeature {
  type: "Feature";
  id: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  properties: BuildingProperties;
}

export interface BuildingsCollection {
  type: "FeatureCollection";
  name: string;
  crs: { type: "name"; properties: { name: string } };
  metadata: {
    generated_utc: string;
    source: string;
    source_params: { bbox: number[] };
    retrieved_at_utc: string;
    user_agent: string;
    storage_crs: string;
    metric_crs: string;
    levels_derivation_enabled: boolean;
    assumed_floor_height_m: number;
    geometry_simplification: string;
    ground_elevation_m: number | null;
    ground_model: string;
  };
  features: BuildingFeature[];
}

/** Compact building summary embedded in simulation.json. */
export interface BuildingSummary {
  id: string;
  name: string | null;
  height_m: number | null;
  levels: number | null;
  height_method: HeightMethod;
  height_confidence: HeightConfidence;
  height_source: string;
  height_source_url: string;
  footprint_area_m2: number;
  shadow_casting: boolean;
  vertical_model: string;
  ground_elevation_m: number | null;
  prism_count: number;
}

// ---------------------------------------------------------------------------
// Study area
// ---------------------------------------------------------------------------

export interface StudyAreaProperties {
  study_area_name: string;
  bbox_wgs84: [number, number, number, number];
  bbox_metric_epsg32643: [number, number, number, number];
  extent_east_m: number;
  extent_north_m: number;
  selection_rationale: string;
  seed_bbox_used_for_query: number[];
  area_m2: number;
  crs: string;
}

export interface StudyArea {
  type: "FeatureCollection";
  name: string;
  crs: { type: "name"; properties: { name: string } };
  properties: StudyAreaProperties;
  features: GeoJSON.Feature<
    GeoJSON.Polygon,
    { study_area_name: string; bbox_wgs84: number[] }
  >[];
}

// ---------------------------------------------------------------------------
// Solar position
// ---------------------------------------------------------------------------

export interface SolarPosition {
  timestamp: string;
  timestamp_utc: string;
  local_time: string;
  date_local: string;
  timezone: string;
  utc_offset: string;
  latitude: number;
  longitude: number;
  /** Degrees clockwise from true north. Direction TO the sun. */
  solar_azimuth_deg: number;
  /** Degrees above the horizon. */
  solar_elevation_deg: number;
  /** Degrees from vertical. Always 90 - elevation. */
  solar_zenith_deg: number;
  apparent_elevation_deg: number;
  apparent_zenith_deg: number;
  sun_above_horizon: boolean;
  shadow_emitted: boolean;
  equation_of_time_min: number;
}

export interface SolarMetadata {
  method: string;
  pvlib_version: string;
  algorithm: string;
  latitude: number;
  longitude: number;
  timezone: string;
  simulation_date: string;
  frame_count: number;
  sunrise: string | null;
  sunset: string | null;
  min_shadow_elevation_deg: number;
}

// ---------------------------------------------------------------------------
// Shadow geometry
// ---------------------------------------------------------------------------

export interface DominantDirection {
  azimuth_deg: number;
  length_m: number;
  angle_from_north_deg: number;
  description: string;
}

export interface ShadowFeatureProperties {
  building_id: string;
  timestamp: string;
  local_time: string;
  date_local: string;
  timezone: string;
  solar_azimuth_deg: number;
  solar_elevation_deg: number;
  solar_zenith_deg: number;
  sun_above_horizon: boolean;
  /** Always the solar azimuth + 180 deg: the direction light travels. */
  shadow_azimuth_deg: number;
  shadow_direction: string;
  height_m: number;
  height_method: HeightMethod;
  shadow_area_m2: number;
  shadow_area_in_study_area_m2: number;
  shadow_perimeter_m: number;
  max_shadow_length_m: number;
  max_shadow_length_natural_m: number;
  truncated_at_max_length: boolean;
  dominant_direction: DominantDirection | null;
  prism_count: number;
  crs_calculated_in: string;
  crs_exported_in: string;
}

export interface ShadowFeature {
  type: "Feature";
  id: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  properties: ShadowFeatureProperties;
}

export interface BuildingOcclusion {
  samples: number;
  shaded_samples: number;
  shaded_fraction: number | null;
  shaded_by: Record<string, number>;
}

export interface OcclusionAnalysis {
  per_building: Record<string, BuildingOcclusion>;
  method: string;
  samples_per_prism?: number;
}

export interface ShadowFrameFile {
  type: "FeatureCollection";
  name: string;
  crs: { type: "name"; properties: { name: string } };
  metadata: {
    timestamp: string;
    local_time: string;
    date_local: string;
    timezone: string;
    solar_azimuth_deg: number;
    solar_elevation_deg: number;
    solar_zenith_deg: number;
    sun_above_horizon: boolean;
    shadow_emitted: boolean;
    shadow_azimuth_deg: number;
    active_building_shadows: number;
    total_shadow_area_m2: number;
    total_shadow_area_in_study_area_m2: number;
    max_shadow_length_m: number;
    study_area_m2: number;
    shadow_coverage_percent: number;
    truncated: boolean;
    max_shadow_length_m_limit: number;
    min_shadow_elevation_deg: number;
    occlusion: OcclusionAnalysis;
    computed_in_crs: string;
    exported_in_crs: string;
  };
  features: ShadowFeature[];
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------

export interface SimulationFrame {
  index: number;
  slug: string;
  timestamp: string;
  timestamp_utc: string;
  local_time: string;
  date_local: string;
  timezone: string;
  solar_azimuth_deg: number;
  solar_elevation_deg: number;
  solar_zenith_deg: number;
  apparent_elevation_deg: number;
  sun_above_horizon: boolean;
  shadow_emitted: boolean;
  shadow_azimuth_deg: number;
  shadow_direction: string;
  active_building_shadows: number;
  total_shadow_area_m2: number;
  total_shadow_area_in_study_area_m2: number;
  max_shadow_length_m: number;
  study_area_m2: number;
  shadow_coverage_percent: number;
  truncated: boolean;
  file: string;
}

export interface PerBuildingAnalysis {
  building_id: string;
  frames_with_shadow: number;
  max_shadow_length_m: number;
  max_shadow_area_m2: number;
  total_shadow_area_m2: number;
  areas_by_frame: Record<string, number>;
  lengths_by_frame: Record<string, number>;
  directions_by_frame: Record<string, number | null>;
}

export interface AnalysisResult {
  study_area: {
    area_m2: number;
    max_total_shadow_area_m2: number;
    max_shadow_coverage_percent: number;
    coverage_by_frame: Record<string, number>;
    total_area_by_frame: Record<string, number>;
  };
  per_building: PerBuildingAnalysis[];
}

export interface SimulationMetadata {
  study_area: StudyAreaProperties;
  simulation_date: string;
  timezone: string;
  frame_count: number;
  start_local: string;
  end_local: string;
  crs_storage: string;
  crs_computation: string;
  solar_method: SolarMetadata;
  max_shadow_length_m: number;
  min_shadow_elevation_deg: number;
  ground_model: string;
  generated_utc: string;
  shadow_model: string;
  warnings: string[];
  night_frames: string[];
  simulation_sha256: string;
}

export interface Simulation {
  metadata: SimulationMetadata;
  buildings: BuildingSummary[];
  frames: SimulationFrame[];
  analysis: AnalysisResult;
}

/** Pre-loaded shadow geometry for all frames, keyed by frame slug. */
export type ShadowFeatureIndex = Record<string, ShadowFeature[]>;

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

export interface ProvenanceBuilding {
  id: string;
  name: string | null;
  height_m: number | null;
  levels: number | null;
  height_method: HeightMethod;
  height_confidence: HeightConfidence;
  height_source: string;
  height_source_url: string;
  footprint_area_m2: number;
  building_parts: number[];
  vertical_model: string;
  shadow_casting: boolean;
  source_tags: Record<string, string>;
}

export interface Provenance {
  generated_utc: string;
  study_area: {
    name: string;
    bbox_wgs84: number[];
    extent_m: { east_west: number; north_south: number };
    selection: string;
  };
  crs: {
    storage_crs: string;
    storage_crs_name: string;
    metric_crs: string;
    metric_crs_name: string;
  };
  data_source: {
    name: string;
    endpoint: string;
    request: string;
    retrieved_at_utc: string;
    user_agent: string;
    licence: string;
    citation: string;
    why_not_overpass: string;
    known_limitation: string;
  };
  place_cross_check: {
    status: string;
    query?: string;
    results?: Array<Record<string, unknown>>;
    error?: string;
  };
  summary: {
    buildings_total: number;
    shadow_casting_buildings: number;
    unresolved_height_buildings: number;
    heights_by_method: Record<string, number>;
  };
  height_methodology: Record<string, string>;
  buildings: ProvenanceBuilding[];
  geometry_repair_log: string[];
}

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

export type MapMode = "2d" | "3d";

/** Loading / error states are explicit; data is never silently substituted. */
export type DatasetState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "error"; message: string };
