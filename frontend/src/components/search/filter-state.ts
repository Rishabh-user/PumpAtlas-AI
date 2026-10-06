import type { FacetValue } from "@/types/api";

/**
 * Search filter state.
 *
 * Two shapes of vocabulary feed the rail. Enumerated fields (pump type, standard, area
 * classification, …) come from `/search/filters/options` and exist whether or not any
 * record uses them. Open fields (country of origin, certifications) are not enumerable,
 * so their options come from the result facets — the rail can only offer what the data
 * actually contains.
 */
export interface FilterOptions {
  pump_types: string[];
  standards: string[];
  area_classifications: string[];
  seal_system_types: string[];
  driver_types: string[];
  incoterms: string[];
  vendor_approval_statuses: string[];
  vendor_tiers: string[];
  confidence_levels: string[];
  verification_statuses: string[];
  sort_options: string[];
}

export interface FilterState {
  query: string;
  pump_types: string[];
  standards: string[];
  countries: string[];
  certifications: string[];
  area_classifications: string[];
  confidence_levels: string[];
  vendor_approval_statuses: string[];
  capacity_min: string;
  capacity_max: string;
  head_min: string;
  head_max: string;
  npshr_max: string;
  price_max: string;
  lead_time_max: string;
  weight_max: string;
  fpso_only: boolean;
  nace_only: boolean;
  sort: string;
}

export const EMPTY_FILTERS: FilterState = {
  query: "",
  pump_types: [],
  standards: [],
  countries: [],
  certifications: [],
  area_classifications: [],
  confidence_levels: [],
  vendor_approval_statuses: [],
  capacity_min: "",
  capacity_max: "",
  head_min: "",
  head_max: "",
  npshr_max: "",
  price_max: "",
  lead_time_max: "",
  weight_max: "",
  fpso_only: false,
  nace_only: false,
  sort: "relevance",
};

export const LIST_KEYS = [
  "pump_types",
  "standards",
  "countries",
  "certifications",
  "area_classifications",
  "confidence_levels",
  "vendor_approval_statuses",
] as const satisfies readonly (keyof FilterState)[];

/** Labels for the removable active-filter chips. */
export const RANGE_LABELS: Record<string, string> = {
  capacity_min: "Capacity from",
  capacity_max: "Capacity to",
  head_min: "Head from",
  head_max: "Head to",
  npshr_max: "Max NPSHr",
  price_max: "Max price",
  lead_time_max: "Max lead time",
  weight_max: "Max dry weight",
  fpso_only: "FPSO experience",
  nace_only: "NACE compliant",
};

/** Unit per range input, keyed by the state field. */
export const RANGE_UNITS: Record<string, string> = {
  capacity_min: "m³/h",
  capacity_max: "m³/h",
  head_min: "m",
  head_max: "m",
  npshr_max: "m",
  price_max: "USD",
  lead_time_max: "wk",
  weight_max: "kg",
};

/** Unit per measure, for the rail where one unit labels a min/max pair. */
export const MEASURE_UNITS = {
  capacity: "m³/h",
  head: "m",
  npshr: "m",
  price: "USD",
  lead_time: "weeks",
  weight: "kg",
} as const;

/** How many filters are actually applied — drives the badge and "clear all". */
export function activeFilterCount(filters: FilterState): number {
  let count = 0;
  for (const [key, value] of Object.entries(filters)) {
    if (key === "query" || key === "sort") continue;
    if (Array.isArray(value)) count += value.length;
    else if (typeof value === "string" && value.trim()) count += 1;
    else if (value === true) count += 1;
  }
  return count;
}

export function toNumber(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export type FacetMap = Record<string, Record<string, number>>;

/**
 * The API returns facets as `{field: [{value, count}]}`. The rail wants to look a count
 * up by value, so flatten once here rather than scanning an array per checkbox row.
 * Null-valued buckets are dropped: "no value recorded" is not a filterable option.
 */
export function normaliseFacets(
  facets: Record<string, FacetValue[]> | undefined,
): FacetMap {
  const out: FacetMap = {};
  for (const [field, buckets] of Object.entries(facets ?? {})) {
    const counts: Record<string, number> = {};
    for (const bucket of buckets) {
      if (bucket.value !== null) counts[bucket.value] = bucket.count;
    }
    out[field] = counts;
  }
  return out;
}

/** Facet keys, so the rail can offer open-vocabulary options the data actually has. */
export function facetValues(
  facets: FacetMap,
  key: string,
  selected: string[],
): string[] {
  const fromData = Object.keys(facets[key] ?? {});
  // A selected value must stay listed even after it filters itself out of the facets,
  // or the user cannot untick it.
  return [...new Set([...fromData, ...selected])];
}
