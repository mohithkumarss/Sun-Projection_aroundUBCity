"use client";

/**
 * Research analytics.
 *
 * Presents the pre-computed per-building and study-area statistics as a table
 * plus a simple bar chart. No subjective labels ("best", "worst") are used;
 * only measured quantities are shown.
 */

import { useMemo } from "react";import type { Simulation, SimulationFrame } from "@/lib/types";
import {
  formatMetres,
  formatPercent,
  formatSquareMetres,
} from "@/lib/format";

export interface AnalysisPanelProps {
  simulation: Simulation;
  frame: SimulationFrame;
  selectedBuildingId: string | null;
}

export default function AnalysisPanel({
  simulation,
  frame,
  selectedBuildingId,
}: AnalysisPanelProps) {
  const analysis = simulation.analysis;
  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const building of simulation.buildings) {
      map.set(building.id, building.name ?? building.id);
    }
    return map;
  }, [simulation.buildings]);

  const maxCoverage = Math.max(
    ...simulation.frames.map((f) => f.shadow_coverage_percent),
    0.0001,
  );

  const perBuilding = analysis.per_building;
  const selected =
    perBuilding.find((entry) => entry.building_id === selectedBuildingId) ?? null;

  return (
    <section aria-labelledby="analysis-heading" className="border-b border-panel-border">
      <h2
        id="analysis-heading"
        className="border-b border-panel-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted"
      >
        Research analytics
      </h2>

      <div className="px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
          Study-area shadow coverage by timestamp
        </h3>
        <p className="tnum mt-1 text-xs text-muted">
          Study area {formatSquareMetres(analysis.study_area.area_m2)} ·
          peak coverage{" "}
          {formatPercent(analysis.study_area.max_shadow_coverage_percent)} at{" "}
          {peakFrame(simulation.frames)}
        </p>

        {/* Bar chart: coverage per frame. Bars are proportional to the max
            coverage so the shape of the day is readable at a glance. */}
        <div className="mt-3 flex h-24 items-end gap-px" role="img"
          aria-label="Bar chart of shadow coverage percentage for each of the 25 hourly frames">
          {simulation.frames.map((f) => {
            const height = f.shadow_emitted
              ? Math.max(2, (f.shadow_coverage_percent / maxCoverage) * 100)
              : 0;
            const isCurrent = f.index === frame.index;
            return (
              <div
                key={f.slug}
                className="flex-1"
                style={{ height: `${height}%` }}
                title={`${f.local_time} — ${
                  f.shadow_emitted
                    ? `${formatPercent(f.shadow_coverage_percent)} (${formatSquareMetres(f.total_shadow_area_in_study_area_m2)})`
                    : "no shadow (sun below threshold)"
                }`}
              >
                <div
                  className={`h-full w-full ${
                    isCurrent
                      ? "bg-[var(--accent)]"
                      : f.shadow_emitted
                        ? "bg-[var(--muted)]/45"
                        : "bg-transparent"
                  }`}
                />
              </div>
            );
          })}
        </div>
        <div className="tnum mt-1 flex justify-between text-[10px] text-muted">
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>06:00 (+1)</span>
        </div>

        <table className="mt-4 w-full text-left text-xs">
          <caption className="sr-only">
            Shadow coverage, area, and maximum length for every frame
          </caption>
          <thead>
            <tr className="border-b border-panel-border text-muted">
              <th scope="col" className="py-1 pr-2 font-medium">Time</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Coverage</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Area</th>
              <th scope="col" className="py-1 text-right font-medium">Max length</th>
            </tr>
          </thead>
          <tbody className="tnum">
            {simulation.frames.map((f) => (
              <tr
                key={f.slug}
                className={
                  f.index === frame.index
                    ? "bg-[var(--accent)]/8 font-semibold"
                    : "border-b border-panel-border/60"
                }
              >
                <td className="py-1 pr-2">{f.local_time}</td>
                <td className="py-1 pr-2 text-right">
                  {f.shadow_emitted ? formatPercent(f.shadow_coverage_percent) : "—"}
                </td>
                <td className="py-1 pr-2 text-right">
                  {f.shadow_emitted
                    ? formatSquareMetres(f.total_shadow_area_in_study_area_m2)
                    : "—"}
                </td>
                <td className="py-1 text-right">
                  {f.shadow_emitted ? formatMetres(f.max_shadow_length_m) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-muted">
          Per-building shadow statistics
        </h3>
        {selected ? (
          <p className="mt-1 text-xs text-muted">
            Filtered to the selected building. Clear the selection to see all.
          </p>
        ) : null}
        <table className="mt-2 w-full text-left text-xs">
          <caption className="sr-only">
            Shadow area, maximum length, and frame count for each building
          </caption>
          <thead>
            <tr className="border-b border-panel-border text-muted">
              <th scope="col" className="py-1 pr-2 font-medium">Building</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Frames</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">Max area</th>
              <th scope="col" className="py-1 text-right font-medium">Max length</th>
            </tr>
          </thead>
          <tbody className="tnum">
            {perBuilding.map((entry) => {
              const isSelected = entry.building_id === selectedBuildingId;
              if (selectedBuildingId && !isSelected) return null;
              return (
                <tr
                  key={entry.building_id}
                  className={
                    isSelected
                      ? "bg-[var(--accent)]/8 font-semibold"
                      : "border-b border-panel-border/60"
                  }
                >
                  <td className="py-1 pr-2">
                    {names.get(entry.building_id) ?? entry.building_id}
                  </td>
                  <td className="py-1 pr-2 text-right">
                    {entry.frames_with_shadow}
                  </td>
                  <td className="py-1 pr-2 text-right">
                    {formatSquareMetres(entry.max_shadow_area_m2)}
                  </td>
                  <td className="py-1 text-right">
                    {formatMetres(entry.max_shadow_length_m)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function peakFrame(frames: SimulationFrame[]): string {
  let best = frames[0];
  for (const frame of frames) {
    if (frame.total_shadow_area_in_study_area_m2 > best.total_shadow_area_in_study_area_m2) {
      best = frame;
    }
  }
  return best.local_time;
}
