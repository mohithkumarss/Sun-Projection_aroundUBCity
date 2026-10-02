/**
 * Dataset loading and validation.
 *
 * Responsibilities
 * ----------------
 *  * fetch the four generated artefacts once
 *  * validate their shape at runtime, so a malformed or partially-written file
 *    produces an explicit error instead of a broken map
 *  * never substitute fabricated or placeholder data on failure
 */

import type {
  BuildingsCollection,
  OcclusionAnalysis,
  ShadowFeature,
  Simulation,
  StudyArea,
} from "../types";

export const DATA_BASE = "/data";

/** Error thrown for any missing, unreadable, or structurally invalid dataset. */
export class DatasetError extends Error {
  readonly detail: string;

  constructor(message: string, detail = "") {
    super(message);
    this.name = "DatasetError";
    this.detail = detail;
  }
}

async function fetchJson<T>(
  path: string,
  what: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { cache: "no-store", signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new DatasetError(
      `Could not load ${what}.`,
      `Request for ${path} failed: ${String(error)}. Has the research dataset been generated? Run: python scripts/run_pipeline.py`,
    );
  }

  if (!response.ok) {
    throw new DatasetError(
      `Could not load ${what} (HTTP ${response.status}).`,
      `${path} returned ${response.status} ${response.statusText}. Run: python scripts/run_pipeline.py`,
    );
  }

  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new DatasetError(
      `${what} is not valid JSON.`,
      `${path} could not be parsed: ${String(error)}. The dataset is likely truncated - re-run the pipeline.`,
    );
  }
}

function assertRecord(value: unknown, field: string, where: string): void {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new DatasetError(
      `Invalid dataset: expected an object at "${field}".`,
      `Found ${Array.isArray(value) ? "array" : typeof value} in ${where}.`,
    );
  }
}

function validateSimulation(data: Simulation): Simulation {
  assertRecord(data, "simulation", "simulation.json");
  if (!Array.isArray(data.frames) || data.frames.length === 0) {
    throw new DatasetError(
      "Simulation dataset contains no frames.",
      "simulation.json must contain a non-empty `frames` array.",
    );
  }
  if (data.frames.length !== 25) {
    throw new DatasetError(
      `Expected 25 hourly frames but found ${data.frames.length}.`,
      "The dataset is inconsistent with the specified 24-hour timeline. Re-run: python scripts/run_pipeline.py",
    );
  }
  for (const frame of data.frames) {
    if (typeof frame.solar_azimuth_deg !== "number" || Number.isNaN(frame.solar_azimuth_deg)) {
      throw new DatasetError(
        `Frame ${String(frame.slug)} has an invalid solar azimuth.`,
        "Solar azimuth must be a finite number in degrees.",
      );
    }
    if (typeof frame.solar_elevation_deg !== "number" || Number.isNaN(frame.solar_elevation_deg)) {
      throw new DatasetError(
        `Frame ${String(frame.slug)} has an invalid solar elevation.`,
        "Solar elevation must be a finite number in degrees.",
      );
    }
  }
  if (!data.metadata?.solar_method?.method) {
    throw new DatasetError(
      "Simulation metadata is missing the solar-position method.",
      "The provenance of the solar calculation is mandatory and must be recorded.",
    );
  }
  return data;
}

function validateBuildings(data: BuildingsCollection): BuildingsCollection {
  assertRecord(data, "buildings", "buildings.geojson");
  if (data.type !== "FeatureCollection" || !Array.isArray(data.features)) {
    throw new DatasetError(
      "buildings.geojson is not a GeoJSON FeatureCollection.",
      "Expected { type: 'FeatureCollection', features: [...] }.",
    );
  }
  if (data.features.length === 0) {
    throw new DatasetError(
      "The building dataset is empty.",
      "No OpenStreetMap buildings were retrieved. The pipeline will not render a fabricated dataset - re-run: python scripts/fetch_buildings.py",
    );
  }
  for (const feature of data.features) {
    if (!feature.properties?.height_method) {
      throw new DatasetError(
        `Building ${String(feature.id)} is missing height_method.`,
        "Every building must declare how its height was established, including 'unresolved'.",
      );
    }
    if (!feature.properties?.height_source) {
      throw new DatasetError(
        `Building ${String(feature.id)} is missing height provenance.`,
        "Every building must record a height source string.",
      );
    }
  }
  return data;
}

export interface Dataset {
  simulation: Simulation;
  buildings: BuildingsCollection;
  studyArea: StudyArea;
  /** Shadow features for all 25 frames, keyed by frame slug. */
  shadows: Record<string, ShadowFeature[]>;
  /** Per-frame building-to-building occlusion results, keyed by frame slug. */
  occlusion: Record<string, OcclusionAnalysis>;
}

/**
 * Load and validate the complete dataset.
 *
 * Fetches all 25 shadow frames in parallel. On any failure a DatasetError is
 * thrown; the caller renders it. No default or sample data is ever returned.
 */
export async function loadDataset(
  signal?: AbortSignal,
): Promise<Dataset> {
  const [simulation, buildings, studyArea] = await Promise.all([
    fetchJson<Simulation>(
      `${DATA_BASE}/simulation.json`,
      "the simulation index",
      signal,
    ),
    fetchJson<BuildingsCollection>(
      `${DATA_BASE}/buildings.geojson`,
      "the building footprints",
      signal,
    ),
    fetchJson<StudyArea>(
      `${DATA_BASE}/study-area.geojson`,
      "the study area",
      signal,
    ),
  ]);

  validateSimulation(simulation);
  validateBuildings(buildings);

  const framePayloads = await Promise.all(
    simulation.frames.map(async (frame) => {
      const payload = await fetchJson<{
        type: string;
        features: ShadowFeature[];
        metadata: Record<string, unknown>;
      }>(`${DATA_BASE}/${frame.file}`, `shadow frame ${frame.local_time}`, signal);

      if (!Array.isArray(payload.features)) {
        throw new DatasetError(
          `Shadow frame ${frame.local_time} is malformed.`,
          "Expected a GeoJSON FeatureCollection with a `features` array.",
        );
      }
      for (const feature of payload.features) {
        if (!feature.geometry) {
          throw new DatasetError(
            `Shadow feature ${String(feature.id)} in frame ${frame.local_time} has no geometry.`,
            "Generated shadow geometry is required for every published feature.",
          );
        }
      }
      return [frame.slug, payload] as const;
    }),
  );

  const shadows: Record<string, ShadowFeature[]> = {};
  const occlusion: Record<string, OcclusionAnalysis> = {};
  for (const [slug, payload] of framePayloads) {
    shadows[slug] = payload.features;
    occlusion[slug] = payload.metadata.occlusion as OcclusionAnalysis;
  }

  return { simulation, buildings, studyArea, shadows, occlusion };
}
