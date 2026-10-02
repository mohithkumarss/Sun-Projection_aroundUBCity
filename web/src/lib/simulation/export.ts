/**
 * GeoJSON export for research geometry.
 *
 * The exported documents retain the full scientific metadata required by the
 * brief (timestamp, building id, solar azimuth and elevation, area, CRS) so an
 * exported frame is a self-contained research record, not a bare shape dump.
 */

import type { ShadowFeature, SimulationFrame } from "../types";

export interface ExportOptions {
  frame: SimulationFrame;
  features: ShadowFeature[];
  studyAreaName: string;
  simulationSha256: string;
  solarMethod: string;
  solarVersion: string;
  crsComputation: string;
  maxShadowLengthM: number;
  truncated: boolean;
}

/** Build the export document for a single frame. */
export function buildFrameExport(options: ExportOptions): GeoJSON.FeatureCollection {
  const { frame, features } = options;
  return {
    type: "FeatureCollection",
    name: `UB City shadow projection ${frame.timestamp}`,
    crs: { type: "name", properties: { name: "EPSG:4326" } },
    metadata: {
      study_area: options.studyAreaName,
      timestamp: frame.timestamp,
      timestamp_utc: frame.timestamp_utc,
      local_time: frame.local_time,
      date_local: frame.date_local,
      timezone: frame.timezone,
      solar_azimuth_deg: frame.solar_azimuth_deg,
      solar_elevation_deg: frame.solar_elevation_deg,
      solar_zenith_deg: frame.solar_zenith_deg,
      sun_above_horizon: frame.sun_above_horizon,
      shadow_azimuth_deg: frame.shadow_azimuth_deg,
      shadow_direction: frame.shadow_direction,
      active_building_shadows: frame.active_building_shadows,
      total_shadow_area_m2: frame.total_shadow_area_m2,
      total_shadow_area_in_study_area_m2: frame.total_shadow_area_in_study_area_m2,
      max_shadow_length_m: frame.max_shadow_length_m,
      shadow_coverage_percent: frame.shadow_coverage_percent,
      truncated: frame.truncated,
      max_shadow_length_m_limit: options.maxShadowLengthM,
      crs_calculated_in: options.crsComputation,
      crs_exported_in: "EPSG:4326",
      solar_position_method: options.solarMethod,
      solar_position_library_version: options.solarVersion,
      simulation_sha256: options.simulationSha256,
      ground_model: "flat plane, z = 0 m",
      shadow_model:
        "Vertical prism extruded to the ground plane; shadow = exact Minkowski sum of the footprint with the segment [z_bottom/tan(elevation), z_top/tan(elevation)] along the anti-solar horizontal direction.",
    },
    features,
  } as unknown as GeoJSON.FeatureCollection;
}

/** Build a single FeatureCollection containing every frame, tagged by frame. */
export function buildAllFramesExport(
  frames: SimulationFrame[],
  shadows: Record<string, ShadowFeature[]>,
  options: Omit<ExportOptions, "frame" | "features">,
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];

  for (const frame of frames) {
    for (const feature of shadows[frame.slug] ?? []) {
      features.push({
        ...feature,
        // Prefix the id so building ids stay unique across the 25 frames.
        id: `${frame.slug}/${feature.id}`,
        properties: {
          ...feature.properties,
          frame_index: frame.index,
          frame_slug: frame.slug,
        },
      });
    }
  }

  return {
    type: "FeatureCollection",
    name: "UB City shadow projection - all 25 hourly frames",
    crs: { type: "name", properties: { name: "EPSG:4326" } },
    metadata: {
      study_area: options.studyAreaName,
      frame_count: frames.length,
      frames: frames.map((frame) => ({
        index: frame.index,
        timestamp: frame.timestamp,
        local_time: frame.local_time,
        solar_azimuth_deg: frame.solar_azimuth_deg,
        solar_elevation_deg: frame.solar_elevation_deg,
        sun_above_horizon: frame.sun_above_horizon,
        total_shadow_area_m2: frame.total_shadow_area_m2,
        max_shadow_length_m: frame.max_shadow_length_m,
        shadow_coverage_percent: frame.shadow_coverage_percent,
        active_building_shadows: frame.active_building_shadows,
      })),
      crs_calculated_in: options.crsComputation,
      crs_exported_in: "EPSG:4326",
      solar_position_method: options.solarMethod,
      solar_position_library_version: options.solarVersion,
      simulation_sha256: options.simulationSha256,
      ground_model: "flat plane, z = 0 m",
      units: "metres, square metres, degrees",
      generated_note:
        "All geometry is precomputed by the Python research pipeline; this export is a copy, not a recomputation.",
    },
    features,
  } as unknown as GeoJSON.FeatureCollection;
}

/** Trigger a browser download of a GeoJSON document. */
export function downloadGeoJson(
  data: GeoJSON.FeatureCollection,
  filename: string,
): void {
  const blob = new Blob([JSON.stringify(data, null, 1)], {
    type: "application/geo+json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Revoke on the next tick so the download has started.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
