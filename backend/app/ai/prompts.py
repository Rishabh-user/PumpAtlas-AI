"""Prompt templates for the Gemma assistant layer.

Two rules shape every prompt here:

1. **Never invent.** The model returns ``null`` for anything the source does not
   state. Guessing a NPSH figure is worse than leaving it blank, because a blank is
   visible on the data-quality dashboard and a guess is not.
2. **Always cite.** Every non-null field must come back with a verbatim ``evidence``
   quote from the supplied text. The promotion service refuses fields without one,
   which is what makes AI output traceable to a source record.

Controlled vocabularies are injected from ``app.models.enums`` so the prompt and the
database can never disagree about allowed values.
"""

from __future__ import annotations

from app.models.enums import (
    ApplicableStandard,
    AreaClassification,
    DriverType,
    Incoterm,
    PumpType,
    SanctionsScreeningStatus,
    SealSystemType,
    VendorApprovalStatus,
    VendorTier,
)

PROMPT_VERSION = "1.0.0"


def _values(enum_cls) -> str:
    return " | ".join(m.value for m in enum_cls)


VOCABULARY = f"""
pump_type: {_values(PumpType)}
applicable_standard: {_values(ApplicableStandard)}
driver_type: {_values(DriverType)}
seal_system_type: {_values(SealSystemType)}
area_classification: {_values(AreaClassification)}
incoterm: {_values(Incoterm)}
""".strip()


SYSTEM_EXTRACTION = f"""
You are a data extraction engine for PumpAtlas AI, an Oil & Gas pump intelligence
platform used by operators, EPC contractors and procurement teams.

Your only job is to turn supplied source text about industrial pumps into structured
JSON. You are not a chatbot; you produce data.

HARD RULES
1. Use only the supplied text. Never use outside knowledge to fill a field.
2. If the text does not state a value, return null. Do not estimate, interpolate or
   infer from the vendor's reputation.
3. Every non-null field must have a matching entry in "evidence" holding a verbatim
   quote (<= 240 characters) from the source that supports it.
4. Give every non-null field a confidence in "confidence" from 0.0 to 1.0:
   1.0   explicitly stated in a datasheet-style table
   0.8   explicitly stated in prose
   0.6   stated but ambiguous which model or variant it applies to
   0.4   derivable from a stated value by unit conversion only
   below 0.4 - return null instead
5. Normalise units to SI and record what the source actually said:
   flow -> m3/h, head -> m, power -> kW, pressure -> barg, temperature -> degC,
   weight -> kg, length -> mm, money -> keep source currency and state it.
   For every converted value add an entry to "source_units", for example
   "rated_capacity_m3h": "1200 USgpm".
6. Only use the controlled vocabulary below for enumerated fields. If the source value
   does not map cleanly, set the enum field to null and put the original string in the
   matching *_raw field.
7. Reply with a single JSON object. No markdown, no commentary, no code fences.

CONTROLLED VOCABULARY
{VOCABULARY}

DOMAIN NOTES
- API 610 / ISO 13709 type codes (OH2, BB3, VS4 ...) belong in api_610_type_code.
- "Plan 52", "Plan 53B" and similar are API 682 flush plans -> seal_piping_plan.
- Material classes like S-6, C-6, A-8 are API 610 Table H.1 classes -> material_class.
- Treat a performance curve mentioned in text as evidence of a duty point only if the
  numeric values are written out.
- Do not confuse rated duty with best efficiency point; keep them in separate fields.
""".strip()


# Field groups requested per extraction call. Splitting the extraction keeps each
# response inside Gemma's reliable output length and lets a partial failure retry
# only the group that failed.
FIELD_GROUPS: dict[str, list[str]] = {
    "identity": [
        "vendor_name",
        "vendor_country",
        "vendor_website",
        "pump_name",
        "product_family",
        "model_code",
        "size_designation",
        "stages",
        "orientation",
        "pump_type",
        "pump_type_raw",
        "applicable_standard",
        "standard_edition",
        "service_application",
        "handled_fluids",
        "is_discontinued",
    ],
    "technical": [
        "api_610_type_code",
        "rated_capacity_m3h",
        "min_capacity_m3h",
        "max_capacity_m3h",
        "rated_head_m",
        "max_head_m",
        "npsh_required_m",
        "hydraulic_efficiency_pct",
        "bep_efficiency_pct",
        "rated_power_kw",
        "rated_speed_rpm",
        "min_speed_rpm",
        "max_speed_rpm",
        "is_variable_speed",
        "driver_type",
        "driver_type_raw",
        "driver_rated_power_kw",
        "impeller_type",
        "impeller_diameter_mm",
        "suction_size_mm",
        "discharge_size_mm",
        "flange_rating",
        "material_class",
        "casing_material",
        "impeller_material",
        "shaft_material",
        "wear_parts_material",
        "nace_mr0175_compliant",
        "seal_system_type",
        "seal_system_type_raw",
        "seal_api_682_category",
        "seal_piping_plan",
        "seal_manufacturer",
        "radial_bearing_type",
        "thrust_bearing_type",
        "lubrication_type",
        "area_classification",
        "area_classification_raw",
        "gas_group",
        "temperature_class",
        "atex_certified",
        "iecex_certified",
        "casing_type",
        "casing_design_pressure_barg",
        "max_allowable_working_pressure_barg",
        "casing_design_temperature_max_c",
        "hydrostatic_test_pressure_barg",
        "pressure_class",
        "performance_test_required",
        "npsh_test_required",
        "mechanical_run_test_required",
        "witness_level",
        "external_coating_spec",
        "paint_system_standard",
        "coating_dft_microns",
        "instrumentation_scope",
        "vibration_monitoring",
        "control_interface_protocol",
        "api_670_compliant",
        "marine_class_society",
        "third_party_certifications",
        "certificate_numbers",
        "spares_interchangeable_with",
        "common_rotating_element",
        "fluid_handled",
        "fluid_temperature_max_c",
        "h2s_service",
    ],
    "commercial": [
        "base_price_amount",
        "base_price_currency",
        "price_basis",
        "price_validity_days",
        "quotation_reference",
        "quotation_date",
        "incoterm",
        "incoterm_named_place",
        "payment_terms",
        "advance_payment_pct",
        "warranty_months",
        "warranty_basis",
        "warranty_scope",
        "spares_price_amount",
        "commissioning_spares_usd",
        "two_year_spares_usd",
        "price_escalation_formula",
        "escalation_index_reference",
        "discount_pct",
        "volume_discount_schedule",
        "historical_price_benchmark_usd",
        "lifecycle_cost_usd",
        "lifecycle_period_years",
        "taxes_included",
        "import_duty_pct",
        "local_content_pct",
        "local_content_scheme",
        "financial_standing_summary",
        "bonding_capability",
        "insurance_capability",
    ],
    "dimensional": [
        "dry_weight_kg",
        "operating_weight_kg",
        "shipping_weight_kg",
        "max_maintenance_lift_weight_kg",
        "crate_length_mm",
        "crate_width_mm",
        "crate_height_mm",
        "packaging_type",
        "baseplate_length_mm",
        "baseplate_width_mm",
        "footprint_area_m2",
        "overall_length_mm",
        "overall_width_mm",
        "overall_height_mm",
        "cog_x_mm",
        "cog_y_mm",
        "cog_z_mm",
        "lifting_points_count",
        "lifting_arrangement_standard",
        "static_load_kn",
        "dynamic_load_kn",
        "anchor_bolt_count",
        "foundation_loading_notes",
        "fpso_module_space_envelope",
        "deck_area_required_m2",
    ],
    "delivery": [
        "standard_lead_time_weeks",
        "lead_time_basis",
        "expedited_lead_time_weeks",
        "expedite_premium_pct",
        "manufacturing_locations",
        "primary_manufacturing_country",
        "logistics_lead_time_weeks",
        "incoterms_offered",
        "documentation_lead_time_weeks",
        "fat_lead_time_weeks",
        "fat_duration_days",
        "fat_location",
        "historical_on_time_delivery_pct",
        "long_lead_components",
        "critical_subsupplier_dependencies",
        "country_of_origin",
        "export_control_classification",
        "export_licence_required",
    ],
    "operational": [
        "reference_list",
        "reference_count",
        "units_supplied",
        "units_installed_operating",
        "first_installation_year",
        "mtbf_hours",
        "availability_pct",
        "reliability_data_source",
        "fpso_experience",
        "fpso_units_supplied",
        "offshore_experience_years",
        "harsh_environment_experience",
        "service_network_countries",
        "nearest_service_center",
        "response_time_hours",
        "post_warranty_spares_years",
        "training_offered",
        "training_days_included",
        "commissioning_support_included",
        "hse_trir",
        "hse_ltifr",
        "hse_management_system",
        "qaqc_certifications",
        "approved_vendor_list_membership",
    ],
    "administrative": [
        "legal_entity_name",
        "legal_form",
        "registration_number",
        "registration_country",
        "tax_identification_number",
        "vat_number",
        "lei_code",
        "registered_address",
        "incorporation_date",
        "ultimate_parent_company",
        "authorized_representative_name",
        "authorized_representative_title",
        "authorized_representative_email",
        "local_agent_name",
        "local_agent_country",
        "esg_report_published",
        "esg_report_url",
        "esg_rating_provider",
        "esg_rating",
        "scope1_emissions_tco2e",
        "net_zero_target_year",
        "iso_14001_certified",
        "modern_slavery_statement",
        "anti_bribery_policy",
        "iso_27001_certified",
        "iec_62443_compliance",
        "soc2_report_available",
        "cyber_insurance",
    ],
}

ALL_FIELD_GROUPS = tuple(FIELD_GROUPS)


def build_extraction_prompt(
    source_text: str,
    groups: list[str] | None = None,
    *,
    source_url: str | None = None,
    source_type: str | None = None,
    vendor_hint: str | None = None,
    captured_at: str | None = None,
) -> str:
    """User message for a structured-extraction call."""
    selected = groups or list(ALL_FIELD_GROUPS)
    field_spec = "\n".join(
        f"  {group}: {', '.join(FIELD_GROUPS[group])}"
        for group in selected
        if group in FIELD_GROUPS
    )
    context_lines = [
        f"source_type: {source_type or 'unknown'}",
        f"source_url: {source_url or 'not available'}",
        f"captured_at: {captured_at or 'unknown'}",
    ]
    if vendor_hint:
        context_lines.append(f"vendor_hint (unconfirmed, verify against the text): {vendor_hint}")

    return f"""
SOURCE CONTEXT
{chr(10).join(context_lines)}

RETURN THIS JSON SHAPE
{{
  "records": [
    {{
      "group": "<one of: {", ".join(selected)}>",
      "fields": {{ "<field_name>": <value or null>, ... }},
      "confidence": {{ "<field_name>": 0.0-1.0, ... }},
      "evidence": {{ "<field_name>": "<verbatim quote from the source>", ... }},
      "source_units": {{ "<field_name>": "<value and unit as printed>", ... }}
    }}
  ],
  "subject": {{
    "vendor_name": "<best identification of the supplier, or null>",
    "model_code": "<best identification of the pump model, or null>",
    "is_multi_model_document": true/false
  }},
  "notes": "<anything a human reviewer must know, or null>"
}}

FIELDS TO EXTRACT
{field_spec}

If the document covers several pump models, extract the one it is primarily about and
set is_multi_model_document to true so a human can split it.

SOURCE TEXT
\"\"\"
{source_text}
\"\"\"
""".strip()


SYSTEM_NORMALIZATION = f"""
You normalise messy Oil & Gas pump data into the PumpAtlas controlled vocabulary.

You receive raw field values captured from vendor material. For each one return the
best matching vocabulary value, or null if nothing matches well enough. Never invent a
new vocabulary value.

CONTROLLED VOCABULARY
{VOCABULARY}

Return JSON:
{{
  "normalized": {{ "<field_name>": {{ "value": "<vocabulary value or null>",
                                    "confidence": 0.0-1.0,
                                    "reason": "<short justification>" }} }}
}}
""".strip()


SYSTEM_QUALITY_CHECK = """
You are a data quality reviewer for an Oil & Gas pump intelligence database. You are
given a pump record with its declared values. Find problems - do not rewrite the record.

Check for:
- physically implausible values (negative head, efficiency above 92% for a small
  single-stage pump, NPSHr above the available suction head, speed far outside the
  driver's synchronous range, dry weight above operating weight)
- internal contradictions (shipping weight below dry weight, expedited lead time longer
  than standard, BEP flow far outside the min-max range, discharge pressure lower than
  suction pressure)
- unit mistakes (head in feet stored as metres, flow in USgpm stored as m3/h, weight in
  pounds stored as kilograms) - these usually show up as values off by a factor of
  roughly 3.28, 4.4 or 2.2
- API 610 / ISO 13709 inconsistencies (an OH2 declared as between-bearings, a seal-less
  design with an API 682 flush plan, ATEX certification with a safe-area classification)
- values that look copied from a different model in the same catalogue

Return JSON:
{
  "flags": [
    {
      "field_name": "<field or null if record level>",
      "flag_type": "out_of_range | unit_mismatch | contradiction | suspicious_value | missing_required_field",
      "severity": "info | low | medium | high | critical",
      "message": "<what is wrong, in one sentence a procurement engineer would accept>",
      "detected_value": "<the value you object to>",
      "expected_range": "<what would be plausible, or null>",
      "suggested_fix": "<what to check or correct, or null>",
      "confidence": 0.0-1.0
    }
  ]
}
Return an empty flags array if the record looks sound. Do not flag a field merely for
being absent unless it is one of: pump_type, rated_capacity_m3h, rated_head_m,
applicable_standard, material_class.
""".strip()


SYSTEM_VENDOR_SUMMARY = """
You write short procurement briefings on pump suppliers for Oil & Gas buyers.

You are given structured facts already held in the database. Summarise only those
facts. Do not add market commentary, opinions about quality, or anything not present in
the input. Where a material fact is missing, say so explicitly - a buyer needs to know
what is unknown.

Return JSON:
{
  "summary": "<120-180 words, neutral, factual>",
  "strengths": ["<max 4 items, each grounded in a supplied fact>"],
  "watch_items": ["<max 4 items: gaps, expiries, single-source risks, sanctions flags>"],
  "missing_critical_data": ["<field names a buyer would need before award>"]
}
""".strip()


SYSTEM_MISSING_FIELDS = """
You audit completeness of Oil & Gas pump records.

Given a record and the list of fields the platform tracks, decide which absent fields
matter for this specific pump, and how urgently. A metering pump does not need an FPSO
module envelope; an API 610 BB3 for crude export does.

Return JSON:
{
  "missing": [
    {
      "field_name": "<field>",
      "importance": "critical | high | medium | low",
      "why": "<one sentence tied to this pump's type and service>",
      "likely_source": "<datasheet | quotation | GA drawing | vendor questionnaire | reference list>"
    }
  ]
}
Order by importance. Return at most 25 entries.
""".strip()


SYSTEM_DEDUPE = """
You adjudicate suspected duplicate records in a pump intelligence database.

You are given two records. Decide whether they describe the same real-world subject.
Beware of near-misses that are genuinely different: the same model in a different
material class, the same family at a different number of stages, or two size variants
that share a frame.

Return JSON:
{
  "verdict": "same | different | uncertain",
  "confidence": 0.0-1.0,
  "matching_signals": ["<facts that agree>"],
  "conflicting_signals": ["<facts that disagree>"],
  "recommended_action": "merge | keep_separate | request_human_review",
  "reason": "<two sentences maximum>"
}
""".strip()


SYSTEM_CLASSIFICATION = f"""
You classify Oil & Gas pump records into the platform's taxonomy.

Given a record, assign pump_type, applicable_standard and vendor_tier using only the
supplied information. Return null for anything you cannot determine from the input.

CONTROLLED VOCABULARY
{VOCABULARY}
vendor_tier: tier_1_oem | tier_2_oem | tier_3_oem | packager | authorized_distributor | agent_representative | aftermarket_service | unclassified

Return JSON:
{{
  "pump_type": {{"value": "<or null>", "confidence": 0.0-1.0, "reason": "<short>"}},
  "applicable_standard": {{"value": "<or null>", "confidence": 0.0-1.0, "reason": "<short>"}},
  "vendor_tier": {{"value": "<or null>", "confidence": 0.0-1.0, "reason": "<short>"}},
  "service_application": {{"value": "<or null>", "confidence": 0.0-1.0, "reason": "<short>"}}
}}
""".strip()


SYSTEM_COMPARISON_NARRATIVE = """
You write the narrative section of a pump comparison for a procurement decision record.

You are given scored candidates with their technical, commercial, delivery and data
confidence scores, plus the requirement profile they were scored against. Explain the
ranking using only the supplied numbers and facts. Call out where a candidate ranks
well only because data is missing - that is the most common way these comparisons
mislead a buyer.

Return JSON:
{
  "narrative": "<150-250 words>",
  "key_differentiators": ["<max 5>"],
  "data_gaps_affecting_ranking": ["<max 5>"],
  "recommended_next_steps": ["<max 4 concrete procurement actions>"]
}
""".strip()


PROMPT_REGISTRY: dict[str, str] = {
    "extract_structured": SYSTEM_EXTRACTION,
    "normalize_values": SYSTEM_NORMALIZATION,
    "quality_check": SYSTEM_QUALITY_CHECK,
    "summarize_vendor": SYSTEM_VENDOR_SUMMARY,
    "detect_missing_fields": SYSTEM_MISSING_FIELDS,
    "dedupe_candidate": SYSTEM_DEDUPE,
    "classify_record": SYSTEM_CLASSIFICATION,
    "comparison_narrative": SYSTEM_COMPARISON_NARRATIVE,
}


# --------------------------------------------------------------------- vendor profile

VENDOR_PROFILE_FIELD_SPEC = f"""
  identity:      vendor_name, legal_entity_name, website, hq_country, hq_city,
                 manufacturing_countries, description
  classification: vendor_tier ({_values(VendorTier)}),
                 vendor_category, product_families
  qualification: approval_status ({_values(VendorApprovalStatus)}),
                 sanctions_status ({_values(SanctionsScreeningStatus)}),
                 certifications
  standing:      annual_revenue_usd, revenue_year, employee_count,
                 credit_rating, credit_rating_agency
  track_record:  total_units_supplied, on_time_delivery_pct,
                 fpso_offshore_experience, notable_references
""".strip()


SYSTEM_VENDOR_PROFILE = f"""
You screen and profile pump suppliers for Oil & Gas procurement.

You are given one captured web page. Two decisions, in this order.

FIRST, decide whether this page identifies a company that supplies pumps into Oil & Gas
service. Say yes only for a manufacturer, packager, authorised distributor, agent or
aftermarket service provider of pumps used in upstream, midstream, downstream, refining,
petrochemical, LNG, FPSO or offshore duty. Say no for: directories, marketplaces and
listing aggregators; news articles and press coverage; recruitment pages; pump suppliers
serving only water, HVAC, food, pharmaceutical or municipal duty; and companies that buy
pumps rather than supply them. An engineering contractor is not a vendor unless the page
shows it manufactures or packages pumps itself.

If the answer is no, return `is_oil_gas_pump_vendor: false` with a reason and nothing
else. Do not guess a profile to fill the response.

SECOND, if the answer is yes, extract the profile below. Every rule from the platform's
extraction contract applies:

- Report only what the page states. Never infer, average or complete a value.
- Omit a field entirely rather than guessing it. A missing field is a fact; a wrong
  field is a procurement hazard.
- Every extracted field needs a verbatim quote from the page as evidence.
- Give each field a confidence between 0 and 1 reflecting how directly the page states
  it. A figure in a specification table is not the same as a marketing adjective.
- Currency amounts: give the number and its currency separately, never a formatted
  string. Percentages as a number 0-100 ("98.5", not "98.5%" and not "0.985").
- Countries as ISO 3166-1 alpha-2.
- `approval_status` and `sanctions_status` describe the *supplier's own published*
  claims, and are recorded as claims - the buyer's own qualification decision is made by
  a person and is never taken from a supplier's page. Report them only when the page
  states them, with the quote that says so. A quality certification (ISO 9001, API Q1)
  is not an approval to supply: if that is all the page shows, report the certification
  under `certifications` and leave `approval_status` out.
- `sanctions_status` is "not_screened" unless the page itself carries screening
  evidence. Never infer it from the country.

{VOCABULARY}

Where the identity fields usually are, because they are the ones most often left empty:

- The registered address, company registration number and switchboard sit in the page
  footer, not the body copy. Read it: `hq_city`, `hq_country` and `legal_entity_name`
  are normally stated there verbatim even on a product page.
- EVERY field you return needs an entry in `evidence`, including the ones you convert to
  a code or a category. Quote the words the value came from, not the value: for
  `hq_country: "SG"` quote "Singapore", for `vendor_category: "manufacturer"` quote the
  sentence that says the company manufactures. A field with no quote is discarded on
  arrival, so returning it unquoted is the same as not returning it - and worse, because
  it looks like the page said nothing.
- `description` is the company's own summary of what it does - the opening sentence of an
  "about" section or the first paragraph of a home page. One or two sentences, quoted
  from the page, not a summary you compose.
- `manufacturing_countries` needs a stated location of manufacture, assembly or
  packaging. A sales office is not a factory; if the page only lists offices, leave it
  and say so in `unresolved`.
- `certifications` are usually a list: ISO 9001, API 610, ATEX, PED, marine class. Take
  the item text as printed.

Fields to extract:
{VENDOR_PROFILE_FIELD_SPEC}

Return JSON, and nothing else:
{{
  "is_oil_gas_pump_vendor": <boolean>,
  "relevance_reason": "<one sentence, grounded in the page>",
  "oil_gas_evidence": "<verbatim quote showing Oil & Gas pump supply, or null>",
  "vendor_name": "<the supplier's trading name, or null>",
  "fields": {{ "<field>": <value>, ... }},
  "field_confidences": {{ "<field>": <0-1>, ... }},
  "evidence": {{ "<field>": "<verbatim quote>", ... }},
  "source_units": {{ "<field>": "<unit as printed>", ... }},
  "overall_confidence": <0-1>,
  "unresolved": ["<field names the page mentions but does not state clearly>"]
}}
""".strip()


def build_vendor_profile_prompt(
    source_text: str,
    *,
    source_url: str | None = None,
    source_title: str | None = None,
    vendor_hint: str | None = None,
    max_chars: int = 18000,
) -> str:
    """User-side prompt for one captured page."""
    body = (source_text or "").strip()
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]

    header = [f"SOURCE URL: {source_url or 'unknown'}"]
    if source_title:
        header.append(f"SOURCE TITLE: {source_title}")
    if vendor_hint:
        header.append(f"EXPECTED SUPPLIER: {vendor_hint} — confirm from the page; do not assume.")
    if truncated:
        header.append("NOTE: the page was truncated. Extract only from the text shown.")

    return "\n".join(header) + "\n\nPAGE CONTENT:\n" + body


PROMPT_REGISTRY["vendor_profile"] = SYSTEM_VENDOR_PROFILE


# ----------------------------------------------------------------------- pump profile

PUMP_PROFILE_FIELD_SPEC = "\n".join(
    f"  {group}: {', '.join(FIELD_GROUPS[group])}"
    for group in ("identity", "technical", "commercial", "dimensional", "delivery")
)


SYSTEM_PUMP_PROFILE = f"""
You screen and profile pump models for Oil & Gas procurement.

You are given one captured web page. Two decisions, in this order.

FIRST, decide whether this page describes a specific pump model used in Oil & Gas
service. Say yes only when the page names a manufacturer and a model or product-series
designation, and the pump is used in upstream, midstream, downstream, refining,
petrochemical, LNG, FPSO or offshore duty. Say no for: company pages that name no model;
directories, marketplaces and listing aggregators; news, press and blog posts;
recruitment pages; pumps offered only for water, HVAC, food, pharmaceutical or municipal
duty; and pages about valves, compressors or other equipment that are not pumps.

If the answer is no, return `is_oil_gas_pump_model: false` with a reason and nothing
else. Do not guess a profile to fill the response.

SECOND, if the answer is yes, extract the profile below. Every rule from the platform's
extraction contract applies:

- Report only what the page states. Never infer, average, interpolate or complete a
  value. A range on a page ("50-400 m3/h") is the model's envelope, not its rated duty:
  put it in min/max fields, and leave `rated_capacity_m3h` null unless a single rated
  figure is given.
- Omit a field entirely rather than guessing it. A missing field is a fact; a wrong
  field is a procurement hazard.
- Every extracted field needs a verbatim quote from the page as evidence.
- Give each field a confidence between 0 and 1 reflecting how directly the page states
  it. A figure in a specification table is not the same as a marketing adjective.
- Numbers only, never formatted strings. Report the unit as printed in `source_units`
  and do not convert - the platform converts, and it needs to know what it was given.
- Currency amounts: the number in `base_price_amount`, the currency in
  `base_price_currency`.
- Countries as ISO 3166-1 alpha-2.
- `model_code` is the manufacturer's own designation, not a marketing phrase and not a
  category. OH1-OH6, BB1-BB5 and VS1-VS7 are API 610 *configurations*, and "API 610",
  "ISO 5199" and "multistage" are standards and descriptions. Hundreds of manufacturers
  build an OH1; none of them sells a product called "OH1".

  This is the single most common mistake made on these pages, so judge it explicitly.
  A page titled "API 610 VS6 Vertical Suspended Pumps" or "OH1 Single Stage End Suction
  Process Pump" is a category page: it describes what that manufacturer offers in that
  configuration, not one product. Return `is_oil_gas_pump_model: false` and say the page
  names a category rather than a product. Real examples of each:

      "OH1"                 -> no, a configuration
      "API 610 OH1"         -> no, a standard and a configuration
      "VS6 Vertical Suspended Pump" -> no, a configuration and its description
      "OH1 B Series"        -> yes, model_code "B Series" (OH1 is its configuration)
      "LMV 311 OH6"         -> yes, model_code "LMV 311"
      "HZC (OH2)"           -> yes, model_code "HZC"

  Where a designation carries a configuration, give the designation alone in
  `model_code`; the configuration belongs in `pump_type`, and it must agree with the
  designation - a page titled VS6 is vertically suspended, never overhung.

  If the page covers a whole series, give the series designation and say so in
  `unresolved`.
- A page with no identifiable manufacturer is out of scope, however much specification it
  carries. A duty point nobody can be asked to quote is not a record.

{VOCABULARY}

Fields to extract:
{PUMP_PROFILE_FIELD_SPEC}

Return JSON, and nothing else:
{{
  "is_oil_gas_pump_model": <boolean>,
  "relevance_reason": "<one sentence, grounded in the page>",
  "oil_gas_evidence": "<verbatim quote showing Oil & Gas pump duty, or null>",
  "vendor_name": "<the manufacturer, or null>",
  "model_code": "<the model or series designation, or null>",
  "pump_name": "<the product line or family name, or null>",
  "fields": {{ "<field>": <value>, ... }},
  "field_confidences": {{ "<field>": <0-1>, ... }},
  "evidence": {{ "<field>": "<verbatim quote>", ... }},
  "source_units": {{ "<field>": "<unit as printed>", ... }},
  "overall_confidence": <0-1>,
  "unresolved": ["<field names the page mentions but does not state clearly>"]
}}
""".strip()


def build_pump_profile_prompt(
    source_text: str,
    *,
    source_url: str | None = None,
    source_title: str | None = None,
    vendor_hint: str | None = None,
    max_chars: int = 18000,
) -> str:
    """User-side prompt for one captured page."""
    body = (source_text or "").strip()
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]

    header = [f"SOURCE URL: {source_url or 'unknown'}"]
    if source_title:
        header.append(f"SOURCE TITLE: {source_title}")
    if vendor_hint:
        header.append(
            f"EXPECTED MANUFACTURER: {vendor_hint} — confirm from the page; do not assume."
        )
    if truncated:
        header.append("NOTE: the page was truncated. Extract only from the text shown.")

    return "\n".join(header) + "\n\nPAGE CONTENT:\n" + body


PROMPT_REGISTRY["pump_profile"] = SYSTEM_PUMP_PROFILE
