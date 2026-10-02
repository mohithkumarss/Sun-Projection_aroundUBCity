"use client";

/**
 * UB City solar-shadow research prototype.
 *
 * This component owns application state only. All scientific geometry arrives
 * pre-computed from the Python pipeline; the browser selects and renders a
 * frame, and never recomputes a shadow.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import MapView from "@/components/map/MapView";
import Timeline from "@/components/timeline/Timeline";
import InfoPanel from "@/components/analysis/InfoPanel";
import AnalysisPanel from "@/components/analysis/AnalysisPanel";
import BuildingPanel from "@/components/building/BuildingPanel";
import Controls from "@/components/controls/Controls";
import {
  DatasetErrorPanel,
  LoadingPanel,
  TokenError,
} from "@/components/common/ErrorStates";

import { inspectToken } from "@/lib/mapbox/token";
import { DatasetError, loadDataset, type Dataset } from "@/lib/simulation/dataset";
import {
  buildAllFramesExport,
  buildFrameExport,
  downloadGeoJson,
} from "@/lib/simulation/export";
import { formatDate } from "@/lib/format";
import type { BuildingFeature, MapMode, ShadowFeature } from "@/lib/types";

export default function Page() {
  const tokenStatus = useMemo(
    () => inspectToken(process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN),
    [],
  );

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [error, setError] = useState<{ message: string; detail: string } | null>(
    null,
  );

  const [frameIndex, setFrameIndex] = useState(0);
  const [mode, setMode] = useState<MapMode>("3d");
  const [playing, setPlaying] = useState(false);
  const [frameIntervalMs, setFrameIntervalMs] = useState(1000);
  const [selectedBuildingId, setSelectedBuildingId] = useState<string | null>(
    null,
  );
  const [panelOpen, setPanelOpen] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  // Load the dataset once on mount.
  useEffect(() => {
    if (!tokenStatus.valid) return;
    const controller = new AbortController();
    loadDataset(controller.signal)
      .then(setDataset)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        if (cause instanceof DatasetError) {
          setError({ message: cause.message, detail: cause.detail });
        } else {
          setError({
            message: "Unexpected error while loading the research dataset.",
            detail: String(cause),
          });
        }
      });
    return () => controller.abort();
  }, [tokenStatus.valid]);

  const frames = dataset?.simulation.frames ?? [];
  const frame = frames[frameIndex] ?? null;

  const shadows: ShadowFeature[] = useMemo(() => {
    if (!dataset || !frame) return [];
    return dataset.shadows[frame.slug] ?? [];
  }, [dataset, frame]);

  const selectedBuilding: BuildingFeature | null = useMemo(() => {
    if (!dataset || !selectedBuildingId) return null;
    return (
      dataset.buildings.features.find(
        (feature) => feature.properties.id === selectedBuildingId,
      ) ?? null
    );
  }, [dataset, selectedBuildingId]);

  const exportOptions = useMemo(() => {
    if (!dataset) return null;
    return {
      studyAreaName: dataset.studyArea.properties.study_area_name,
      simulationSha256: dataset.simulation.metadata.simulation_sha256,
      solarMethod: dataset.simulation.metadata.solar_method.method,
      solarVersion: dataset.simulation.metadata.solar_method.pvlib_version,
      crsComputation: dataset.simulation.metadata.crs_computation,
      maxShadowLengthM: dataset.simulation.metadata.max_shadow_length_m,
      truncated: false,
    };
  }, [dataset]);

  const handleExportFrame = useCallback(() => {
    if (!dataset || !frame || !exportOptions) return;
    const document_ = buildFrameExport({
      ...exportOptions,
      frame,
      features: shadows,
    });
    downloadGeoJson(document_, `ub-city-shadow-${frame.slug}.geojson`);
  }, [dataset, frame, exportOptions, shadows]);

  const handleExportAll = useCallback(() => {
    if (!dataset || !exportOptions) return;
    const document_ = buildAllFramesExport(
      dataset.simulation.frames,
      dataset.shadows,
      exportOptions,
    );
    downloadGeoJson(document_, "ub-city-shadow-all-frames.geojson");
  }, [dataset, exportOptions]);

  // Open the side panel when a building is picked so the inspection result is
  // never hidden off-screen on a narrow viewport. This is event-driven, not an
  // effect: deriving it in an effect would cause a cascading render.
  const handleSelectBuilding = useCallback((buildingId: string | null) => {
    setSelectedBuildingId(buildingId);
    if (buildingId) setPanelOpen(true);
  }, []);

  // ---------------------------------------------------------------------
  // Explicit error states
  // ---------------------------------------------------------------------
  if (!tokenStatus.valid) {
    return <TokenError message={tokenStatus.message ?? "Token unavailable."} />;
  }
  if (error) {
    return (
      <DatasetErrorPanel
        title="Research dataset unavailable"
        message={error.message}
        detail={error.detail}
      />
    );
  }
  if (!dataset || !frame) {
    return <LoadingPanel />;
  }

  const meta = dataset.simulation.metadata;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-panel-border bg-panel px-4 py-2.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <div>
            <h1 className="text-sm font-semibold leading-tight">
              Solar shadow projection — {dataset.studyArea.properties.study_area_name}
            </h1>
            <p className="tnum mt-0.5 text-xs text-muted">
              {formatDate(meta.simulation_date)} · {meta.frame_count} hourly frames ·{" "}
              {meta.start_local.slice(11, 16)} → {meta.end_local.slice(0, 10)}{" "}
              {meta.end_local.slice(11, 16)} IST
            </p>
          </div>
          <p className="tnum text-[10px] leading-tight text-muted">
            {meta.solar_method.algorithm} · pvlib {meta.solar_method.pvlib_version}
            <br />
            computed in {meta.crs_computation} · exported as {meta.crs_storage} ·
            ground {meta.ground_model}
          </p>
        </div>
      </header>

      <Controls
        mode={mode}
        onModeChange={setMode}
        onExportFrame={handleExportFrame}
        onExportAll={handleExportAll}
        canExport={shadows.length > 0}
      />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="relative min-h-[52vh] flex-1 lg:min-h-0">
          <MapView
            token={tokenStatus.token as string}
            mode={mode}
            frame={frame}
            shadows={shadows}
            buildings={dataset.buildings}
            studyArea={dataset.studyArea}
            selectedBuildingId={selectedBuildingId}
            onSelectBuilding={handleSelectBuilding}
            maxShadowLengthM={meta.max_shadow_length_m}
            minShadowElevationDeg={meta.min_shadow_elevation_deg}
            onMapError={setMapError}
            mapError={mapError}
          />

          {/* Provenance / accuracy disclosure, deliberately plain text. */}
          <details className="absolute bottom-2 left-2 max-w-xs border border-panel-border bg-panel/95 text-xs">
            <summary className="cursor-pointer px-2 py-1.5 font-medium">
              Data provenance &amp; accuracy
            </summary>
            <div className="space-y-2 border-t border-panel-border px-2 py-2 text-muted">
              <p>
                Footprints: OpenStreetMap (ODbL), retrieved{" "}
                {dataset.buildings.metadata.retrieved_at_utc.slice(0, 10)}.
                Volunteer-surveyed geometry — positional accuracy is not
                survey grade.
              </p>
              <p>
                Heights: {dataset.simulation.buildings.filter((b) => b.shadow_casting).length}{" "}
                of {dataset.simulation.buildings.length} buildings carry a
                documented height. The remainder are shown but cast no shadow.
              </p>
              <p>
                Solar position: {meta.solar_method.algorithm}. This is the
                strongest link in the chain; building data is the weakest.
              </p>
              <p>
                Ground is a flat plane at z = 0 m. No DEM is integrated, so
                terrain relief is ignored.
              </p>
              <p className="tnum break-all">
                dataset sha256: {meta.simulation_sha256.slice(0, 24)}…
              </p>
            </div>
          </details>
        </div>

        <aside
          className={`w-full shrink-0 overflow-y-auto border-t border-panel-border bg-panel lg:w-96 lg:border-l lg:border-t-0 ${
            panelOpen ? "" : ""
          }`}
        >
          <button
            type="button"
            onClick={() => setPanelOpen((open) => !open)}
            className="tnum flex w-full items-center justify-between border-b border-panel-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted lg:hidden"
            aria-expanded={panelOpen}
          >
            Data panels {panelOpen ? "▾" : "▸"}
          </button>

          <div className={panelOpen ? "block" : "hidden lg:block"}>
            <InfoPanel frame={frame} simulation={dataset.simulation} />
            <BuildingPanel
              building={selectedBuilding}
              shadows={shadows}
              currentTime={frame.local_time}
              onClear={() => setSelectedBuildingId(null)}
            />
            <AnalysisPanel
              simulation={dataset.simulation}
              frame={frame}
              selectedBuildingId={selectedBuildingId}
            />
          </div>
        </aside>
      </div>

      <Timeline
        frames={frames}
        index={frameIndex}
        onIndexChange={setFrameIndex}
        playing={playing}
        onPlayingChange={setPlaying}
        frameIntervalMs={frameIntervalMs}
        onIntervalChange={setFrameIntervalMs}
        disabled={false}
      />
    </div>
  );
}
