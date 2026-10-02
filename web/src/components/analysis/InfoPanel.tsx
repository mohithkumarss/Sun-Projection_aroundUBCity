"use client";

/**
 * Solar + shadow information panel for the selected timestamp.
 *
 * Every value shown here is read from the generated dataset. Nothing is
 * recomputed in the browser.
 */

import type { Simulation, SimulationFrame } from "@/lib/types";
import {
  formatClock,
  formatDate,
  formatDegrees,
  formatMetres,
  formatPercent,
  formatSquareMetres,
} from "@/lib/format";

export interface InfoPanelProps {
  frame: SimulationFrame;
  simulation: Simulation;
}

function Row({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <dt className="text-xs text-muted">{label}</dt>
      <dd
        className={`tnum text-sm ${
          emphasis ? "font-semibold" : ""
        } text-right`}
      >
        {value}
      </dd>
    </div>
  );
}

export default function InfoPanel({ frame, simulation }: InfoPanelProps) {
  const solar = simulation.metadata.solar_method;
  const night = !frame.sun_above_horizon;

  return (
    <section aria-labelledby="info-heading" className="border-b border-panel-border">
      <h2
        id="info-heading"
        className="border-b border-panel-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted"
      >
        Solar position &amp; shadow metrics
      </h2>

      <div className="px-4 py-3">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <span className="tnum text-xl font-semibold">{frame.local_time}</span>
          <span className="text-xs text-muted">
            {formatDate(frame.date_local)} IST
          </span>
        </div>

        <dl className="divide-y divide-panel-border">
          <Row label="Solar azimuth" value={formatDegrees(frame.solar_azimuth_deg)} />
          <Row
            label="Solar elevation"
            value={formatDegrees(frame.solar_elevation_deg)}
            emphasis
          />
          <Row label="Solar zenith" value={formatDegrees(frame.solar_zenith_deg)} />
          <Row
            label="Apparent elevation"
            value={formatDegrees(frame.apparent_elevation_deg)}
          />
          <Row label="Shadow direction" value={`${frame.shadow_direction} (${formatDegrees(frame.shadow_azimuth_deg)})`} />
          <Row
            label="Sun above horizon"
            value={frame.sun_above_horizon ? "Yes" : "No"}
          />
          <Row
            label="Active building shadows"
            value={
              frame.shadow_emitted
                ? String(frame.active_building_shadows)
                : "0 (no projection)"
            }
            emphasis={frame.shadow_emitted}
          />
          <Row
            label="Total shadow area"
            value={
              frame.shadow_emitted
                ? formatSquareMetres(frame.total_shadow_area_m2)
                : "—"
            }
          />
          <Row
            label="Area within study area"
            value={
              frame.shadow_emitted
                ? formatSquareMetres(frame.total_shadow_area_in_study_area_m2)
                : "—"
            }
          />
          <Row
            label="Max shadow length"
            value={
              frame.shadow_emitted ? formatMetres(frame.max_shadow_length_m) : "—"
            }
          />
          <Row
            label="Study-area coverage"
            value={
              frame.shadow_emitted
                ? formatPercent(frame.shadow_coverage_percent)
                : "—"
            }
          />
        </dl>

        {frame.truncated && (
          <p className="mt-2 border-l-2 border-[var(--warn)] bg-[var(--warn)]/5 px-2 py-1.5 text-xs text-[var(--warn)]">
            Shadow length clipped at the{" "}
            {simulation.metadata.max_shadow_length_m} m limit. The natural
            projection at this solar elevation would be far longer, so the
            reported area is a lower bound rather than the true value.
          </p>
        )}

        {night && (
          <p className="mt-2 border-l-2 border-[var(--night)] bg-[var(--night)]/5 px-2 py-1.5 text-xs text-[var(--night)]">
            The sun is below the horizon. No solar shadow is computed or drawn
            for this frame, per the night-time handling rule.
          </p>
        )}

        <div className="mt-3 border-t border-panel-border pt-2">
          <dl className="divide-y divide-panel-border">
            <Row label="Sunrise" value={solar.sunrise ? formatClock(solar.sunrise) : "—"} />
            <Row label="Sunset" value={solar.sunset ? formatClock(solar.sunset) : "—"} />
            <Row
              label="Timestamp"
              value={frame.timestamp}
            />
          </dl>
        </div>
      </div>
    </section>
  );
}
