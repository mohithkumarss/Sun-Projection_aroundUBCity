"use client";

/**
 * Map mode toggle and GeoJSON export controls.
 */

import type { MapMode } from "@/lib/types";

export interface ControlsProps {
  mode: MapMode;
  onModeChange: (mode: MapMode) => void;
  onExportFrame: () => void;
  onExportAll: () => void;
  canExport: boolean;
}

export default function Controls({
  mode,
  onModeChange,
  onExportFrame,
  onExportAll,
  canExport,
}: ControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-panel-border bg-panel px-4 py-2">
      <div
        role="group"
        aria-label="Map mode"
        className="flex border border-panel-border"
      >
        {(["2d", "3d"] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onModeChange(option)}
            aria-pressed={mode === option}
            className={`tnum px-3 py-1.5 text-sm ${
              mode === option
                ? "bg-[var(--accent)] text-white"
                : "hover:bg-[var(--background)]"
            }`}
          >
            {option.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={onExportFrame}
          disabled={!canExport}
          className="tnum border border-panel-border px-3 py-1.5 text-sm hover:bg-[var(--background)] disabled:opacity-40"
        >
          Export this frame (GeoJSON)
        </button>
        <button
          type="button"
          onClick={onExportAll}
          disabled={!canExport}
          className="tnum border border-panel-border px-3 py-1.5 text-sm hover:bg-[var(--background)] disabled:opacity-40"
        >
          Export all 25 frames
        </button>
      </div>
    </div>
  );
}
