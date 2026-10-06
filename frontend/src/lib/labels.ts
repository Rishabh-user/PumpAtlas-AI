/**
 * Domain labelling.
 *
 * The generic humaniser turned `centrifugal_oh1` into "Centrifugal oh1", which is not
 * how any rotating-equipment engineer reads it. API 610 type codes are upper-case and
 * carry a family; seal plans and area classifications have conventional spellings. A
 * product for this audience gets them right.
 */

const EM_DASH = "\u2014";

const PUMP_TYPES: Record<string, { code: string; family: string }> = {
  centrifugal_oh1: { code: "OH1", family: "Overhung, foot-mounted" },
  centrifugal_oh2: { code: "OH2", family: "Overhung, centreline-mounted" },
  centrifugal_oh3: { code: "OH3", family: "Overhung, vertical in-line" },
  centrifugal_oh5: { code: "OH5", family: "Overhung, close-coupled" },
  centrifugal_oh6: {
    code: "OH6",
    family: "Overhung, high-speed integral gear",
  },
  between_bearings_bb1: {
    code: "BB1",
    family: "Between bearings, axially split",
  },
  between_bearings_bb2: {
    code: "BB2",
    family: "Between bearings, radially split",
  },
  between_bearings_bb3: {
    code: "BB3",
    family: "Between bearings, multistage axial split",
  },
  between_bearings_bb4: {
    code: "BB4",
    family: "Between bearings, single casing",
  },
  between_bearings_bb5: { code: "BB5", family: "Between bearings, barrel" },
  vertically_suspended_vs1: {
    code: "VS1",
    family: "Vertically suspended, diffuser",
  },
  vertically_suspended_vs4: {
    code: "VS4",
    family: "Vertically suspended, line shaft sump",
  },
  vertically_suspended_vs6: {
    code: "VS6",
    family: "Vertically suspended, double casing",
  },
  submersible: { code: "Submersible", family: "" },
  reciprocating_plunger: { code: "Reciprocating", family: "Plunger" },
  reciprocating_diaphragm: { code: "Reciprocating", family: "Diaphragm" },
  rotary_screw: { code: "Rotary", family: "Screw" },
  rotary_gear: { code: "Rotary", family: "Gear" },
  rotary_progressive_cavity: { code: "Rotary", family: "Progressive cavity" },
  metering_dosing: { code: "Metering", family: "Dosing" },
  multiphase: { code: "Multiphase", family: "" },
  esp: { code: "ESP", family: "Electric submersible" },
  firewater: { code: "Firewater", family: "NFPA 20" },
  other: { code: "Other", family: "" },
};

const STANDARDS: Record<string, string> = {
  api_610: "API 610",
  api_674: "API 674",
  api_675: "API 675",
  api_676: "API 676",
  api_682: "API 682",
  api_685: "API 685",
  iso_13709: "ISO 13709",
  iso_5199: "ISO 5199",
  iso_2858: "ISO 2858",
  asme_b73_1: "ASME B73.1",
  asme_b73_2: "ASME B73.2",
  nfpa_20: "NFPA 20",
  hydraulic_institute: "Hydraulic Institute",
  en_733: "EN 733",
  client_spec: "Client specification",
  other: "Other",
};

const AREA_CLASSES: Record<string, string> = {
  zone_0: "Zone 0",
  zone_1: "Zone 1",
  zone_2: "Zone 2",
  class_i_div_1: "Class I Div 1",
  class_i_div_2: "Class I Div 2",
  safe_area: "Safe area",
  other: "Other",
};

const SEAL_TYPES: Record<string, string> = {
  api682_arrangement_1: "API 682 Arr. 1",
  api682_arrangement_2: "API 682 Arr. 2",
  api682_arrangement_3: "API 682 Arr. 3",
  packed_gland: "Packed gland",
  magnetic_drive: "Magnetic drive",
  canned_motor: "Canned motor",
  seal_less_other: "Seal-less (other)",
  other: "Other",
};

const DRIVERS: Record<string, string> = {
  electric_motor: "Electric motor",
  vfd_electric_motor: "Electric motor (VFD)",
  steam_turbine: "Steam turbine",
  gas_turbine: "Gas turbine",
  diesel_engine: "Diesel engine",
  hydraulic: "Hydraulic",
  air_motor: "Air motor",
  other: "Other",
};

const VENDOR_TIERS: Record<string, string> = {
  tier_1_oem: "Tier 1 OEM",
  tier_2_oem: "Tier 2 OEM",
  tier_3_oem: "Tier 3 OEM",
  packager: "Packager",
  authorized_distributor: "Authorised distributor",
  agent_representative: "Agent / representative",
  aftermarket_service: "Aftermarket service",
  unclassified: "Unclassified",
};

const CONFIDENCE: Record<string, string> = {
  verified: "Verified",
  vendor_declared: "Vendor declared",
  third_party: "Third party",
  ai_extracted: "AI extracted",
  estimated: "Estimated",
  unknown: "Unknown",
};

const APPROVAL: Record<string, string> = {
  approved: "Approved",
  conditionally_approved: "Conditionally approved",
  pending_qualification: "Pending qualification",
  under_review: "Under review",
  not_approved: "Not approved",
  suspended: "Suspended",
  blacklisted: "Blacklisted",
};

const ACRONYMS = new Set([
  "api",
  "iso",
  "asme",
  "nfpa",
  "npsh",
  "fpso",
  "esg",
  "hse",
  "qaqc",
  "qa",
  "qc",
  "fat",
  "sat",
  "mtbf",
  "mttr",
  "nace",
  "atex",
  "iecex",
  "oem",
  "ip",
  "dft",
  "lei",
  "vat",
  "hs",
  "us",
  "eu",
  "uk",
  "otd",
  "bep",
  "cog",
  "ga",
  "itp",
  "ncr",
  "avl",
  "soc2",
  "iec",
  "rpm",
  "psi",
  "kw",
]);

/** Title-case a snake_case identifier, keeping domain acronyms upper-case. */
export function humanise(value: string | null | undefined): string {
  if (!value) return EM_DASH;
  const words = value.replace(/[_-]+/g, " ").trim().split(/\s+/);
  if (!words.length) return EM_DASH;
  return words
    .map((word, index) => {
      const lower = word.toLowerCase();
      if (ACRONYMS.has(lower)) return lower.toUpperCase();
      if (/^\d+$/.test(word)) return word;
      return index === 0
        ? word.charAt(0).toUpperCase() + lower.slice(1)
        : lower;
    })
    .join(" ");
}

/**
 * Column and field labels drop the unit suffix baked into the identifier, because the
 * value beside them already carries the unit. "Rated capacity m3h ... 305 m3/h" reads
 * as two different quantities on a quick scan; "Rated capacity ... 305 m3/h" does not.
 *
 * `pct` is dropped rather than uppercased for the same reason - `ratioAsPct` renders the
 * "%" on the value.
 */
const UNIT_SUFFIXES = new Set([
  "m3h",
  "m3",
  "m2",
  "m",
  "mm",
  "cm",
  "kg",
  "tonnes",
  "kw",
  "hp",
  "rpm",
  "barg",
  "bar",
  "kpa",
  "mpa",
  "psi",
  "c",
  "f",
  "k",
  "usd",
  "eur",
  "gbp",
  "pct",
  "amount",
  "hours",
  "weeks",
  "months",
  "days",
  "years",
  "cst",
  "nm",
  "db",
  "micron",
  "ppm",
  "kva",
  "litres",
  "amps",
  "volts",
  "hz",
]);

/** Field identifier -> label, with the unit suffix stripped. */
export function fieldLabel(field: string | null | undefined): string {
  if (!field) return EM_DASH;
  const parts = field.split("_");
  while (
    parts.length > 1 &&
    UNIT_SUFFIXES.has(parts[parts.length - 1]!.toLowerCase())
  ) {
    parts.pop();
  }
  return humanise(parts.join("_"));
}

/** "OH2" - the code an engineer scans a table for. */
export function pumpTypeCode(value: string | null | undefined): string {
  if (!value) return EM_DASH;
  return PUMP_TYPES[value]?.code ?? humanise(value);
}

export function standardLabel(value: string | null | undefined): string {
  return value ? (STANDARDS[value] ?? humanise(value)) : EM_DASH;
}

function areaClassLabel(value: string | null | undefined): string {
  return value ? (AREA_CLASSES[value] ?? humanise(value)) : EM_DASH;
}

function sealLabel(value: string | null | undefined): string {
  return value ? (SEAL_TYPES[value] ?? humanise(value)) : EM_DASH;
}

function driverLabel(value: string | null | undefined): string {
  return value ? (DRIVERS[value] ?? humanise(value)) : EM_DASH;
}

export function vendorTierLabel(value: string | null | undefined): string {
  return value ? (VENDOR_TIERS[value] ?? humanise(value)) : EM_DASH;
}

export function confidenceLabel(value: string | null | undefined): string {
  return value ? (CONFIDENCE[value] ?? humanise(value)) : "Unknown";
}

export function approvalLabel(value: string | null | undefined): string {
  return value ? (APPROVAL[value] ?? humanise(value)) : EM_DASH;
}

/** Dispatch by field name, so one call site handles every vocabulary. */
export function labelFor(
  field: string,
  value: string | null | undefined,
): string {
  switch (field) {
    case "pump_type":
    case "pump_types":
      return pumpTypeCode(value);
    case "applicable_standard":
    case "standards":
      return standardLabel(value);
    case "area_classification":
    case "area_classifications":
      return areaClassLabel(value);
    case "seal_system_type":
    case "seal_system_types":
      return sealLabel(value);
    case "driver_type":
    case "driver_types":
      return driverLabel(value);
    case "vendor_tier":
    case "vendor_tiers":
      return vendorTierLabel(value);
    case "confidence_level":
    case "confidence_levels":
      return confidenceLabel(value);
    case "vendor_approval_status":
    case "vendor_approval_statuses":
      return approvalLabel(value);
    default:
      return humanise(value);
  }
}
