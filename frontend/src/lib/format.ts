/** Display helpers. Units are shown explicitly - a bare number is a procurement hazard. */

import { humanise } from "@/lib/labels";

const EM_DASH = "\u2014";

export function num(
  value: number | string | null | undefined,
  options: { unit?: string; decimals?: number } = {},
): string {
  if (value === null || value === undefined || value === "") return EM_DASH;
  const parsed = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(parsed)) return EM_DASH;
  const decimals = options.decimals ?? (Math.abs(parsed) >= 100 ? 0 : 1);
  const formatted = parsed.toLocaleString("en-GB", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return options.unit ? `${formatted} ${options.unit}` : formatted;
}

export function money(
  value: number | null | undefined,
  currency = "USD",
): string {
  if (value === null || value === undefined) return EM_DASH;
  return value.toLocaleString("en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });
}

/** Consumed by `ratioAsPct`; not part of this module's surface. */
function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return EM_DASH;
  return value.toFixed(value >= 10 ? 0 : 1) + "%";
}

export function ratioAsPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return EM_DASH;
  // Ratios are stored 0-1, but vendor data sometimes arrives as 0-100; accept both.
  return pct(value <= 1 ? value * 100 : value);
}

export function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return EM_DASH;
  if (Array.isArray(value)) return value.length ? value.join(", ") : EM_DASH;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return EM_DASH;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return EM_DASH;
  return parsed.toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function dateOnly(value: string | null | undefined): string {
  if (!value) return EM_DASH;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return EM_DASH;
  return parsed.toLocaleDateString("en-GB", { dateStyle: "medium" });
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return EM_DASH;
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index] ?? "B"}`;
}

/** Spec field -> unit. Consumed by `fieldValue`; not part of this module's surface. */
const FIELD_UNITS: Record<string, string> = {
  rated_capacity_m3h: "m3/h",
  min_capacity_m3h: "m3/h",
  max_capacity_m3h: "m3/h",
  rated_head_m: "m",
  max_head_m: "m",
  npsh_required_m: "m",
  hydraulic_efficiency_pct: "%",
  bep_efficiency_pct: "%",
  rated_power_kw: "kW",
  rated_speed_rpm: "rpm",
  casing_design_pressure_barg: "barg",
  max_allowable_working_pressure_barg: "barg",
  hydrostatic_test_pressure_barg: "barg",
  fluid_temperature_max_c: "degC",
  dry_weight_kg: "kg",
  operating_weight_kg: "kg",
  shipping_weight_kg: "kg",
  max_maintenance_lift_weight_kg: "kg",
  footprint_area_m2: "m2",
  overall_length_mm: "mm",
  overall_width_mm: "mm",
  overall_height_mm: "mm",
  standard_lead_time_weeks: "weeks",
  expedited_lead_time_weeks: "weeks",
  logistics_lead_time_weeks: "weeks",
  fat_duration_days: "days",
  warranty_months: "months",
  mtbf_hours: "h",
  lifecycle_cost_usd: "USD",
  base_price_usd: "USD",
};

/**
 * An extracted value as editable text — what to put in a "correct it" box.
 *
 * Deliberately not :func:`fieldValue`, which is for *reading*: that humanises
 * `centrifugal_oh1` to "Centrifugal oh1" and renders 310000 as "US$310,000". Round-trip
 * either of those back to the API and the vocabulary gate rejects it, so what goes in
 * the box is the raw value with only the shaping the API will accept back — a list as
 * comma-separated text, which its column coercion already parses.
 */
export function editableValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value))
    return value.map((entry) => String(entry)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function fieldValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return EM_DASH;
  const unit = FIELD_UNITS[field];
  if (typeof value === "number" && unit === "USD") return money(value);
  if (typeof value === "number") return num(value, { unit });
  if (typeof value === "string" && unit && !Number.isNaN(Number(value))) {
    return num(Number(value), { unit });
  }
  if (
    typeof value === "string" &&
    /^[a-z0-9_]+$/.test(value) &&
    value.includes("_")
  ) {
    return humanise(value);
  }
  return text(value);
}
