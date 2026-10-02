/**
 * Presentation helpers.
 *
 * All scientific values are formatted from the dataset as generated; nothing
 * here recomputes a quantity or introduces a display-only value that could be
 * mistaken for a measurement.
 */

/** Format a metre value with a sensible number of significant decimals. */
export function formatMetres(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(2)} km`;
  return `${value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} m`;
}

export function formatSquareMetres(
  value: number | null | undefined,
  decimals = 0,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(3)} km²`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(2)} ha`;
  return `${value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} m²`;
}

export function formatDegrees(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(decimals)}°`;
}

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/** "2026-10-01" -> "01 Oct 2026". */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${String(day).padStart(2, "0")} ${months[month - 1]} ${year}`;
}

/** "2026-10-01T06:00:00+05:30" -> "06:00". */
export function formatClock(isoTimestamp: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(isoTimestamp);
  return match ? `${match[1]}:${match[2]}` : isoTimestamp;
}

/** Human label for a height method, without overstating it. */
export function describeHeightMethod(method: string): string {
  switch (method) {
    case "OSM_exact":
      return "Tagged in OpenStreetMap";
    case "documented":
      return "From published documentation";
    case "survey":
      return "Survey measured";
    case "lidar":
      return "Derived from lidar / DEM";
    case "derived_from_levels":
      return "Estimated from floor count (not measured)";
    case "unresolved":
      return "Unresolved — no documented height";
    default:
      return method;
  }
}

export function describeConfidence(confidence: string): string {
  switch (confidence) {
    case "high":
      return "High";
    case "medium":
      return "Medium";
    case "low":
      return "Low";
    case "none":
      return "None";
    default:
      return confidence;
  }
}
