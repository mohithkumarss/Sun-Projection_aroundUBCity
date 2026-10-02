"use client";

/**
 * Building inspection panel.
 *
 * Height is always shown together with how it was established. A building with
 * an unresolved height is displayed as such and is never given a number.
 */

import type { BuildingFeature, BuildingProperties, ShadowFeature } from "@/lib/types";
import {
  describeConfidence,
  describeHeightMethod,
  formatMetres,
  formatSquareMetres,
} from "@/lib/format";

export interface BuildingPanelProps {
  building: BuildingFeature | null;
  shadows: ShadowFeature[];
  currentTime: string;
  onClear: () => void;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <dt className="shrink-0 text-xs text-muted">{label}</dt>
      <dd className="text-right text-sm">{children}</dd>
    </div>
  );
}

function HeightValue({ properties }: { properties: BuildingProperties }) {
  if (properties.height_m === null) {
    return (
      <span className="text-[var(--warn)]">
        Unresolved
        <span className="block text-xs text-muted">no documented height</span>
      </span>
    );
  }
  return (
    <span>
      {formatMetres(properties.height_m)}
      <span className="block text-xs text-muted">
        {describeHeightMethod(properties.height_method)}
      </span>
    </span>
  );
}

export default function BuildingPanel({
  building,
  shadows,
  currentTime,
  onClear,
}: BuildingPanelProps) {
  if (!building) {
    return (
      <section aria-labelledby="building-heading" className="border-b border-panel-border">
        <h2
          id="building-heading"
          className="border-b border-panel-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted"
        >
          Building inspection
        </h2>
        <p className="px-4 py-4 text-xs text-muted">
          Click a building footprint on the map to inspect its height, its
          provenance, and its shadow at the selected time.
        </p>
      </section>
    );
  }

  const properties = building.properties;
  const shadow = shadows.find(
    (feature) => feature.properties.building_id === properties.id,
  );

  return (
    <section aria-labelledby="building-heading" className="border-b border-panel-border">
      <div className="flex items-center justify-between border-b border-panel-border px-4 py-2">
        <h2
          id="building-heading"
          className="text-xs font-semibold uppercase tracking-wide text-muted"
        >
          Building inspection
        </h2>
        <button
          type="button"
          onClick={onClear}
          className="text-xs text-muted hover:text-foreground"
        >
          Clear
        </button>
      </div>

      <div className="px-4 py-3">
        <h3 className="text-base font-semibold leading-tight">
          {properties.name ?? "Unnamed building"}
        </h3>
        <p className="tnum mt-0.5 text-xs text-muted">{properties.id}</p>

        <dl className="mt-3 divide-y divide-panel-border">
          <Field label="Height">
            <HeightValue properties={properties} />
          </Field>
          <Field label="Confidence">
            {describeConfidence(properties.height_confidence)}
          </Field>
          <Field label="Floors">
            {properties.levels !== null ? (
              String(properties.levels)
            ) : (
              <span className="text-muted">Not recorded</span>
            )}
          </Field>
          <Field label="Footprint area">
            {formatSquareMetres(properties.footprint_area_m2)}
          </Field>
          <Field label="Vertical model">
            {properties.vertical_model === "building_parts"
              ? `Building parts (${properties.building_part_ids.length})`
              : properties.vertical_model === "single_prism"
                ? "Single prism"
                : "None"}
          </Field>
          <Field label="Casts shadow">
            {properties.shadow_casting ? "Yes" : "No"}
          </Field>
          <Field label="Ground elevation">
            {properties.ground_elevation_m !== null
              ? formatMetres(properties.ground_elevation_m)
              : "Flat assumption (z = 0 m)"}
          </Field>
        </dl>

        <div className="mt-3 border-t border-panel-border pt-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Height provenance
          </h4>
          <p className="mt-1 text-xs leading-relaxed">
            {properties.height_source}
          </p>
          {properties.height_source_url && (
            <a
              href={properties.height_source_url}
              target="_blank"
              rel="noreferrer noopener"
              className="tnum mt-1 block break-all text-xs text-[var(--accent)] underline"
            >
              {properties.height_source_url}
            </a>
          )}
          {properties.height_conflicts.length > 0 && (
            <div className="mt-2 border-l-2 border-[var(--warn)] bg-[var(--warn)]/5 px-2 py-1.5">
              <p className="text-xs font-semibold text-[var(--warn)]">
                Source disagreement preserved
              </p>
              {properties.height_conflicts.map((conflict, i) => (
                <p key={i} className="mt-1 text-xs text-muted">
                  {conflict.issue}
                  {conflict.resolution_rule ? ` — ${conflict.resolution_rule}` : ""}
                </p>
              ))}
            </div>
          )}
        </div>

        {shadow ? (
          <div className="mt-3 border-t border-panel-border pt-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
              Shadow at {currentTime}
            </h4>
            <dl className="mt-1 divide-y divide-panel-border">
              <Field label="Shadow area">
                {formatSquareMetres(shadow.properties.shadow_area_m2)}
              </Field>
              <Field label="Max length">
                {formatMetres(shadow.properties.max_shadow_length_m)}
              </Field>
              <Field label="Direction">
                {shadow.properties.shadow_direction} (
                {shadow.properties.shadow_azimuth_deg.toFixed(1)}°)
              </Field>
              <Field label="Perimeter">
                {formatMetres(shadow.properties.shadow_perimeter_m)}
              </Field>
            </dl>
          </div>
        ) : (
          <p className="mt-3 border-t border-panel-border pt-2 text-xs text-muted">
            No shadow polygon for this building at {currentTime} — either the
            sun is below the horizon or the building has no documented height.
          </p>
        )}

        <div className="mt-3 border-t border-panel-border pt-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Source
          </h4>
          <p className="mt-1 text-xs text-muted">
            OpenStreetMap way {properties.osm_id} ({properties.source}).
            Height method:{" "}
            <span className="tnum">{properties.height_method}</span>.
          </p>
        </div>
      </div>
    </section>
  );
}
