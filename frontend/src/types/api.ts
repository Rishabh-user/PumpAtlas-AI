/** Shapes returned by the PumpAtlas API. Kept narrow: only what the UI reads. */

export type ConfidenceLevel =
  | "verified"
  | "vendor_declared"
  | "third_party"
  | "ai_extracted"
  | "estimated"
  | "unknown";

export type VerificationStatus =
  "unverified" | "in_review" | "verified" | "disputed" | "superseded";

export type FlagSeverity = "info" | "low" | "medium" | "high" | "critical";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface SearchResultRow {
  pump_model_id: string;
  pump_id: string;
  vendor_id: string;
  label: string;
  vendor_name: string;
  pump_name: string;
  model_code: string;
  summary: string | null;
  vendor_country: string | null;
  country_of_origin: string | null;
  pump_type: string | null;
  applicable_standard: string | null;
  service_application: string | null;
  area_classification: string | null;
  seal_system_type: string | null;
  material_class: string | null;
  certifications: string[];
  vendor_approval_status: string | null;
  vendor_tier: string | null;
  fpso_experience: boolean | null;
  nace_compliant: boolean | null;
  rated_capacity_m3h: number | null;
  rated_head_m: number | null;
  npsh_required_m: number | null;
  hydraulic_efficiency_pct: number | null;
  rated_speed_rpm: number | null;
  rated_power_kw: number | null;
  base_price_usd: number | null;
  standard_lead_time_weeks: number | null;
  dry_weight_kg: number | null;
  operating_weight_kg: number | null;
  footprint_area_m2: number | null;
  on_time_delivery_pct: number | null;
  units_installed: number | null;
  mtbf_hours: number | null;
  confidence_level: ConfidenceLevel | null;
  verification_status: VerificationStatus | null;
  data_completeness_pct: number | null;
  open_flag_count: number;
  is_shared_master: boolean;
  similarity?: number | null;
}

export interface FacetValue {
  value: string | null;
  count: number;
}

export interface SearchResponse {
  items: SearchResultRow[];
  total: number;
  limit: number;
  offset: number;
  sort: string;
  facets: Record<string, FacetValue[]>;
  took_ms: number | null;
}

export interface ScorecardCriterion {
  score: number | null;
  weight: number;
  contribution: number;
  value: unknown;
  target: unknown;
  reason: string;
}

export interface Scorecard {
  kind: string;
  score: number;
  grade: string;
  fields_evaluated: number;
  fields_missing: number;
  disqualified: boolean;
  disqualification_reason: string | null;
  breakdown: Record<string, ScorecardCriterion>;
}

export interface QualityFlag {
  id: string;
  entity_type?: string;
  field_name: string | null;
  flag_type: string;
  severity: FlagSeverity;
  message: string;
  detected_value?: string | null;
  expected_range?: string | null;
  suggested_fix?: string | null;
  detected_by?: string;
  is_resolved?: boolean;
}

export interface ProvenanceEntry {
  field_name: string;
  value_text: string | null;
  previous_value_text: string | null;
  value_origin: string;
  confidence_level: ConfidenceLevel;
  confidence_score: number | null;
  source_id: string | null;
  ai_job_id: string | null;
  model_used: string | null;
  evidence_quote: string | null;
  evidence_locator: string | null;
  original_value: string | null;
  original_unit: string | null;
  is_current: boolean;
  created_at: string | null;
}

export interface ProvenanceSummary {
  total_fields_with_provenance: number;
  by_origin: Record<string, number>;
  by_confidence: Record<string, number>;
  ai_derived_fields: number;
  ai_share_pct: number | null;
}

export interface DocumentRef {
  id: string;
  filename: string;
  document_kind: string;
  size_bytes: number | null;
  page_count: number | null;
  created_at: string | null;
}

export interface SourceRef {
  id: string;
  title: string | null;
  source_type: string;
  source_url: string | null;
  captured_at: string | null;
  confidence_level: ConfidenceLevel;
  is_authoritative: boolean;
}

export interface PumpProfile {
  pump_model: Record<string, unknown>;
  pump: Record<string, unknown>;
  vendor: Record<string, unknown>;
  specs: Record<string, Record<string, unknown> | null>;
  scorecards: Scorecard[];
  open_flags: QualityFlag[];
  provenance_summary: ProvenanceSummary;
  documents: DocumentRef[];
  sources: SourceRef[];
  similar: SearchResultRow[];
}

export interface Vendor {
  id: string;
  name: string;
  country: string | null;
  hq_country: string | null;
  hq_city: string | null;
  website: string | null;
  description: string | null;
  vendor_category: string | null;
  product_families: string[] | null;
  manufacturing_countries: string[] | null;
  vendor_tier: string | null;
  /**
   * How many *other* tenancies hold this company.
   *
   * Non-zero is not a bug: a client's own supplier record and the shared-master record
   * are separate by design, and a merge across that boundary is refused. Shown so the
   * two rows read as what they are.
   */
  also_in_other_tenancies: number;
  approval_status: string | null;
  sanctions_status: string | null;
  fpso_offshore_experience: boolean | null;
  on_time_delivery_pct: number | null;
  total_units_supplied: number | null;
  data_completeness_pct: number | null;
  confidence_level: ConfidenceLevel;
  verification_status: VerificationStatus;
  ai_summary: string | null;
  is_shared_master: boolean;
}

/** An email address or phone number seen on a captured page, with where it was seen. */
export interface VendorContactSighting {
  value: string;
  seen_on: {
    source_id: string;
    url: string | null;
    title: string | null;
    captured_at: string | null;
    /** Whether the page belongs to this company, rather than a distributor or agent. */
    same_domain: boolean;
  };
}

/**
 * Contact details read off the pages a vendor record was built from.
 *
 * Only the ones not recorded yet. What the company's own site states is recorded
 * automatically with the page it came from; these are the remainder, mostly pages
 * belonging to other companies, which a person decides on.
 */
export interface VendorContactDetails {
  emails: VendorContactSighting[];
  phones: VendorContactSighting[];
}

/** One field a version changed, with what it was and what it became. */
export interface VendorVersionChange {
  field: string;
  from: unknown;
  to: unknown;
}

/**
 * A snapshot of the vendor after one change, newest first.
 *
 * `record_versions` holds the full row for rollback; the API sends only the diff, which
 * is what a reader wants — "this run added the headquarters and the product families".
 */
export interface VendorVersion {
  version: number;
  operation: string;
  created_at: string;
  change_reason: string | null;
  changed_by_user_id: string | null;
  ai_job_id: string | null;
  changes: VendorVersionChange[];
  change_count: number;
}

export interface ImportBatch {
  id: string;
  name: string;
  import_mode: string;
  source_type: string;
  status: string;
  total_items: number;
  processed_items: number;
  failed_items: number;
  promoted_items: number;
  needs_review_items: number;
  auto_promote: boolean;
  progress_pct: number;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  created_at: string | null;
}

export interface ReviewQueueItem {
  id: string;
  source_id: string | null;
  ai_job_id: string | null;
  entity_type: string;
  payload: {
    fields?: Record<string, unknown>;
    subject?: Record<string, unknown>;
  };
  field_confidences: Record<string, number>;
  evidence_spans: Record<string, { quote?: string }>;
  overall_confidence: number | null;
  confidence_level: ConfidenceLevel;
  review_decision: string;
  source_title: string | null;
  source_url: string | null;
  source_type: string | null;
  source_captured_at: string | null;
  suggested_vendor: string | null;
  suggested_model_code: string | null;
  field_count: number;
  /** Set once the candidate has been promoted; null while it is still a candidate. */
  promoted_at: string | null;
  /**
   * What the candidate became. Not a route key: it is the *spec table* when promotion
   * wrote a spec version, in which case `target_id` is that version's row id rather
   * than a record id — so only "pump_model" and "vendors" can be linked to.
   */
  target_type: string | null;
  target_id: string | null;
  /** The corrections a reviewer made, by field name, at the time of the decision. */
  reviewer_edits: Record<string, unknown>;
  review_notes: string | null;
  matched_existing_vendor_id: string | null;
  /**
   * Whether a vendor exists for this candidate, decided by the API.
   *
   * Derived server-side on purpose: the review filters select on it, so computing the
   * badge separately in the browser would let a filtered list show a card whose badge
   * contradicts the filter that selected it.
   */
  vendor_match: VendorMatch;
}

/** The vendor states a reviewer can filter the queue by. */
export type VendorMatch = "matched" | "new" | "missing";

/** Counts per bucket for the whole queue, not just the page being shown. */
export interface ReviewQueueFacets {
  total: number;
  vendor_match: Record<VendorMatch, number>;
  fields: { with_fields: number; without_fields: number };
  /** Open-ended: a new extraction contract adds a type, so this is not a union. */
  entity_type: Record<string, number>;
}

export interface QualityDashboardData {
  total_pump_models: number;
  total_vendors: number;
  avg_completeness_pct: number | null;
  records_by_confidence: Record<string, number>;
  records_by_verification: Record<string, number>;
  open_flags_by_severity: Record<string, number>;
  open_flags_by_type: Record<string, number>;
  top_missing_fields: { field_name: string; count: number }[];
  stale_records: number;
  duplicate_candidates_open: number;
  pending_ai_reviews: number;
  ai_field_share_pct: number | null;
}

export interface AuditLogEntry {
  id: number;
  occurred_at: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  entity_label: string | null;
  user_email: string | null;
  actor_type: string;
  summary: string | null;
  changes: Record<string, unknown>;
  request_id: string | null;
  ip_address: string | null;
  http_method: string | null;
  http_path: string | null;
  status_code: number | null;
}

export interface Tenant {
  id: string;
  slug: string;
  name: string;
  country: string | null;
  industry_segment: string | null;
  status: string;
  plan: string;
  can_use_shared_master: boolean;
  max_users: number;
  user_count?: number;
  vendor_count?: number;
  pump_model_count?: number;
  storage_used_mb?: number;
  open_flag_count?: number;
}

export interface ComparisonItem {
  id: string;
  pump_model_id: string | null;
  label: string | null;
  technical_score: number | null;
  commercial_score: number | null;
  delivery_risk_score: number | null;
  data_confidence_score: number | null;
  overall_score: number | null;
  rank: number | null;
  disqualified: boolean;
  disqualification_reason: string | null;
  values: Record<string, unknown>;
  score_breakdown: Record<string, unknown>;
}

export interface Comparison {
  id: string;
  name: string;
  description: string | null;
  comparison_kind: string;
  requirement_profile_id: string | null;
  status: string;
  recommendation: string | null;
  ai_narrative: string | null;
  fields_shown: string[];
  items: ComparisonItem[];
  snapshot: Record<string, unknown>;
  created_at: string | null;
}

export interface DuplicateCandidate {
  id: string;
  entity_type: string;
  entity_id_a: string;
  entity_id_b: string;
  similarity_score: number;
  match_signals: Record<string, { score?: number; detail?: string }>;
  detection_method: string;
  status: string;
  label_a: string | null;
  label_b: string | null;
}

export interface CurrentUser {
  id: string;
  tenant_id: string | null;
  email: string;
  full_name: string;
  job_title: string | null;
  is_active: boolean;
  is_platform_admin: boolean;
  roles: { name: string; display_name: string }[];
  tenant_name: string | null;
  tenant_slug: string | null;
  permissions: Record<string, string[]>;
}

/* ----------------------------------------------------------------------- chat */

export interface ChatRecordField {
  field_name: string;
  value: unknown;
}

/** One panel of a record, named as the pump profile page names it. */
export interface ChatRecordGroup {
  key: string;
  label: string;
  fields: ChatRecordField[];
  /** How many of this group's fields the record holds. */
  recorded: number;
  /** How many the schema tracks, so "6 of 21" can be said honestly. */
  tracked: number;
}

export interface ChatRecordHit {
  pump_model_id: string;
  /** "R1" — the marker the answer cites. */
  marker: string;
  label: string | null;
  vendor_name: string | null;
  vendor_id: string | null;
  model_code: string | null;
  pump_type: string | null;
  applicable_standard: string | null;
  rated_capacity_m3h: number | null;
  rated_head_m: number | null;
  confidence_level: string | null;
  verification_status: string | null;
  groups: ChatRecordGroup[];
  /** Prose held on the pump — description, AI summary. */
  notes: string[];
  recorded_count: number;
  [key: string]: unknown;
}

export interface ChatWebSource {
  /** "W1" — the marker the answer cites. */
  marker: string;
  url: string;
  title: string | null;
  excerpt: string;
  /** False when the provider returned only a link, so the answer could not quote it. */
  has_text: boolean;
}

export interface ChatNewOnWeb {
  url: string;
  title: string | null;
  vendor_hint: string | null;
}

export interface ChatAnswer {
  answer: string | null;
  model?: string;
  /** The records the answer cites as [R1], [R2]… in order. */
  records: ChatRecordHit[];
  record_total: number;
  web: ChatWebSource[];
  web_error: string | null;
  /** Pages about vendors the database does not hold — offered for capture. */
  new_on_web: ChatNewOnWeb[];
  error: string | null;
}

export interface ChatExample {
  label: string;
  query: string;
}

/**
 * What the Ask screen shows before the first question.
 *
 * The copy is served, not hard-coded, because more than one frontend renders
 * this endpoint — this app and the client deployments that reach `/chat/ask`
 * through their own backend. Editing a prompt on the platform changes it in all
 * of them with no consumer deploy.
 */
export interface ChatContext {
  web_available: boolean;
  kinds: string[];
  title?: string;
  lede?: string;
  placeholder?: string;
  examples?: ChatExample[];
}

export interface ChatCaptureResult {
  run_id: string;
  kind: string;
  queries: string[];
  transport: string | null;
  watch: string;
}

/* ---------------------------------------------------------------- AI settings */

export type AiRole = "search" | "reading";

export interface AiProviderConfig {
  id: string;
  label: string;
  provider: string;
  role: AiRole;
  model: string | null;
  base_url: string | null;
  timeout_seconds: number | null;
  is_active: boolean;
  /** A prefix of the key — enough to recognise it, useless for anything else. */
  key_hint: string | null;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_detail: string | null;
  created_at: string | null;
}

export interface AiProviderList {
  items: AiProviderConfig[];
  active: Record<AiRole, AiProviderConfig | null>;
  /** False until both roles have an active provider; AI search cannot run before then. */
  ready: boolean;
  /** False when the table has not been migrated yet — a setup step, not an error. */
  installed?: boolean;
  setup_hint?: string;
  /** The exact command, with this installation's host already filled in. */
  setup_command?: string;
}

export interface AiSettingsOptions {
  roles: AiRole[];
  /** A vendor that cannot fill a role must not be offerable for it. */
  providers_by_role: Record<AiRole, string[]>;
  default_models: Record<string, string | null>;
  labels: Record<string, string>;
}

/* ------------------------------------------------------ admin database viewer */

export interface DatabaseTableSummary {
  name: string;
  /** PostgreSQL's own estimate. Counting 36 tables exactly costs 36 round trips. */
  estimated_rows: number;
  columns: number;
  has_redacted_columns: boolean;
}

export interface DatabaseTableList {
  tables: DatabaseTableSummary[];
  row_counts_are_estimates: boolean;
  scope: string;
}

export interface DatabaseColumn {
  name: string;
  data_type: string;
  nullable: boolean;
  /** Value is never read out of the database; the column is listed, not shown. */
  redacted: boolean;
}

export interface DatabaseTablePage {
  table: string;
  columns: DatabaseColumn[];
  /** Every value arrives already stringified — this view is for reading, not parsing. */
  items: Record<string, string | null>[];
  total: number;
  limit: number;
  offset: number;
  /** The primary key paging is ordered by, or null when the table has no single one. */
  ordered_by: string | null;
  redacted_columns: string[];
}

/* -------------------------------------------------------------- AI discovery */

export interface DiscoveryStage {
  key: string;
  /** "parallel" or "gemma"; null for platform-side work. */
  provider: string | null;
  label: string;
  status: "pending" | "running" | "done" | "failed" | "skipped";
  detail: string | null;
  done: number;
  total: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface DiscoveryJob {
  provider: string | null;
  prompt_name: string | null;
  status: string;
  model: string | null;
  latency_ms: number | null;
  error: string | null;
}

export interface CandidateField {
  field_name: string;
  label: string;
  value: unknown;
  confidence: number | null;
  evidence: string | null;
}

export interface DiscoveryCandidate {
  id: string;
  /** Model code, or the supplier name. */
  title: string | null;
  /** Manufacturer, or the country. */
  subtitle: string | null;
  vendor_name: string | null;
  model_code: string | null;
  pump_name: string | null;
  website: string | null;
  hq_country: string | null;
  hq_city: string | null;
  vendor_tier: string | null;
  pump_type: string | null;
  applicable_standard: string | null;
  product_families: string[];
  overall_confidence: number | null;
  relevance_reason: string | null;
  oil_gas_evidence: string | null;
  field_count: number;
  fields: CandidateField[];
  unresolved: string[];
  source_url: string | null;
  source_title: string | null;
  decision: "pending" | "accepted" | "accepted_with_edits" | "rejected";
  /** Why storing would fail; null when the candidate can be stored. */
  blocked_reason: string | null;
  /**
   * The designation this will actually be stored under, when it differs from the one on
   * the page — an API 610 type code is a configuration, not a name, so "OH1 B Series"
   * becomes "B Series".
   */
  stored_as?: string | null;
  stored_id: string | null;
  matches_existing_id: string | null;
  matches_existing_label: string | null;
}

export interface CountryOption {
  code: string;
  name: string;
  /** True for countries that manufacture or service Oil & Gas pumps. */
  pump_supply: boolean;
}

/** One axis a sweep can run along, and how big that sweep would be. */
export interface DiscoveryScope {
  scope: "country" | "pump_type";
  segment_count: number;
  examples: string[];
  is_default: boolean;
}

/** A vocabulary entry and the phrase actually sent to the search provider. */
export interface DiscoveryPhrase {
  value: string;
  phrase: string;
}

export interface DiscoveryScopes {
  kind: "vendor" | "pump";
  scopes: DiscoveryScope[];
  max_sweep_pages: number;
  max_countries: number;
  pump_types: DiscoveryPhrase[];
  services: DiscoveryPhrase[];
}

export interface DiscoveryRun {
  id: string;
  kind: "vendor" | "pump";
  sweep: boolean;
  /** True when candidates were written without a human picking them. */
  auto_store?: boolean;
  /** Parallel AI searches this run makes: 1 for a query, one per pump type for a sweep. */
  segment_count: number;
  name: string;
  status: string;
  objective: string | null;
  queries: string[];
  query: string | null;
  country: string | null;
  transport: string | null;
  is_running: boolean;
  cancel_requested: boolean;
  stages: DiscoveryStage[];
  jobs: DiscoveryJob[];
  /** Total provider calls; `jobs` carries only the most recent, capped by the API. */
  job_count: number;
  candidates: DiscoveryCandidate[];
  pages_found: number;
  pages_screened: number;
  pages_failed: number;
  candidate_count: number;
  stored_count: number;
  error_summary: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface StoredRecord {
  id: string | null;
  label: string;
  candidate_id: string;
  fields_applied: string[];
  fields_refused: Record<string, string>;
}

export interface DiscoverySelectResponse {
  stored: StoredRecord[];
  rejected: string[];
  failed: Record<string, string>;
}
