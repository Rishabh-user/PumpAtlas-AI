-- =====================================================================
-- PumpAtlas AI - Oil & Gas Pump Intelligence Platform
-- Canonical PostgreSQL schema
--
-- GENERATED FILE - do not edit by hand.
-- Source of truth: backend/app/models/*.py
-- Regenerate with:  python scripts/gen_schema.py
--
-- Apply order:
--   1. db/extensions.sql   (pgcrypto, pg_trgm, btree_gin, unaccent)
--   2. db/schema.sql       (this file)
--   3. db/functions.sql    (search vector, versioning, provenance triggers)
--   4. db/rls.sql          (row level security policies)
--   5. db/partitions.sql   (optional: audit_logs monthly partitioning)
--
-- Then seed roles, the demo tenant and the bootstrap admin:
--   cd backend && python -m scripts.seed
-- =====================================================================

SET client_min_messages = warning;


-- ---------- enum types ----------

CREATE TYPE ai_job_status AS ENUM (
    'pending',
    'running',
    'succeeded',
    'failed',
    'cancelled',
    'awaiting_review'
);

CREATE TYPE ai_job_type AS ENUM (
    'extract_structured',
    'normalize_values',
    'summarize_vendor',
    'classify_record',
    'detect_missing_fields',
    'quality_check',
    'contradiction_check',
    'dedupe_candidate',
    'web_search',
    'similarity_match'
);

CREATE TYPE applicable_standard AS ENUM (
    'api_610',
    'api_674',
    'api_675',
    'api_676',
    'api_682',
    'api_685',
    'iso_13709',
    'iso_5199',
    'iso_2858',
    'asme_b73_1',
    'asme_b73_2',
    'nfpa_20',
    'hydraulic_institute',
    'en_733',
    'client_spec',
    'other'
);

CREATE TYPE area_classification AS ENUM (
    'zone_0',
    'zone_1',
    'zone_2',
    'class_i_div_1',
    'class_i_div_2',
    'safe_area',
    'other'
);

CREATE TYPE audit_action AS ENUM (
    'create',
    'update',
    'delete',
    'read_sensitive',
    'login',
    'login_failed',
    'logout',
    'export',
    'import',
    'ai_suggestion_applied',
    'ai_suggestion_rejected',
    'permission_change',
    'tenant_change',
    'merge'
);

CREATE TYPE confidence_level AS ENUM (
    'verified',
    'vendor_declared',
    'third_party',
    'ai_extracted',
    'estimated',
    'unknown'
);

CREATE TYPE data_quality_flag_type AS ENUM (
    'missing_required_field',
    'out_of_range',
    'unit_mismatch',
    'contradiction',
    'suspicious_value',
    'stale_data',
    'duplicate_suspect',
    'unnormalized_value',
    'source_unverified'
);

CREATE TYPE document_kind AS ENUM (
    'datasheet',
    'performance_curve',
    'ga_drawing',
    'quotation',
    'certificate',
    'test_report',
    'manual',
    'reference_list',
    'company_profile',
    'financial_statement',
    'spreadsheet',
    'other'
);

CREATE TYPE driver_type AS ENUM (
    'electric_motor',
    'vfd_electric_motor',
    'steam_turbine',
    'gas_turbine',
    'diesel_engine',
    'hydraulic',
    'air_motor',
    'other'
);

CREATE TYPE flag_severity AS ENUM (
    'info',
    'low',
    'medium',
    'high',
    'critical'
);

CREATE TYPE incoterm AS ENUM (
    'exw',
    'fca',
    'fas',
    'fob',
    'cfr',
    'cif',
    'cpt',
    'cip',
    'dap',
    'dpu',
    'ddp'
);

CREATE TYPE ingestion_status AS ENUM (
    'queued',
    'fetching',
    'parsing',
    'parsed',
    'extracting',
    'extracted',
    'needs_review',
    'promoted',
    'failed',
    'rejected'
);

CREATE TYPE pump_type AS ENUM (
    'centrifugal_oh1',
    'centrifugal_oh2',
    'centrifugal_oh3',
    'centrifugal_oh5',
    'centrifugal_oh6',
    'between_bearings_bb1',
    'between_bearings_bb2',
    'between_bearings_bb3',
    'between_bearings_bb4',
    'between_bearings_bb5',
    'vertically_suspended_vs1',
    'vertically_suspended_vs4',
    'vertically_suspended_vs6',
    'submersible',
    'reciprocating_plunger',
    'reciprocating_diaphragm',
    'rotary_screw',
    'rotary_gear',
    'rotary_progressive_cavity',
    'metering_dosing',
    'multiphase',
    'esp',
    'firewater',
    'other'
);

CREATE TYPE review_decision AS ENUM (
    'pending',
    'accepted',
    'accepted_with_edits',
    'rejected',
    'escalated'
);

CREATE TYPE sanctions_screening_status AS ENUM (
    'cleared',
    'flagged_review',
    'restricted',
    'sanctioned',
    'not_screened'
);

CREATE TYPE scorecard_kind AS ENUM (
    'technical_fit',
    'commercial_fit',
    'delivery_risk',
    'data_confidence',
    'overall'
);

CREATE TYPE seal_system_type AS ENUM (
    'api682_arrangement_1',
    'api682_arrangement_2',
    'api682_arrangement_3',
    'packed_gland',
    'magnetic_drive',
    'canned_motor',
    'seal_less_other',
    'other'
);

CREATE TYPE source_type AS ENUM (
    'web_page',
    'pdf',
    'document',
    'spreadsheet',
    'api',
    'manual_form',
    'email',
    'vendor_portal',
    'parallel_search'
);

CREATE TYPE tenant_plan AS ENUM (
    'trial',
    'standard',
    'professional',
    'enterprise'
);

CREATE TYPE tenant_status AS ENUM (
    'trial',
    'active',
    'suspended',
    'churned'
);

CREATE TYPE user_role_name AS ENUM (
    'admin',
    'research_analyst',
    'procurement',
    'engineering',
    'vendor_manager',
    'client_user'
);

CREATE TYPE value_origin AS ENUM (
    'manual',
    'ai_extraction',
    'ai_normalization',
    'ai_inference',
    'import',
    'api_sync',
    'calculated'
);

CREATE TYPE vendor_approval_status AS ENUM (
    'approved',
    'conditionally_approved',
    'pending_qualification',
    'under_review',
    'not_approved',
    'suspended',
    'blacklisted'
);

CREATE TYPE vendor_tier AS ENUM (
    'tier_1_oem',
    'tier_2_oem',
    'tier_3_oem',
    'packager',
    'authorized_distributor',
    'agent_representative',
    'aftermarket_service',
    'unclassified'
);

CREATE TYPE verification_status AS ENUM (
    'unverified',
    'in_review',
    'verified',
    'disputed',
    'superseded'
);


-- ---------- tables ----------

CREATE TABLE ai_provider_configs (
	label VARCHAR(120) NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	model VARCHAR(120), 
	encrypted_api_key TEXT NOT NULL, 
	key_hint VARCHAR(24), 
	base_url VARCHAR(255), 
	timeout_seconds INTEGER, 
	is_active BOOLEAN NOT NULL, 
	last_checked_at TIMESTAMP WITH TIME ZONE, 
	last_check_ok BOOLEAN, 
	last_check_detail TEXT, 
	created_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_ai_provider_configs PRIMARY KEY (id), 
	CONSTRAINT uq_ai_provider_configs_label_role UNIQUE (label, role)
);

CREATE TABLE roles (
	name user_role_name NOT NULL, 
	display_name VARCHAR(120) NOT NULL, 
	description VARCHAR(500), 
	is_platform_role BOOLEAN NOT NULL, 
	permissions JSONB NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_roles PRIMARY KEY (id), 
	CONSTRAINT uq_roles_name UNIQUE (name)
);

COMMENT ON COLUMN roles.is_platform_role IS 'Role operates across all tenants';

CREATE TABLE tenants (
	slug VARCHAR(63) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	legal_name VARCHAR(255), 
	country VARCHAR(2), 
	industry_segment VARCHAR(120), 
	status tenant_status NOT NULL, 
	plan tenant_plan NOT NULL, 
	contract_start DATE, 
	contract_end DATE, 
	can_use_shared_master BOOLEAN NOT NULL, 
	can_contribute_shared_master BOOLEAN NOT NULL, 
	max_users INTEGER NOT NULL, 
	max_ai_jobs_per_day INTEGER NOT NULL, 
	max_storage_mb INTEGER NOT NULL, 
	data_retention_days INTEGER, 
	settings JSONB NOT NULL, 
	primary_contact_email VARCHAR(320), 
	notes TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_tenants PRIMARY KEY (id)
);

COMMENT ON COLUMN tenants.country IS 'ISO 3166-1 alpha-2';
COMMENT ON COLUMN tenants.industry_segment IS 'e.g. upstream FPSO operator, EPC contractor';

CREATE TABLE users (
	tenant_id UUID, 
	email VARCHAR(320) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	job_title VARCHAR(160), 
	hashed_password VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_platform_admin BOOLEAN NOT NULL, 
	mfa_enabled BOOLEAN NOT NULL, 
	mfa_secret VARCHAR(64), 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	failed_login_count INTEGER NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	password_changed_at TIMESTAMP WITH TIME ZONE, 
	preferences JSONB NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_email UNIQUE (email), 
	CONSTRAINT fk_users_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN users.tenant_id IS 'NULL for Targeticon platform staff';
COMMENT ON COLUMN users.is_platform_admin IS 'Can administer every tenant';

CREATE TABLE api_keys (
	tenant_id UUID, 
	created_by_user_id UUID, 
	name VARCHAR(160) NOT NULL, 
	prefix VARCHAR(16) NOT NULL, 
	hashed_key VARCHAR(255) NOT NULL, 
	scopes JSONB NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_api_keys PRIMARY KEY (id), 
	CONSTRAINT fk_api_keys_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_api_keys_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE import_batches (
	name VARCHAR(255) NOT NULL, 
	import_mode VARCHAR(40) NOT NULL, 
	source_type source_type NOT NULL, 
	status ingestion_status NOT NULL, 
	total_items INTEGER NOT NULL, 
	processed_items INTEGER NOT NULL, 
	failed_items INTEGER NOT NULL, 
	promoted_items INTEGER NOT NULL, 
	needs_review_items INTEGER NOT NULL, 
	config JSONB NOT NULL, 
	auto_promote BOOLEAN NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	created_by_user_id UUID, 
	error_summary TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_import_batches PRIMARY KEY (id), 
	CONSTRAINT fk_import_batches_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_import_batches_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN import_batches.import_mode IS 'file_upload | url_list | scheduled_crawl | api_sync | web_search | manual_form';
COMMENT ON COLUMN import_batches.config IS 'Crawl scope, mapping profile, AI options';
COMMENT ON COLUMN import_batches.auto_promote IS 'Promote high-confidence extractions without human review';

CREATE TABLE requirement_profiles (
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	project_name VARCHAR(255), 
	tag_number VARCHAR(80), 
	required_capacity_m3h NUMERIC(18, 6), 
	required_head_m NUMERIC(18, 6), 
	max_npshr_m NUMERIC(18, 6), 
	min_efficiency_pct NUMERIC(18, 6), 
	fluid VARCHAR(160), 
	fluid_temperature_c NUMERIC(18, 6), 
	fluid_specific_gravity NUMERIC(18, 6), 
	required_standard VARCHAR(64), 
	required_pump_types JSONB NOT NULL, 
	required_area_classification VARCHAR(40), 
	required_certifications JSONB NOT NULL, 
	required_material_class VARCHAR(24), 
	nace_required BOOLEAN, 
	max_lead_time_weeks NUMERIC(18, 6), 
	max_budget_usd NUMERIC(18, 2), 
	max_dry_weight_kg NUMERIC(18, 6), 
	max_footprint_m2 NUMERIC(18, 6), 
	excluded_countries JSONB NOT NULL, 
	local_content_min_pct NUMERIC(18, 6), 
	weight_technical NUMERIC(18, 6) NOT NULL, 
	weight_commercial NUMERIC(18, 6) NOT NULL, 
	weight_delivery NUMERIC(18, 6) NOT NULL, 
	weight_data_confidence NUMERIC(18, 6) NOT NULL, 
	criteria_overrides JSONB NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_requirement_profiles PRIMARY KEY (id), 
	CONSTRAINT uq_requirement_profiles_tenant_id_name UNIQUE (tenant_id, name), 
	CONSTRAINT fk_requirement_profiles_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_requirement_profiles_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE TABLE saved_searches (
	name VARCHAR(255) NOT NULL, 
	query_text VARCHAR(1000), 
	filters JSONB NOT NULL, 
	sort_by VARCHAR(80), 
	is_shared_in_tenant BOOLEAN NOT NULL, 
	alert_enabled BOOLEAN NOT NULL, 
	alert_frequency VARCHAR(24), 
	last_alert_at TIMESTAMP WITH TIME ZONE, 
	last_result_count INTEGER, 
	created_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_saved_searches PRIMARY KEY (id), 
	CONSTRAINT uq_saved_searches_tenant_id_created_by_user_id_name UNIQUE (tenant_id, created_by_user_id, name), 
	CONSTRAINT fk_saved_searches_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_saved_searches_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN saved_searches.alert_frequency IS 'daily | weekly | on_change';

CREATE TABLE tags (
	slug VARCHAR(80) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description VARCHAR(500), 
	color VARCHAR(9), 
	category VARCHAR(60), 
	is_system BOOLEAN NOT NULL, 
	usage_count INTEGER NOT NULL, 
	created_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_tags PRIMARY KEY (id), 
	CONSTRAINT uq_tags_tenant_id_slug UNIQUE (tenant_id, slug), 
	CONSTRAINT fk_tags_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_tags_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN tags.color IS 'Hex, for dashboard chips';
COMMENT ON COLUMN tags.category IS 'watchlist | project | risk | commodity | custom';

CREATE TABLE tenant_permissions (
	tenant_id UUID NOT NULL, 
	resource VARCHAR(64) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	granted BOOLEAN NOT NULL, 
	shared_with_tenant_id UUID, 
	constraints JSONB NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	granted_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_tenant_permissions PRIMARY KEY (id), 
	CONSTRAINT uq_tenant_permissions_tenant_id_resource_action_shared__ceb1 UNIQUE (tenant_id, resource, action, shared_with_tenant_id), 
	CONSTRAINT fk_tenant_permissions_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_tenant_permissions_shared_with_tenant_id FOREIGN KEY(shared_with_tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_tenant_permissions_granted_by_user_id FOREIGN KEY(granted_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE user_roles (
	user_id UUID NOT NULL, 
	role_id UUID NOT NULL, 
	CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
	CONSTRAINT fk_user_roles_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_roles_role_id FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
);

CREATE TABLE audit_logs (
	id BIGSERIAL NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	action audit_action NOT NULL, 
	entity_type VARCHAR(60), 
	entity_id UUID, 
	entity_label VARCHAR(500), 
	user_id UUID, 
	user_email VARCHAR(320), 
	actor_type VARCHAR(24) NOT NULL, 
	api_key_id UUID, 
	summary TEXT, 
	changes JSONB NOT NULL, 
	context JSONB NOT NULL, 
	request_id VARCHAR(64), 
	ip_address INET, 
	user_agent VARCHAR(500), 
	http_method VARCHAR(10), 
	http_path VARCHAR(500), 
	status_code INTEGER, 
	tenant_id UUID, 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
	CONSTRAINT fk_audit_logs_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_audit_logs_api_key_id FOREIGN KEY(api_key_id) REFERENCES api_keys (id) ON DELETE SET NULL, 
	CONSTRAINT fk_audit_logs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN audit_logs.entity_label IS 'Human-readable subject, kept even if the row is later deleted';
COMMENT ON COLUMN audit_logs.actor_type IS 'user | system | worker | api_key';
COMMENT ON COLUMN audit_logs.changes IS '{"field": {"from": "...", "to": "..."}} - the diff that was applied';
COMMENT ON COLUMN audit_logs.context IS 'Route, job id, batch id, reason';

CREATE TABLE comparisons (
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	requirement_profile_id UUID, 
	comparison_kind VARCHAR(40) NOT NULL, 
	fields_shown JSONB NOT NULL, 
	snapshot JSONB NOT NULL, 
	recommendation TEXT, 
	ai_narrative TEXT, 
	status VARCHAR(24) NOT NULL, 
	is_shared_in_tenant BOOLEAN NOT NULL, 
	created_by_user_id UUID, 
	finalised_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_comparisons PRIMARY KEY (id), 
	CONSTRAINT fk_comparisons_requirement_profile_id FOREIGN KEY(requirement_profile_id) REFERENCES requirement_profiles (id) ON DELETE SET NULL, 
	CONSTRAINT fk_comparisons_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_comparisons_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN comparisons.comparison_kind IS 'pump_model | vendor';
COMMENT ON COLUMN comparisons.snapshot IS 'Frozen values as displayed, so a decision record stays reproducible';
COMMENT ON COLUMN comparisons.status IS 'draft | final | archived';

CREATE TABLE confidence_scores (
	entity_type VARCHAR(60) NOT NULL, 
	entity_id UUID NOT NULL, 
	scorecard_kind scorecard_kind NOT NULL, 
	score NUMERIC(6, 3) NOT NULL, 
	grade VARCHAR(4), 
	breakdown JSONB NOT NULL, 
	weighting_profile JSONB NOT NULL, 
	requirement_profile_id UUID, 
	fields_evaluated INTEGER, 
	fields_missing INTEGER, 
	computed_by_version VARCHAR(24), 
	computed_at TIMESTAMP WITH TIME ZONE, 
	is_stale BOOLEAN NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_confidence_scores PRIMARY KEY (id), 
	CONSTRAINT uq_confidence_scores_tenant_id_entity_type_entity_id_sc_fc9c UNIQUE (tenant_id, entity_type, entity_id, scorecard_kind, requirement_profile_id), 
	CONSTRAINT fk_confidence_scores_requirement_profile_id FOREIGN KEY(requirement_profile_id) REFERENCES requirement_profiles (id) ON DELETE CASCADE, 
	CONSTRAINT fk_confidence_scores_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN confidence_scores.score IS '0.000 - 100.000';
COMMENT ON COLUMN confidence_scores.grade IS 'A / B / C / D / E';
COMMENT ON COLUMN confidence_scores.breakdown IS 'Per-criterion contributions: {"npsh_margin": {"score": 80, "weight": 0.1}}';
COMMENT ON COLUMN confidence_scores.requirement_profile_id IS 'NULL means scored against platform defaults';

CREATE TABLE sources (
	source_type source_type NOT NULL, 
	status ingestion_status NOT NULL, 
	title VARCHAR(500), 
	source_url VARCHAR(2000), 
	canonical_url VARCHAR(2000), 
	publisher VARCHAR(255), 
	author VARCHAR(255), 
	language VARCHAR(8), 
	published_at TIMESTAMP WITH TIME ZONE, 
	captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	http_status INTEGER, 
	content_type VARCHAR(160), 
	content_hash VARCHAR(64), 
	raw_content TEXT, 
	parsed_text TEXT, 
	parsed_text_chars INTEGER, 
	source_metadata JSONB NOT NULL, 
	confidence_level confidence_level NOT NULL, 
	reliability_score NUMERIC(5, 4), 
	is_authoritative BOOLEAN NOT NULL, 
	parallel_search_id VARCHAR(120), 
	parallel_result_rank INTEGER, 
	import_batch_id UUID, 
	submitted_by_user_id UUID, 
	vendor_hint VARCHAR(255), 
	error_message TEXT, 
	retry_count INTEGER NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	tenant_id UUID, 
	CONSTRAINT pk_sources PRIMARY KEY (id), 
	CONSTRAINT fk_sources_import_batch_id FOREIGN KEY(import_batch_id) REFERENCES import_batches (id) ON DELETE SET NULL, 
	CONSTRAINT fk_sources_submitted_by_user_id FOREIGN KEY(submitted_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_sources_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN sources.captured_at IS 'When PumpAtlas fetched the source';
COMMENT ON COLUMN sources.content_hash IS 'SHA-256 of raw bytes; drives re-crawl dedupe';
COMMENT ON COLUMN sources.raw_content IS 'Raw HTML / JSON payload as captured; large binaries live in documents';
COMMENT ON COLUMN sources.parsed_text IS 'Plain text used for extraction';
COMMENT ON COLUMN sources.source_metadata IS 'Headers, robots directives, crawl context';
COMMENT ON COLUMN sources.reliability_score IS '0-1 trust in the publisher; OEM site > distributor > forum';
COMMENT ON COLUMN sources.is_authoritative IS 'True for OEM/official documents';
COMMENT ON COLUMN sources.parallel_search_id IS 'Parallel AI run that surfaced this result';
COMMENT ON COLUMN sources.vendor_hint IS 'Vendor the submitter believes this source is about';

CREATE TABLE tagged_records (
	tag_id UUID NOT NULL, 
	entity_type VARCHAR(60) NOT NULL, 
	entity_id UUID NOT NULL, 
	tenant_id UUID, 
	tagged_by_user_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_tagged_records PRIMARY KEY (tag_id, entity_type, entity_id), 
	CONSTRAINT fk_tagged_records_tag_id FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE, 
	CONSTRAINT fk_tagged_records_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_tagged_records_tagged_by_user_id FOREIGN KEY(tagged_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE vendors (
	name VARCHAR(255) NOT NULL, 
	normalized_name VARCHAR(255) NOT NULL, 
	aliases VARCHAR(255)[], 
	website VARCHAR(500), 
	hq_country VARCHAR(2), 
	country VARCHAR(2), 
	hq_city VARCHAR(120), 
	address_line VARCHAR(500), 
	state_region VARCHAR(120), 
	legal_entity_name VARCHAR(255), 
	client_since DATE, 
	is_purchasing_blocked BOOLEAN NOT NULL, 
	purchasing_block_note TEXT, 
	logo_url VARCHAR(500), 
	description TEXT, 
	ai_summary TEXT, 
	ai_summary_generated_at TIMESTAMP WITH TIME ZONE, 
	vendor_tier vendor_tier NOT NULL, 
	vendor_category VARCHAR(120), 
	product_families VARCHAR(120)[], 
	manufacturing_countries VARCHAR(2)[], 
	approval_status vendor_approval_status NOT NULL, 
	approval_expiry DATE, 
	approved_by_user_id UUID, 
	sanctions_status sanctions_screening_status NOT NULL, 
	sanctions_screened_at TIMESTAMP WITH TIME ZONE, 
	sanctions_notes TEXT, 
	geopolitical_risk_notes TEXT, 
	annual_revenue_usd NUMERIC(18, 2), 
	revenue_year INTEGER, 
	employee_count INTEGER, 
	credit_rating_agency VARCHAR(80), 
	credit_rating VARCHAR(32), 
	dun_bradstreet_number VARCHAR(32), 
	financial_standing_notes TEXT, 
	bonding_capacity_usd NUMERIC(18, 2), 
	can_provide_performance_bond BOOLEAN, 
	can_provide_advance_payment_guarantee BOOLEAN, 
	insurance_coverage_usd NUMERIC(18, 2), 
	insurance_details JSONB NOT NULL, 
	on_time_delivery_pct NUMERIC(5, 4), 
	total_units_supplied INTEGER, 
	fpso_offshore_experience BOOLEAN, 
	data_completeness_pct NUMERIC(5, 4), 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	primary_source_id UUID, 
	last_verified_at TIMESTAMP WITH TIME ZONE, 
	created_by_user_id UUID, 
	is_shared_master BOOLEAN NOT NULL, 
	merged_into_vendor_id UUID, 
	extra JSONB NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	tenant_id UUID, 
	CONSTRAINT pk_vendors PRIMARY KEY (id), 
	CONSTRAINT uq_vendors_tenant_id_normalized_name_country UNIQUE (tenant_id, normalized_name, country), 
	CONSTRAINT fk_vendors_approved_by_user_id FOREIGN KEY(approved_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_vendors_primary_source_id FOREIGN KEY(primary_source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_vendors_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_vendors_merged_into_vendor_id FOREIGN KEY(merged_into_vendor_id) REFERENCES vendors (id) ON DELETE SET NULL, 
	CONSTRAINT fk_vendors_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN vendors.normalized_name IS 'Lowercased, legal-suffix-stripped; dedupe key';
COMMENT ON COLUMN vendors.country IS 'Operating country for this record';
COMMENT ON COLUMN vendors.address_line IS 'Street address as the source states it';
COMMENT ON COLUMN vendors.state_region IS 'State, province or county';
COMMENT ON COLUMN vendors.legal_entity_name IS 'Registered name where it differs from the trading name';
COMMENT ON COLUMN vendors.client_since IS 'When this client first opened an account with the supplier';
COMMENT ON COLUMN vendors.is_purchasing_blocked IS 'The client has barred purchasing from this supplier';
COMMENT ON COLUMN vendors.ai_summary IS 'Gemma-generated vendor briefing; regenerated on material change';
COMMENT ON COLUMN vendors.vendor_category IS 'Client-specific category label';
COMMENT ON COLUMN vendors.merged_into_vendor_id IS 'Set when this record was merged away as a duplicate';

CREATE TABLE crawl_schedules (
	name VARCHAR(255) NOT NULL, 
	target_type VARCHAR(40) NOT NULL, 
	target VARCHAR(2000) NOT NULL, 
	vendor_id UUID, 
	cron_expression VARCHAR(120) NOT NULL, 
	max_depth INTEGER NOT NULL, 
	max_pages INTEGER NOT NULL, 
	include_patterns JSONB NOT NULL, 
	exclude_patterns JSONB NOT NULL, 
	auto_extract BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	last_run_status VARCHAR(40), 
	next_run_at TIMESTAMP WITH TIME ZONE, 
	created_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_crawl_schedules PRIMARY KEY (id), 
	CONSTRAINT fk_crawl_schedules_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE SET NULL, 
	CONSTRAINT fk_crawl_schedules_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_crawl_schedules_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN crawl_schedules.target_type IS 'url | sitemap | vendor_site | parallel_query';

CREATE TABLE pumps (
	vendor_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	normalized_name VARCHAR(255) NOT NULL, 
	product_family VARCHAR(160), 
	pump_type pump_type NOT NULL, 
	pump_type_raw VARCHAR(255), 
	applicable_standard applicable_standard NOT NULL, 
	additional_standards VARCHAR(64)[], 
	standard_edition VARCHAR(64), 
	service_application VARCHAR(255), 
	handled_fluids VARCHAR(120)[], 
	description TEXT, 
	ai_summary TEXT, 
	is_discontinued BOOLEAN NOT NULL, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	primary_source_id UUID, 
	created_by_user_id UUID, 
	is_shared_master BOOLEAN NOT NULL, 
	merged_into_pump_id UUID, 
	extra JSONB NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	tenant_id UUID, 
	CONSTRAINT pk_pumps PRIMARY KEY (id), 
	CONSTRAINT uq_pumps_tenant_id_vendor_id_normalized_name UNIQUE (tenant_id, vendor_id, normalized_name), 
	CONSTRAINT fk_pumps_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_pumps_primary_source_id FOREIGN KEY(primary_source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_pumps_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_pumps_merged_into_pump_id FOREIGN KEY(merged_into_pump_id) REFERENCES pumps (id) ON DELETE SET NULL, 
	CONSTRAINT fk_pumps_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN pumps.pump_type_raw IS 'Original uncontrolled string as captured from the source';
COMMENT ON COLUMN pumps.standard_edition IS 'e.g. API 610 12th Edition / ISO 13709:2009';
COMMENT ON COLUMN pumps.service_application IS 'e.g. crude export, produced water injection, firewater';

CREATE TABLE vendor_approvals (
	tenant_id UUID, 
	vendor_id UUID NOT NULL, 
	project VARCHAR(160) NOT NULL, 
	package VARCHAR(300) NOT NULL, 
	approved_country VARCHAR(160), 
	status VARCHAR(32) NOT NULL, 
	document_reference VARCHAR(300), 
	source_id UUID, 
	approved_on DATE, 
	expires_on DATE, 
	notes TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_vendor_approvals PRIMARY KEY (id), 
	CONSTRAINT uq_vendor_approval UNIQUE (vendor_id, project, package), 
	CONSTRAINT fk_vendor_approvals_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_vendor_approvals_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_vendor_approvals_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

COMMENT ON COLUMN vendor_approvals.approved_country IS 'Countries as the document writes them - ''UK / Brazil / India'' - kept verbatim';
COMMENT ON COLUMN vendor_approvals.document_reference IS 'The document number, so an answer can cite it';

CREATE TABLE vendor_contacts (
	vendor_id UUID NOT NULL, 
	tenant_id UUID, 
	contact_role VARCHAR(80) NOT NULL, 
	full_name VARCHAR(255), 
	company_name VARCHAR(255), 
	email VARCHAR(320), 
	source_id UUID, 
	captured_at TIMESTAMP WITH TIME ZONE, 
	origin VARCHAR(24), 
	phone VARCHAR(64), 
	country VARCHAR(2), 
	territory VARCHAR(255), 
	agency_agreement_valid_until DATE, 
	is_primary BOOLEAN NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_vendor_contacts PRIMARY KEY (id), 
	CONSTRAINT fk_vendor_contacts_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_vendor_contacts_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_vendor_contacts_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

COMMENT ON COLUMN vendor_contacts.contact_role IS 'commercial | technical | agent | service | authorized_representative';
COMMENT ON COLUMN vendor_contacts.company_name IS 'Set when the contact is an agent/representative entity';
COMMENT ON COLUMN vendor_contacts.source_id IS 'The captured page this detail was read from; null when entered by hand';
COMMENT ON COLUMN vendor_contacts.origin IS 'manual | ai_extraction, mirroring field_provenance';

CREATE TABLE vendor_identifiers (
	tenant_id UUID, 
	vendor_id UUID NOT NULL, 
	scheme VARCHAR(40) NOT NULL, 
	value VARCHAR(120) NOT NULL, 
	issued_country VARCHAR(2), 
	source_id UUID, 
	captured_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_vendor_identifiers PRIMARY KEY (id), 
	CONSTRAINT uq_vendor_identifier UNIQUE (vendor_id, scheme, value), 
	CONSTRAINT fk_vendor_identifiers_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	CONSTRAINT fk_vendor_identifiers_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_vendor_identifiers_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

CREATE TABLE pump_models (
	pump_id UUID NOT NULL, 
	model_code VARCHAR(160) NOT NULL, 
	size_designation VARCHAR(120), 
	frame_size VARCHAR(80), 
	stages INTEGER, 
	orientation VARCHAR(32), 
	generation VARCHAR(64), 
	tag_number VARCHAR(80), 
	project_reference VARCHAR(255), 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	data_completeness_pct FLOAT, 
	primary_source_id UUID, 
	created_by_user_id UUID, 
	last_reviewed_at TIMESTAMP WITH TIME ZONE, 
	is_shared_master BOOLEAN NOT NULL, 
	merged_into_pump_model_id UUID, 
	extra JSONB NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	tenant_id UUID, 
	CONSTRAINT pk_pump_models PRIMARY KEY (id), 
	CONSTRAINT uq_pump_models_tenant_id_pump_id_model_code UNIQUE (tenant_id, pump_id, model_code), 
	CONSTRAINT fk_pump_models_pump_id FOREIGN KEY(pump_id) REFERENCES pumps (id) ON DELETE CASCADE, 
	CONSTRAINT fk_pump_models_primary_source_id FOREIGN KEY(primary_source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_pump_models_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_pump_models_merged_into_pump_model_id FOREIGN KEY(merged_into_pump_model_id) REFERENCES pump_models (id) ON DELETE SET NULL, 
	CONSTRAINT fk_pump_models_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN pump_models.size_designation IS 'Suction x discharge x nominal impeller, e.g. 4x6x11';
COMMENT ON COLUMN pump_models.orientation IS 'horizontal | vertical | inline';
COMMENT ON COLUMN pump_models.tag_number IS 'Client tag when the record came from a project datasheet';
COMMENT ON COLUMN pump_models.data_completeness_pct IS 'Share of required intelligence fields populated; recomputed by worker';

CREATE TABLE comparison_items (
	comparison_id UUID NOT NULL, 
	pump_model_id UUID, 
	vendor_id UUID, 
	position INTEGER NOT NULL, 
	technical_score NUMERIC(6, 3), 
	commercial_score NUMERIC(6, 3), 
	delivery_risk_score NUMERIC(6, 3), 
	data_confidence_score NUMERIC(6, 3), 
	overall_score NUMERIC(6, 3), 
	rank INTEGER, 
	score_breakdown JSONB NOT NULL, 
	disqualified BOOLEAN NOT NULL, 
	disqualification_reason VARCHAR(500), 
	reviewer_notes TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_comparison_items PRIMARY KEY (id), 
	CONSTRAINT uq_comparison_items_comparison_id_pump_model_id_vendor_id UNIQUE (comparison_id, pump_model_id, vendor_id), 
	CONSTRAINT fk_comparison_items_comparison_id FOREIGN KEY(comparison_id) REFERENCES comparisons (id) ON DELETE CASCADE, 
	CONSTRAINT fk_comparison_items_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_comparison_items_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_comparison_items_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE TABLE documents (
	source_id UUID, 
	vendor_id UUID, 
	pump_id UUID, 
	pump_model_id UUID, 
	document_kind document_kind NOT NULL, 
	filename VARCHAR(500) NOT NULL, 
	storage_key VARCHAR(1000) NOT NULL, 
	storage_bucket VARCHAR(160), 
	mime_type VARCHAR(160), 
	size_bytes BIGINT, 
	checksum_sha256 VARCHAR(64), 
	page_count INTEGER, 
	extracted_text TEXT, 
	ocr_applied BOOLEAN NOT NULL, 
	is_confidential BOOLEAN NOT NULL, 
	document_date TIMESTAMP WITH TIME ZONE, 
	revision VARCHAR(40), 
	uploaded_by_user_id UUID, 
	doc_metadata JSONB NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	tenant_id UUID, 
	CONSTRAINT pk_documents PRIMARY KEY (id), 
	CONSTRAINT uq_documents_tenant_id_storage_key UNIQUE (tenant_id, storage_key), 
	CONSTRAINT fk_documents_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE, 
	CONSTRAINT fk_documents_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE SET NULL, 
	CONSTRAINT fk_documents_pump_id FOREIGN KEY(pump_id) REFERENCES pumps (id) ON DELETE SET NULL, 
	CONSTRAINT fk_documents_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE SET NULL, 
	CONSTRAINT fk_documents_uploaded_by_user_id FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_documents_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN documents.storage_key IS 'S3 object key (or local path in dev)';

CREATE TABLE search_index (
	pump_model_id UUID NOT NULL, 
	pump_id UUID NOT NULL, 
	vendor_id UUID NOT NULL, 
	label VARCHAR(500) NOT NULL, 
	vendor_name VARCHAR(255) NOT NULL, 
	pump_name VARCHAR(255) NOT NULL, 
	model_code VARCHAR(160) NOT NULL, 
	summary TEXT, 
	search_vector TSVECTOR, 
	searchable_text TEXT, 
	vendor_country VARCHAR(2), 
	manufacturing_countries VARCHAR(2)[], 
	country_of_origin VARCHAR(2), 
	pump_type pump_type, 
	applicable_standard applicable_standard, 
	service_application VARCHAR(255), 
	area_classification VARCHAR(40), 
	seal_system_type VARCHAR(60), 
	driver_type VARCHAR(60), 
	material_class VARCHAR(24), 
	certifications VARCHAR(120)[], 
	incoterms_offered VARCHAR(8)[], 
	vendor_approval_status vendor_approval_status, 
	vendor_tier VARCHAR(40), 
	fpso_experience BOOLEAN, 
	nace_compliant BOOLEAN, 
	rated_capacity_m3h NUMERIC(18, 6), 
	rated_head_m NUMERIC(18, 6), 
	npsh_required_m NUMERIC(18, 6), 
	hydraulic_efficiency_pct NUMERIC(18, 6), 
	rated_speed_rpm INTEGER, 
	rated_power_kw NUMERIC(18, 6), 
	fluid_temperature_max_c NUMERIC(18, 6), 
	casing_design_pressure_barg NUMERIC(18, 6), 
	base_price_usd NUMERIC(18, 2), 
	standard_lead_time_weeks NUMERIC(18, 6), 
	expedited_lead_time_weeks NUMERIC(18, 6), 
	dry_weight_kg NUMERIC(18, 6), 
	operating_weight_kg NUMERIC(18, 6), 
	footprint_area_m2 NUMERIC(18, 6), 
	on_time_delivery_pct NUMERIC(5, 4), 
	units_installed INTEGER, 
	mtbf_hours INTEGER, 
	confidence_level confidence_level, 
	verification_status verification_status, 
	data_completeness_pct NUMERIC(5, 4), 
	data_confidence_score NUMERIC(6, 3), 
	open_flag_count INTEGER NOT NULL, 
	is_shared_master BOOLEAN NOT NULL, 
	last_source_captured_at TIMESTAMP WITH TIME ZONE, 
	indexed_at TIMESTAMP WITH TIME ZONE, 
	index_version VARCHAR(24), 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_search_index PRIMARY KEY (id), 
	CONSTRAINT uq_search_index_pump_model_id UNIQUE (pump_model_id), 
	CONSTRAINT fk_search_index_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_search_index_pump_id FOREIGN KEY(pump_id) REFERENCES pumps (id) ON DELETE CASCADE, 
	CONSTRAINT fk_search_index_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_search_index_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN search_index.label IS 'Vendor + pump + model, as shown in result rows';
COMMENT ON COLUMN search_index.searchable_text IS 'Concatenated haystack the tsvector is generated from';

CREATE TABLE ai_jobs (
	job_type ai_job_type NOT NULL, 
	status ai_job_status NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	model VARCHAR(160), 
	prompt_name VARCHAR(120), 
	prompt_version VARCHAR(24), 
	source_id UUID, 
	document_id UUID, 
	import_batch_id UUID, 
	subject_type VARCHAR(60), 
	subject_id UUID, 
	request_payload JSONB NOT NULL, 
	response_payload JSONB NOT NULL, 
	raw_response_text TEXT, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	cost_usd NUMERIC(12, 6), 
	latency_ms INTEGER, 
	attempt INTEGER NOT NULL, 
	celery_task_id VARCHAR(120), 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	error_message TEXT, 
	triggered_by_user_id UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_ai_jobs PRIMARY KEY (id), 
	CONSTRAINT fk_ai_jobs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_jobs_document_id FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_jobs_import_batch_id FOREIGN KEY(import_batch_id) REFERENCES import_batches (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_jobs_triggered_by_user_id FOREIGN KEY(triggered_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_jobs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN ai_jobs.provider IS 'openrouter | parallel';
COMMENT ON COLUMN ai_jobs.prompt_name IS 'Named template used, e.g. extract_technical_v3';
COMMENT ON COLUMN ai_jobs.subject_type IS 'vendor | pump | pump_model | technical_spec | ...';
COMMENT ON COLUMN ai_jobs.raw_response_text IS 'Verbatim model output, kept for audit and re-parsing';

CREATE TABLE administrative_specs (
	vendor_id UUID, 
	legal_entity_name VARCHAR(255), 
	legal_form VARCHAR(80), 
	registration_number VARCHAR(80), 
	registration_country VARCHAR(2), 
	registration_authority VARCHAR(200), 
	tax_identification_number VARCHAR(80), 
	vat_number VARCHAR(80), 
	lei_code VARCHAR(20), 
	registered_address TEXT, 
	incorporation_date DATE, 
	ultimate_parent_company VARCHAR(255), 
	ownership_structure JSONB NOT NULL, 
	beneficial_ownership_disclosed BOOLEAN, 
	authorized_representative_name VARCHAR(255), 
	authorized_representative_title VARCHAR(160), 
	authorized_representative_email VARCHAR(320), 
	authorized_representative_phone VARCHAR(64), 
	local_agent_name VARCHAR(255), 
	local_agent_country VARCHAR(2), 
	agency_agreement_reference VARCHAR(160), 
	agency_agreement_expiry DATE, 
	power_of_attorney_on_file BOOLEAN, 
	esg_report_published BOOLEAN, 
	esg_report_url VARCHAR(500), 
	esg_rating_provider VARCHAR(120), 
	esg_rating VARCHAR(40), 
	scope1_emissions_tco2e NUMERIC(18, 6), 
	scope2_emissions_tco2e NUMERIC(18, 6), 
	scope3_emissions_reported BOOLEAN, 
	net_zero_target_year INTEGER, 
	iso_14001_certified BOOLEAN, 
	iso_50001_certified BOOLEAN, 
	modern_slavery_statement BOOLEAN, 
	anti_bribery_policy BOOLEAN, 
	conflict_minerals_policy BOOLEAN, 
	diversity_disclosures TEXT, 
	iso_27001_certified BOOLEAN, 
	iec_62443_compliance VARCHAR(80), 
	soc2_report_available BOOLEAN, 
	penetration_test_frequency VARCHAR(80), 
	security_incident_history TEXT, 
	supply_chain_security_program TEXT, 
	remote_access_policy TEXT, 
	cyber_insurance BOOLEAN, 
	cybersecurity_questionnaire_completed BOOLEAN, 
	submitted_by_name VARCHAR(255), 
	submitted_by_organisation VARCHAR(255), 
	submission_channel VARCHAR(80), 
	source_reference VARCHAR(500), 
	data_owner VARCHAR(160), 
	next_review_due DATE, 
	completeness_pct NUMERIC(5, 4), 
	verification_method VARCHAR(200), 
	verified_by_user_id UUID, 
	verified_at TIMESTAMP WITH TIME ZONE, 
	retention_policy VARCHAR(160), 
	confidentiality_class VARCHAR(40), 
	pump_model_id UUID NOT NULL, 
	source_id UUID, 
	ai_job_id UUID, 
	created_by_user_id UUID, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	source_units JSONB NOT NULL, 
	notes TEXT, 
	extra JSONB NOT NULL, 
	data_submission_date DATE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	superseded_at TIMESTAMP WITH TIME ZONE, 
	schema_version VARCHAR DEFAULT '1.0.0' NOT NULL, 
	CONSTRAINT pk_administrative_specs PRIMARY KEY (id), 
	CONSTRAINT uq_administrative_specs_pump_model_id_version UNIQUE (pump_model_id, version), 
	CONSTRAINT fk_administrative_specs_vendor_id FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE, 
	CONSTRAINT fk_administrative_specs_verified_by_user_id FOREIGN KEY(verified_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_administrative_specs_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_administrative_specs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_administrative_specs_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_administrative_specs_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_administrative_specs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN administrative_specs.legal_form IS 'GmbH | S.p.A. | Ltd | LLC | JSC ...';
COMMENT ON COLUMN administrative_specs.lei_code IS 'ISO 17442 legal entity id';
COMMENT ON COLUMN administrative_specs.iec_62443_compliance IS 'Security level claimed for OT/control scope';
COMMENT ON COLUMN administrative_specs.submission_channel IS 'portal | email | web crawl | api | interview';
COMMENT ON COLUMN administrative_specs.verification_method IS 'How the record was verified: document, call, site audit';
COMMENT ON COLUMN administrative_specs.confidentiality_class IS 'public | internal | confidential | restricted';
COMMENT ON COLUMN administrative_specs.source_units IS 'Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}';
COMMENT ON COLUMN administrative_specs.extra IS 'Fields not yet promoted to columns';
COMMENT ON COLUMN administrative_specs.data_submission_date IS 'Date the supplier or analyst submitted this data';

CREATE TABLE commercial_specs (
	base_price_amount NUMERIC(18, 2), 
	base_price_currency VARCHAR(3), 
	base_price_usd NUMERIC(18, 2), 
	fx_rate_used NUMERIC(18, 6), 
	fx_rate_date DATE, 
	price_basis VARCHAR(200), 
	price_validity_days INTEGER, 
	quotation_reference VARCHAR(160), 
	quotation_date DATE, 
	incoterm incoterm, 
	incoterm_named_place VARCHAR(160), 
	payment_terms TEXT, 
	advance_payment_pct NUMERIC(18, 6), 
	payment_days_net INTEGER, 
	letter_of_credit_required BOOLEAN, 
	retention_pct NUMERIC(18, 6), 
	liquidated_damages_terms TEXT, 
	liquidated_damages_cap_pct NUMERIC(18, 6), 
	warranty_months INTEGER, 
	warranty_basis VARCHAR(120), 
	warranty_scope TEXT, 
	extended_warranty_available BOOLEAN, 
	extended_warranty_cost_pct NUMERIC(18, 6), 
	spares_price_amount NUMERIC(18, 2), 
	spares_price_currency VARCHAR(3), 
	commissioning_spares_usd NUMERIC(18, 2), 
	two_year_spares_usd NUMERIC(18, 2), 
	capital_spares_usd NUMERIC(18, 2), 
	spares_price_list JSONB NOT NULL, 
	spares_discount_pct NUMERIC(18, 6), 
	price_escalation_formula TEXT, 
	escalation_index_reference VARCHAR(160), 
	escalation_base_date DATE, 
	escalation_annual_pct NUMERIC(18, 6), 
	discount_pct NUMERIC(18, 6), 
	volume_discount_schedule JSONB NOT NULL, 
	frame_agreement_reference VARCHAR(160), 
	historical_price_benchmark_usd NUMERIC(18, 2), 
	benchmark_source VARCHAR(200), 
	benchmark_date DATE, 
	benchmark_variance_pct NUMERIC(18, 6), 
	lifecycle_cost_usd NUMERIC(18, 2), 
	lifecycle_period_years INTEGER, 
	energy_cost_per_year_usd NUMERIC(18, 2), 
	maintenance_cost_per_year_usd NUMERIC(18, 2), 
	lifecycle_assumptions JSONB NOT NULL, 
	taxes_included BOOLEAN, 
	tax_details TEXT, 
	import_duty_pct NUMERIC(18, 6), 
	customs_hs_code VARCHAR(24), 
	local_content_pct NUMERIC(18, 6), 
	local_content_scheme VARCHAR(160), 
	local_content_certificate VARCHAR(160), 
	withholding_tax_pct NUMERIC(18, 6), 
	financial_standing_summary TEXT, 
	bonding_capability TEXT, 
	insurance_capability TEXT, 
	parent_company_guarantee_available BOOLEAN, 
	pump_model_id UUID NOT NULL, 
	source_id UUID, 
	ai_job_id UUID, 
	created_by_user_id UUID, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	source_units JSONB NOT NULL, 
	notes TEXT, 
	extra JSONB NOT NULL, 
	data_submission_date DATE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	superseded_at TIMESTAMP WITH TIME ZONE, 
	schema_version VARCHAR DEFAULT '1.0.0' NOT NULL, 
	CONSTRAINT pk_commercial_specs PRIMARY KEY (id), 
	CONSTRAINT uq_commercial_specs_pump_model_id_version UNIQUE (pump_model_id, version), 
	CONSTRAINT fk_commercial_specs_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_commercial_specs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_commercial_specs_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_commercial_specs_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_commercial_specs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN commercial_specs.base_price_currency IS 'ISO 4217';
COMMENT ON COLUMN commercial_specs.base_price_usd IS 'Converted at fx_rate_used for cross-vendor comparison';
COMMENT ON COLUMN commercial_specs.price_basis IS 'Scope covered by the price: bare shaft, package, skid';
COMMENT ON COLUMN commercial_specs.payment_terms IS 'e.g. 20% advance / 70% on delivery / 10% on FAC';
COMMENT ON COLUMN commercial_specs.warranty_basis IS 'from delivery | from commissioning | whichever is earlier';
COMMENT ON COLUMN commercial_specs.spares_price_list IS 'Itemised spare part price list';
COMMENT ON COLUMN commercial_specs.price_escalation_formula IS 'Contractual escalation clause as written';
COMMENT ON COLUMN commercial_specs.escalation_index_reference IS 'e.g. CEPCI, Eurostat MIG, BLS PPI 3561';
COMMENT ON COLUMN commercial_specs.volume_discount_schedule IS 'e.g. {"5": 4.5, "10": 8.0} units to pct';
COMMENT ON COLUMN commercial_specs.benchmark_variance_pct IS 'Offer vs benchmark; negative means cheaper than benchmark';
COMMENT ON COLUMN commercial_specs.local_content_scheme IS 'e.g. NOGICD Nigeria, ICV Saudi Arabia, Petrobras local content';
COMMENT ON COLUMN commercial_specs.source_units IS 'Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}';
COMMENT ON COLUMN commercial_specs.extra IS 'Fields not yet promoted to columns';
COMMENT ON COLUMN commercial_specs.data_submission_date IS 'Date the supplier or analyst submitted this data';

CREATE TABLE data_quality_flags (
	entity_type VARCHAR(60) NOT NULL, 
	entity_id UUID NOT NULL, 
	field_name VARCHAR(120), 
	flag_type data_quality_flag_type NOT NULL, 
	severity flag_severity NOT NULL, 
	message TEXT NOT NULL, 
	detected_value VARCHAR(500), 
	expected_range VARCHAR(255), 
	conflicting_entity_type VARCHAR(60), 
	conflicting_entity_id UUID, 
	conflicting_value VARCHAR(500), 
	detected_by VARCHAR(40) NOT NULL, 
	ai_job_id UUID, 
	suggested_fix TEXT, 
	is_resolved BOOLEAN NOT NULL, 
	resolution VARCHAR(40), 
	resolved_by_user_id UUID, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	resolution_notes TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_data_quality_flags PRIMARY KEY (id), 
	CONSTRAINT fk_data_quality_flags_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_data_quality_flags_resolved_by_user_id FOREIGN KEY(resolved_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_data_quality_flags_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN data_quality_flags.detected_by IS 'validator | ai | user';
COMMENT ON COLUMN data_quality_flags.resolution IS 'corrected | accepted_as_is | false_positive | deferred';

CREATE TABLE delivery_specs (
	standard_lead_time_weeks NUMERIC(18, 6), 
	lead_time_basis VARCHAR(160), 
	expedited_lead_time_weeks NUMERIC(18, 6), 
	expedite_premium_pct NUMERIC(18, 6), 
	expedite_premium_usd NUMERIC(18, 2), 
	expedite_conditions TEXT, 
	engineering_lead_time_weeks NUMERIC(18, 6), 
	manufacturing_lead_time_weeks NUMERIC(18, 6), 
	manufacturing_locations VARCHAR(160)[], 
	primary_manufacturing_country VARCHAR(2), 
	assembly_location VARCHAR(160), 
	testing_location VARCHAR(160), 
	workshop_capacity_notes TEXT, 
	current_backlog_weeks NUMERIC(18, 6), 
	logistics_lead_time_weeks NUMERIC(18, 6), 
	shipping_mode VARCHAR(80), 
	port_of_loading VARCHAR(160), 
	incoterms_offered VARCHAR(8)[], 
	preferred_incoterm incoterm, 
	freight_cost_estimate_usd NUMERIC(18, 2), 
	oversize_cargo BOOLEAN, 
	logistics_notes TEXT, 
	documentation_lead_time_weeks NUMERIC(18, 6), 
	final_documentation_weeks_after_delivery NUMERIC(18, 6), 
	document_deliverables_list JSONB NOT NULL, 
	documentation_language VARCHAR(80), 
	as_built_documentation_included BOOLEAN, 
	fat_lead_time_weeks NUMERIC(18, 6), 
	fat_duration_days NUMERIC(18, 6), 
	fat_notice_period_weeks NUMERIC(18, 6), 
	fat_location VARCHAR(160), 
	fat_witness_slots INTEGER, 
	sat_supported BOOLEAN, 
	fat_scheduling_notes TEXT, 
	historical_on_time_delivery_pct NUMERIC(5, 4), 
	otd_sample_size INTEGER, 
	otd_measurement_period VARCHAR(120), 
	average_delay_weeks NUMERIC(18, 6), 
	delivery_risk_notes TEXT, 
	long_lead_components JSONB NOT NULL, 
	critical_subsupplier_dependencies VARCHAR(200)[], 
	single_source_components VARCHAR(200)[], 
	forging_casting_lead_time_weeks NUMERIC(18, 6), 
	country_of_origin VARCHAR(2), 
	export_control_classification VARCHAR(80), 
	export_licence_required BOOLEAN, 
	export_licence_lead_time_weeks NUMERIC(18, 6), 
	restricted_destinations VARCHAR(2)[], 
	us_content_pct NUMERIC(18, 6), 
	export_control_notes TEXT, 
	pump_model_id UUID NOT NULL, 
	source_id UUID, 
	ai_job_id UUID, 
	created_by_user_id UUID, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	source_units JSONB NOT NULL, 
	notes TEXT, 
	extra JSONB NOT NULL, 
	data_submission_date DATE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	superseded_at TIMESTAMP WITH TIME ZONE, 
	schema_version VARCHAR DEFAULT '1.0.0' NOT NULL, 
	CONSTRAINT pk_delivery_specs PRIMARY KEY (id), 
	CONSTRAINT uq_delivery_specs_pump_model_id_version UNIQUE (pump_model_id, version), 
	CONSTRAINT fk_delivery_specs_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_delivery_specs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_delivery_specs_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_delivery_specs_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_delivery_specs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN delivery_specs.lead_time_basis IS 'from PO | from approved drawings | from LOI';
COMMENT ON COLUMN delivery_specs.manufacturing_locations IS 'City, country per plant';
COMMENT ON COLUMN delivery_specs.shipping_mode IS 'sea | air | road | multimodal';
COMMENT ON COLUMN delivery_specs.fat_lead_time_weeks IS 'Weeks from PO to FAT readiness';
COMMENT ON COLUMN delivery_specs.otd_sample_size IS 'Number of orders behind the OTD figure';
COMMENT ON COLUMN delivery_specs.long_lead_components IS 'e.g. {"castings": {"weeks": 22, "source": "EU foundry"}}';
COMMENT ON COLUMN delivery_specs.export_control_classification IS 'e.g. EAR99, ECCN 2B999, EU dual-use item';
COMMENT ON COLUMN delivery_specs.source_units IS 'Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}';
COMMENT ON COLUMN delivery_specs.extra IS 'Fields not yet promoted to columns';
COMMENT ON COLUMN delivery_specs.data_submission_date IS 'Date the supplier or analyst submitted this data';

CREATE TABLE dimensional_specs (
	dry_weight_kg NUMERIC(18, 6), 
	operating_weight_kg NUMERIC(18, 6), 
	shipping_weight_kg NUMERIC(18, 6), 
	pump_only_weight_kg NUMERIC(18, 6), 
	driver_weight_kg NUMERIC(18, 6), 
	baseplate_weight_kg NUMERIC(18, 6), 
	max_maintenance_lift_weight_kg NUMERIC(18, 6), 
	max_maintenance_lift_item VARCHAR(160), 
	crate_length_mm NUMERIC(18, 6), 
	crate_width_mm NUMERIC(18, 6), 
	crate_height_mm NUMERIC(18, 6), 
	crate_volume_m3 NUMERIC(18, 6), 
	number_of_packages INTEGER, 
	packaging_type VARCHAR(160), 
	packaging_standard VARCHAR(120), 
	preservation_period_months INTEGER, 
	baseplate_length_mm NUMERIC(18, 6), 
	baseplate_width_mm NUMERIC(18, 6), 
	baseplate_height_mm NUMERIC(18, 6), 
	baseplate_type VARCHAR(120), 
	footprint_area_m2 NUMERIC(18, 6), 
	overall_length_mm NUMERIC(18, 6), 
	overall_width_mm NUMERIC(18, 6), 
	overall_height_mm NUMERIC(18, 6), 
	maintenance_access_envelope_mm JSONB NOT NULL, 
	cog_x_mm NUMERIC(18, 6), 
	cog_y_mm NUMERIC(18, 6), 
	cog_z_mm NUMERIC(18, 6), 
	cog_reference_datum VARCHAR(160), 
	lifting_points_count INTEGER, 
	lifting_point_details JSONB NOT NULL, 
	lifting_arrangement_standard VARCHAR(120), 
	certified_lifting_set_included BOOLEAN, 
	static_load_kn NUMERIC(18, 6), 
	dynamic_load_kn NUMERIC(18, 6), 
	torque_reaction_knm NUMERIC(18, 6), 
	anchor_bolt_count INTEGER, 
	anchor_bolt_size VARCHAR(40), 
	foundation_loading_notes TEXT, 
	grouting_requirement VARCHAR(160), 
	vibration_isolation_required BOOLEAN, 
	fpso_module_space_envelope TEXT, 
	fpso_module_envelope_length_mm NUMERIC(18, 6), 
	fpso_module_envelope_width_mm NUMERIC(18, 6), 
	fpso_module_envelope_height_mm NUMERIC(18, 6), 
	deck_area_required_m2 NUMERIC(18, 6), 
	module_integration_notes TEXT, 
	motion_design_criteria VARCHAR(200), 
	pump_model_id UUID NOT NULL, 
	source_id UUID, 
	ai_job_id UUID, 
	created_by_user_id UUID, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	source_units JSONB NOT NULL, 
	notes TEXT, 
	extra JSONB NOT NULL, 
	data_submission_date DATE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	superseded_at TIMESTAMP WITH TIME ZONE, 
	schema_version VARCHAR DEFAULT '1.0.0' NOT NULL, 
	CONSTRAINT pk_dimensional_specs PRIMARY KEY (id), 
	CONSTRAINT uq_dimensional_specs_pump_model_id_version UNIQUE (pump_model_id, version), 
	CONSTRAINT fk_dimensional_specs_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_dimensional_specs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_dimensional_specs_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_dimensional_specs_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_dimensional_specs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN dimensional_specs.max_maintenance_lift_weight_kg IS 'Heaviest single item to be lifted during maintenance';
COMMENT ON COLUMN dimensional_specs.packaging_type IS 'seaworthy wooden case | vacuum barrier | container | skid';
COMMENT ON COLUMN dimensional_specs.packaging_standard IS 'e.g. ISPM 15, MIL-STD-2073';
COMMENT ON COLUMN dimensional_specs.baseplate_type IS 'API 610 baseplate | skid | fabricated | grouted';
COMMENT ON COLUMN dimensional_specs.maintenance_access_envelope_mm IS 'Clearances needed per side for pull-out';
COMMENT ON COLUMN dimensional_specs.lifting_arrangement_standard IS 'e.g. DNV 2.7-3, EN 13155';
COMMENT ON COLUMN dimensional_specs.fpso_module_space_envelope IS 'Declared L x W x H envelope inside the topside module';
COMMENT ON COLUMN dimensional_specs.motion_design_criteria IS 'Vessel motions / accelerations the unit is designed for';
COMMENT ON COLUMN dimensional_specs.source_units IS 'Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}';
COMMENT ON COLUMN dimensional_specs.extra IS 'Fields not yet promoted to columns';
COMMENT ON COLUMN dimensional_specs.data_submission_date IS 'Date the supplier or analyst submitted this data';

CREATE TABLE duplicate_candidates (
	entity_type VARCHAR(60) NOT NULL, 
	entity_id_a UUID NOT NULL, 
	entity_id_b UUID NOT NULL, 
	similarity_score NUMERIC(5, 4) NOT NULL, 
	match_signals JSONB NOT NULL, 
	detection_method VARCHAR(40) NOT NULL, 
	ai_job_id UUID, 
	status VARCHAR(40) NOT NULL, 
	merged_into_id UUID, 
	reviewed_by_user_id UUID, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	notes TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_duplicate_candidates PRIMARY KEY (id), 
	CONSTRAINT uq_duplicate_candidates_tenant_id_entity_type_entity_id_d077 UNIQUE (tenant_id, entity_type, entity_id_a, entity_id_b), 
	CONSTRAINT fk_duplicate_candidates_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_duplicate_candidates_reviewed_by_user_id FOREIGN KEY(reviewed_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_duplicate_candidates_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN duplicate_candidates.match_signals IS '{"normalized_name": 1.0, "duty_point": 0.97, "trigram": 0.88}';
COMMENT ON COLUMN duplicate_candidates.detection_method IS 'deterministic | ai | manual';
COMMENT ON COLUMN duplicate_candidates.status IS 'open | merged | distinct | deferred';

CREATE TABLE extracted_entities (
	source_id UUID, 
	ai_job_id UUID, 
	entity_type VARCHAR(60) NOT NULL, 
	payload JSONB NOT NULL, 
	raw_payload JSONB NOT NULL, 
	field_confidences JSONB NOT NULL, 
	evidence_spans JSONB NOT NULL, 
	overall_confidence NUMERIC(5, 4), 
	confidence_level confidence_level NOT NULL, 
	review_decision review_decision NOT NULL, 
	reviewed_by_user_id UUID, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	review_notes TEXT, 
	reviewer_edits JSONB NOT NULL, 
	target_type VARCHAR(60), 
	target_id UUID, 
	promoted_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_extracted_entities PRIMARY KEY (id), 
	CONSTRAINT fk_extracted_entities_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE, 
	CONSTRAINT fk_extracted_entities_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_extracted_entities_reviewed_by_user_id FOREIGN KEY(reviewed_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_extracted_entities_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN extracted_entities.entity_type IS 'vendor | pump | pump_model | technical_spec | commercial_spec | ...';
COMMENT ON COLUMN extracted_entities.payload IS 'Normalised candidate record';
COMMENT ON COLUMN extracted_entities.raw_payload IS 'Pre-normalisation model output';
COMMENT ON COLUMN extracted_entities.field_confidences IS '{"rated_head_m": 0.82, ...}';
COMMENT ON COLUMN extracted_entities.evidence_spans IS '{"rated_head_m": {"quote": "...", "char_start": 1420}} - traceability';
COMMENT ON COLUMN extracted_entities.reviewer_edits IS 'Field-level corrections a human made';
COMMENT ON COLUMN extracted_entities.target_type IS 'Set on promotion: which table received the data';

CREATE TABLE operational_specs (
	reference_list JSONB NOT NULL, 
	reference_count INTEGER, 
	units_supplied INTEGER, 
	units_installed_operating INTEGER, 
	first_installation_year INTEGER, 
	cumulative_operating_hours INTEGER, 
	reference_contactable BOOLEAN, 
	mtbf_hours INTEGER, 
	mttr_hours NUMERIC(18, 6), 
	availability_pct NUMERIC(5, 4), 
	failure_rate_per_year NUMERIC(18, 6), 
	common_failure_modes TEXT, 
	reliability_data_source VARCHAR(200), 
	seal_mtbf_hours INTEGER, 
	overhaul_interval_hours INTEGER, 
	fpso_experience BOOLEAN, 
	fpso_units_supplied INTEGER, 
	fpso_project_references JSONB NOT NULL, 
	offshore_experience_years INTEGER, 
	harsh_environment_experience VARCHAR(200), 
	subsea_experience BOOLEAN, 
	service_network_countries VARCHAR(2)[], 
	service_centers JSONB NOT NULL, 
	nearest_service_center VARCHAR(200), 
	response_time_hours NUMERIC(18, 6), 
	field_service_engineers_count INTEGER, 
	service_agreement_options TEXT, 
	remote_monitoring_offered BOOLEAN, 
	post_warranty_spares_years INTEGER, 
	spares_availability_commitment TEXT, 
	spares_stock_locations VARCHAR(160)[], 
	typical_spares_delivery_weeks NUMERIC(18, 6), 
	obsolescence_management_policy TEXT, 
	training_offered BOOLEAN, 
	training_scope TEXT, 
	training_days_included NUMERIC(18, 6), 
	commissioning_support_included BOOLEAN, 
	commissioning_support_days NUMERIC(18, 6), 
	supervision_day_rate_usd NUMERIC(18, 2), 
	documentation_training_language VARCHAR(80), 
	hse_trir NUMERIC(18, 6), 
	hse_ltifr NUMERIC(18, 6), 
	hse_fatalities_last_5y INTEGER, 
	hse_incident_history TEXT, 
	hse_management_system VARCHAR(120), 
	hse_audit_date DATE, 
	qaqc_certifications VARCHAR(120)[], 
	quality_certificate_expiry DATE, 
	itp_available BOOLEAN, 
	audit_history JSONB NOT NULL, 
	ncr_history_notes TEXT, 
	vendor_approval_notes TEXT, 
	approved_vendor_list_membership VARCHAR(160)[], 
	pump_model_id UUID NOT NULL, 
	source_id UUID, 
	ai_job_id UUID, 
	created_by_user_id UUID, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	source_units JSONB NOT NULL, 
	notes TEXT, 
	extra JSONB NOT NULL, 
	data_submission_date DATE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	superseded_at TIMESTAMP WITH TIME ZONE, 
	schema_version VARCHAR DEFAULT '1.0.0' NOT NULL, 
	CONSTRAINT pk_operational_specs PRIMARY KEY (id), 
	CONSTRAINT uq_operational_specs_pump_model_id_version UNIQUE (pump_model_id, version), 
	CONSTRAINT fk_operational_specs_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_operational_specs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_operational_specs_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_operational_specs_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_operational_specs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN operational_specs.reference_list IS '[{"client":"...","project":"...","year":2021,"units":4,"country":"BR"}]';
COMMENT ON COLUMN operational_specs.reliability_data_source IS 'e.g. OREDA, client CMMS, vendor claim';
COMMENT ON COLUMN operational_specs.harsh_environment_experience IS 'North Sea, Arctic, deepwater Brazil, West Africa ...';
COMMENT ON COLUMN operational_specs.hse_trir IS 'Total recordable incident rate';
COMMENT ON COLUMN operational_specs.hse_ltifr IS 'Lost time injury frequency rate';
COMMENT ON COLUMN operational_specs.hse_management_system IS 'e.g. ISO 45001 certified';
COMMENT ON COLUMN operational_specs.qaqc_certifications IS 'ISO 9001, ISO 14001, API Q1, ASME U stamp ...';
COMMENT ON COLUMN operational_specs.itp_available IS 'Inspection and test plan can be supplied';
COMMENT ON COLUMN operational_specs.approved_vendor_list_membership IS 'Operator AVLs the vendor sits on';
COMMENT ON COLUMN operational_specs.source_units IS 'Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}';
COMMENT ON COLUMN operational_specs.extra IS 'Fields not yet promoted to columns';
COMMENT ON COLUMN operational_specs.data_submission_date IS 'Date the supplier or analyst submitted this data';

CREATE TABLE record_versions (
	entity_type VARCHAR(60) NOT NULL, 
	entity_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	operation VARCHAR(16) NOT NULL, 
	snapshot JSONB NOT NULL, 
	diff JSONB NOT NULL, 
	changed_by_user_id UUID, 
	change_reason VARCHAR(500), 
	ai_job_id UUID, 
	schema_version VARCHAR(24), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_record_versions PRIMARY KEY (id), 
	CONSTRAINT fk_record_versions_changed_by_user_id FOREIGN KEY(changed_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_record_versions_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_record_versions_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN record_versions.operation IS 'insert | update | delete | merge';

CREATE TABLE technical_specs (
	standard_compliance_notes TEXT, 
	api_610_type_code VARCHAR(16), 
	deviations_to_standard TEXT, 
	rated_capacity_m3h NUMERIC(18, 6), 
	min_capacity_m3h NUMERIC(18, 6), 
	max_capacity_m3h NUMERIC(18, 6), 
	min_continuous_stable_flow_m3h NUMERIC(18, 6), 
	bep_capacity_m3h NUMERIC(18, 6), 
	rated_head_m NUMERIC(18, 6), 
	max_head_m NUMERIC(18, 6), 
	shutoff_head_m NUMERIC(18, 6), 
	differential_pressure_barg NUMERIC(18, 6), 
	npsh_required_m NUMERIC(18, 6), 
	npsh_available_m NUMERIC(18, 6), 
	npsh_margin_m NUMERIC(18, 6), 
	hydraulic_efficiency_pct NUMERIC(18, 6), 
	bep_efficiency_pct NUMERIC(18, 6), 
	rated_power_kw NUMERIC(18, 6), 
	max_power_kw NUMERIC(18, 6), 
	specific_speed NUMERIC(18, 6), 
	suction_specific_speed NUMERIC(18, 6), 
	impeller_type VARCHAR(80), 
	impeller_diameter_mm NUMERIC(18, 6), 
	number_of_vanes INTEGER, 
	suction_size_mm NUMERIC(18, 6), 
	discharge_size_mm NUMERIC(18, 6), 
	flange_rating VARCHAR(40), 
	flange_facing VARCHAR(40), 
	rated_speed_rpm INTEGER, 
	min_speed_rpm INTEGER, 
	max_speed_rpm INTEGER, 
	is_variable_speed BOOLEAN, 
	driver_type driver_type, 
	driver_type_raw VARCHAR(160), 
	driver_rated_power_kw NUMERIC(18, 6), 
	driver_manufacturer VARCHAR(160), 
	driver_model VARCHAR(160), 
	driver_voltage_v INTEGER, 
	driver_frequency_hz INTEGER, 
	driver_service_factor NUMERIC(18, 6), 
	driver_enclosure VARCHAR(40), 
	coupling_type VARCHAR(120), 
	gearbox_required BOOLEAN, 
	material_class VARCHAR(24), 
	casing_material VARCHAR(160), 
	impeller_material VARCHAR(160), 
	shaft_material VARCHAR(160), 
	wear_parts_material VARCHAR(160), 
	shaft_sleeve_material VARCHAR(160), 
	gasket_material VARCHAR(160), 
	fastener_material VARCHAR(160), 
	nace_mr0175_compliant BOOLEAN, 
	corrosion_allowance_mm NUMERIC(18, 6), 
	material_certification VARCHAR(120), 
	seal_system_type seal_system_type, 
	seal_system_type_raw VARCHAR(160), 
	seal_api_682_category VARCHAR(24), 
	seal_arrangement VARCHAR(80), 
	seal_piping_plan VARCHAR(80), 
	seal_manufacturer VARCHAR(160), 
	seal_model VARCHAR(160), 
	seal_face_materials VARCHAR(200), 
	seal_elastomer VARCHAR(120), 
	barrier_buffer_fluid VARCHAR(160), 
	seal_support_system_scope TEXT, 
	radial_bearing_type VARCHAR(120), 
	thrust_bearing_type VARCHAR(120), 
	bearing_arrangement VARCHAR(120), 
	bearing_manufacturer VARCHAR(160), 
	bearing_life_hours INTEGER, 
	lubrication_type VARCHAR(80), 
	lubricant_grade VARCHAR(80), 
	lube_oil_system_scope TEXT, 
	bearing_isolators VARCHAR(120), 
	bearing_temperature_monitoring BOOLEAN, 
	area_classification area_classification, 
	area_classification_raw VARCHAR(160), 
	gas_group VARCHAR(24), 
	temperature_class VARCHAR(16), 
	equipment_protection_level VARCHAR(24), 
	ingress_protection VARCHAR(16), 
	atex_certified BOOLEAN, 
	iecex_certified BOOLEAN, 
	ex_certificate_numbers VARCHAR(80)[], 
	casing_type VARCHAR(80), 
	casing_design_pressure_barg NUMERIC(18, 6), 
	max_allowable_working_pressure_barg NUMERIC(18, 6), 
	casing_design_temperature_min_c NUMERIC(18, 6), 
	casing_design_temperature_max_c NUMERIC(18, 6), 
	hydrostatic_test_pressure_barg NUMERIC(18, 6), 
	pressure_class VARCHAR(40), 
	casing_design_code VARCHAR(120), 
	nozzle_load_capability VARCHAR(160), 
	performance_test_required BOOLEAN, 
	performance_test_grade VARCHAR(40), 
	npsh_test_required BOOLEAN, 
	mechanical_run_test_required BOOLEAN, 
	mechanical_run_duration_hours NUMERIC(18, 6), 
	hydrostatic_test_required BOOLEAN, 
	string_test_required BOOLEAN, 
	complete_unit_test_required BOOLEAN, 
	nde_requirements TEXT, 
	witness_level VARCHAR(40), 
	test_standard VARCHAR(120), 
	noise_limit_dba NUMERIC(18, 6), 
	vibration_limit_mm_s NUMERIC(18, 6), 
	external_coating_spec VARCHAR(200), 
	internal_coating_spec VARCHAR(200), 
	paint_system_standard VARCHAR(120), 
	coating_dft_microns NUMERIC(18, 6), 
	surface_preparation VARCHAR(120), 
	corrosion_category VARCHAR(24), 
	galvanic_protection VARCHAR(160), 
	instrumentation_scope TEXT, 
	vibration_monitoring VARCHAR(160), 
	api_670_compliant BOOLEAN, 
	temperature_monitoring VARCHAR(160), 
	pressure_instrumentation VARCHAR(160), 
	control_interface_protocol VARCHAR(120), 
	local_control_panel BOOLEAN, 
	junction_box_certification VARCHAR(120), 
	condition_monitoring_ready BOOLEAN, 
	signal_list JSONB NOT NULL, 
	marine_class_society VARCHAR(80), 
	marine_certification_type VARCHAR(120), 
	third_party_certifications VARCHAR(120)[], 
	certificate_numbers VARCHAR(120)[], 
	certification_valid_until DATE, 
	inspection_authority VARCHAR(120), 
	spares_interchangeable_with VARCHAR(160)[], 
	parts_commonality_pct NUMERIC(18, 6), 
	common_rotating_element BOOLEAN, 
	interchangeability_notes TEXT, 
	obsolescence_risk VARCHAR(24), 
	fluid_handled VARCHAR(160), 
	fluid_specific_gravity NUMERIC(18, 6), 
	fluid_viscosity_cst NUMERIC(18, 6), 
	fluid_temperature_min_c NUMERIC(18, 6), 
	fluid_temperature_max_c NUMERIC(18, 6), 
	solids_content_pct NUMERIC(18, 6), 
	h2s_service BOOLEAN, 
	suction_pressure_barg NUMERIC(18, 6), 
	discharge_pressure_barg NUMERIC(18, 6), 
	pump_model_id UUID NOT NULL, 
	source_id UUID, 
	ai_job_id UUID, 
	created_by_user_id UUID, 
	confidence_level confidence_level NOT NULL, 
	verification_status verification_status NOT NULL, 
	source_units JSONB NOT NULL, 
	notes TEXT, 
	extra JSONB NOT NULL, 
	data_submission_date DATE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	version INTEGER DEFAULT '1' NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	superseded_at TIMESTAMP WITH TIME ZONE, 
	schema_version VARCHAR DEFAULT '1.0.0' NOT NULL, 
	CONSTRAINT pk_technical_specs PRIMARY KEY (id), 
	CONSTRAINT uq_technical_specs_pump_model_id_version UNIQUE (pump_model_id, version), 
	CONSTRAINT fk_technical_specs_pump_model_id FOREIGN KEY(pump_model_id) REFERENCES pump_models (id) ON DELETE CASCADE, 
	CONSTRAINT fk_technical_specs_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_technical_specs_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_technical_specs_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_technical_specs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN technical_specs.api_610_type_code IS 'OH2 / BB3 / VS4 ... as declared on the datasheet';
COMMENT ON COLUMN technical_specs.impeller_type IS 'closed | semi-open | open | vortex | double-suction';
COMMENT ON COLUMN technical_specs.flange_rating IS 'e.g. ASME 300# RF, API 6A 5000 psi';
COMMENT ON COLUMN technical_specs.driver_enclosure IS 'e.g. TEFC, WPII, Ex d IIB T4';
COMMENT ON COLUMN technical_specs.material_class IS 'API 610 Table H.1 class, e.g. S-6, C-6, A-8, D-1';
COMMENT ON COLUMN technical_specs.nace_mr0175_compliant IS 'Sour service compliance (NACE MR0175 / ISO 15156)';
COMMENT ON COLUMN technical_specs.material_certification IS 'e.g. EN 10204 3.1 / 3.2';
COMMENT ON COLUMN technical_specs.seal_api_682_category IS 'Category 1 / 2 / 3';
COMMENT ON COLUMN technical_specs.seal_arrangement IS 'single | dual pressurised | dual unpressurised';
COMMENT ON COLUMN technical_specs.seal_piping_plan IS 'API 682 flush plan, e.g. Plan 11 + Plan 52';
COMMENT ON COLUMN technical_specs.lubrication_type IS 'ring oil | flood | pressurised | grease | oil mist';
COMMENT ON COLUMN technical_specs.gas_group IS 'IIA / IIB / IIC';
COMMENT ON COLUMN technical_specs.temperature_class IS 'T1 - T6';
COMMENT ON COLUMN technical_specs.ingress_protection IS 'e.g. IP66';
COMMENT ON COLUMN technical_specs.casing_type IS 'radially split | axially split | barrel | double casing';
COMMENT ON COLUMN technical_specs.pressure_class IS 'ASME/ANSI class or API rating of the casing';
COMMENT ON COLUMN technical_specs.casing_design_code IS 'e.g. ASME VIII Div.1, PED 2014/68/EU';
COMMENT ON COLUMN technical_specs.nozzle_load_capability IS 'e.g. 2x API 610 Table 5 allowable';
COMMENT ON COLUMN technical_specs.performance_test_grade IS 'e.g. API 610 Table 16 / HI 14.6 grade 1B';
COMMENT ON COLUMN technical_specs.nde_requirements IS 'Non-destructive examination scope: RT / UT / MPI / DPI extents';
COMMENT ON COLUMN technical_specs.witness_level IS 'witnessed | observed | monitored | unwitnessed';
COMMENT ON COLUMN technical_specs.external_coating_spec IS 'e.g. NORSOK M-501 System 1';
COMMENT ON COLUMN technical_specs.paint_system_standard IS 'NORSOK M-501 | ISO 12944 | client spec';
COMMENT ON COLUMN technical_specs.surface_preparation IS 'e.g. ISO 8501-1 Sa 2.5';
COMMENT ON COLUMN technical_specs.corrosion_category IS 'ISO 12944 category, e.g. CX offshore';
COMMENT ON COLUMN technical_specs.vibration_monitoring IS 'API 670 accelerometers / velocity probes / none';
COMMENT ON COLUMN technical_specs.control_interface_protocol IS 'Modbus TCP | PROFIBUS DP | HART | FF | Ethernet/IP';
COMMENT ON COLUMN technical_specs.marine_class_society IS 'DNV | ABS | LR | BV | ClassNK | RINA | none';
COMMENT ON COLUMN technical_specs.marine_certification_type IS 'Type approval | product certificate | unit certificate';
COMMENT ON COLUMN technical_specs.third_party_certifications IS 'Free list, e.g. CE/PED, ATEX, IECEx, UKCA';
COMMENT ON COLUMN technical_specs.spares_interchangeable_with IS 'Model codes sharing rotating elements / wear parts';
COMMENT ON COLUMN technical_specs.obsolescence_risk IS 'low | medium | high';
COMMENT ON COLUMN technical_specs.source_units IS 'Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}';
COMMENT ON COLUMN technical_specs.extra IS 'Fields not yet promoted to columns';
COMMENT ON COLUMN technical_specs.data_submission_date IS 'Date the supplier or analyst submitted this data';

CREATE TABLE ai_suggestions (
	entity_type VARCHAR(60) NOT NULL, 
	entity_id UUID NOT NULL, 
	field_name VARCHAR(120) NOT NULL, 
	suggestion_kind VARCHAR(40) NOT NULL, 
	current_value TEXT, 
	suggested_value TEXT, 
	suggested_value_json JSONB NOT NULL, 
	rationale TEXT, 
	evidence_quote TEXT, 
	confidence_score NUMERIC(5, 4), 
	confidence_level confidence_level NOT NULL, 
	ai_job_id UUID, 
	source_id UUID, 
	extracted_entity_id UUID, 
	decision review_decision NOT NULL, 
	decided_by_user_id UUID, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	applied_value TEXT, 
	decision_notes TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_ai_suggestions PRIMARY KEY (id), 
	CONSTRAINT fk_ai_suggestions_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_suggestions_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_suggestions_extracted_entity_id FOREIGN KEY(extracted_entity_id) REFERENCES extracted_entities (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_suggestions_decided_by_user_id FOREIGN KEY(decided_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_ai_suggestions_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN ai_suggestions.suggestion_kind IS 'fill_missing | normalize | correct | enrich | flag_removal';
COMMENT ON COLUMN ai_suggestions.applied_value IS 'What was actually written, if the reviewer edited the suggestion';

CREATE TABLE field_provenance (
	entity_type VARCHAR(60) NOT NULL, 
	entity_id UUID NOT NULL, 
	field_name VARCHAR(120) NOT NULL, 
	value_text TEXT, 
	previous_value_text TEXT, 
	value_origin value_origin NOT NULL, 
	confidence_level confidence_level NOT NULL, 
	confidence_score NUMERIC(5, 4), 
	source_id UUID, 
	document_id UUID, 
	ai_job_id UUID, 
	extracted_entity_id UUID, 
	model_used VARCHAR(160), 
	evidence_quote TEXT, 
	evidence_locator VARCHAR(255), 
	original_value VARCHAR(500), 
	original_unit VARCHAR(40), 
	normalization_note TEXT, 
	changed_by_user_id UUID, 
	is_current BOOLEAN NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id UUID, 
	CONSTRAINT pk_field_provenance PRIMARY KEY (id), 
	CONSTRAINT fk_field_provenance_source_id FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
	CONSTRAINT fk_field_provenance_document_id FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL, 
	CONSTRAINT fk_field_provenance_ai_job_id FOREIGN KEY(ai_job_id) REFERENCES ai_jobs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_field_provenance_extracted_entity_id FOREIGN KEY(extracted_entity_id) REFERENCES extracted_entities (id) ON DELETE SET NULL, 
	CONSTRAINT fk_field_provenance_changed_by_user_id FOREIGN KEY(changed_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_field_provenance_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN field_provenance.value_text IS 'Written value rendered as text, for diffing and audit';
COMMENT ON COLUMN field_provenance.evidence_quote IS 'Verbatim snippet from the source that supports the value';
COMMENT ON COLUMN field_provenance.evidence_locator IS 'Page number, cell reference, char offset or CSS selector';
COMMENT ON COLUMN field_provenance.original_value IS 'Value as printed in the source, before unit normalisation';


-- ---------- indexes ----------

CREATE UNIQUE INDEX uq_ai_provider_configs_one_active_per_role ON ai_provider_configs (role) WHERE is_active;
CREATE UNIQUE INDEX ix_tenants_slug ON tenants (slug);
CREATE INDEX ix_users_tenant_active ON users (tenant_id, is_active);
CREATE INDEX ix_users_tenant_id ON users (tenant_id);
CREATE INDEX ix_api_keys_prefix ON api_keys (prefix);
CREATE INDEX ix_api_keys_tenant_id ON api_keys (tenant_id);
CREATE INDEX ix_import_batches_tenant_id ON import_batches (tenant_id);
CREATE INDEX ix_import_batches_tenant_status ON import_batches (tenant_id, status);
CREATE INDEX ix_requirement_profiles_tenant ON requirement_profiles (tenant_id, is_active);
CREATE INDEX ix_requirement_profiles_tenant_id ON requirement_profiles (tenant_id);
CREATE INDEX ix_saved_searches_tenant_id ON saved_searches (tenant_id);
CREATE INDEX ix_tags_tenant_id ON tags (tenant_id);
CREATE INDEX ix_tenant_permissions_tenant_id ON tenant_permissions (tenant_id);
CREATE INDEX ix_audit_logs_action ON audit_logs (action, occurred_at);
CREATE INDEX ix_audit_logs_actor ON audit_logs (user_id, occurred_at);
CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX ix_audit_logs_occurred_at ON audit_logs (occurred_at);
CREATE INDEX ix_audit_logs_request_id ON audit_logs (request_id);
CREATE INDEX ix_audit_logs_tenant_id ON audit_logs (tenant_id);
CREATE INDEX ix_audit_logs_tenant_time ON audit_logs (tenant_id, occurred_at);
CREATE INDEX ix_comparisons_tenant_created ON comparisons (tenant_id, created_at);
CREATE INDEX ix_comparisons_tenant_id ON comparisons (tenant_id);
CREATE INDEX ix_confidence_scores_entity ON confidence_scores (entity_type, entity_id);
CREATE INDEX ix_confidence_scores_tenant_id ON confidence_scores (tenant_id);
CREATE INDEX ix_sources_content_hash ON sources (content_hash);
CREATE INDEX ix_sources_import_batch_id ON sources (import_batch_id);
CREATE INDEX ix_sources_tenant_id ON sources (tenant_id);
CREATE INDEX ix_sources_tenant_status ON sources (tenant_id, status);
CREATE INDEX ix_sources_type_captured ON sources (source_type, captured_at);
CREATE INDEX ix_sources_url ON sources (source_url);
CREATE INDEX ix_tagged_records_entity ON tagged_records (entity_type, entity_id);
CREATE INDEX ix_tagged_records_tenant_tag ON tagged_records (tenant_id, tag_id);
CREATE INDEX ix_vendors_country ON vendors (country);
CREATE INDEX ix_vendors_fpso_offshore_experience ON vendors (fpso_offshore_experience);
CREATE INDEX ix_vendors_hq_country ON vendors (hq_country);
CREATE INDEX ix_vendors_name ON vendors (name);
CREATE INDEX ix_vendors_tenant_id ON vendors (tenant_id);
CREATE INDEX ix_vendors_tenant_status ON vendors (tenant_id, approval_status);
CREATE INDEX ix_vendors_tier ON vendors (vendor_tier);
CREATE INDEX ix_crawl_schedules_next_run ON crawl_schedules (is_active, next_run_at);
CREATE INDEX ix_crawl_schedules_tenant_id ON crawl_schedules (tenant_id);
CREATE INDEX ix_pumps_applicable_standard ON pumps (applicable_standard);
CREATE INDEX ix_pumps_pump_type ON pumps (pump_type);
CREATE INDEX ix_pumps_tenant_id ON pumps (tenant_id);
CREATE INDEX ix_pumps_tenant_vendor ON pumps (tenant_id, vendor_id);
CREATE INDEX ix_pumps_type_standard ON pumps (pump_type, applicable_standard);
CREATE INDEX ix_pumps_vendor_id ON pumps (vendor_id);
CREATE INDEX ix_vendor_approvals_package ON vendor_approvals (package);
CREATE INDEX ix_vendor_approvals_project ON vendor_approvals (tenant_id, project);
CREATE INDEX ix_vendor_approvals_tenant_id ON vendor_approvals (tenant_id);
CREATE INDEX ix_vendor_approvals_vendor ON vendor_approvals (vendor_id);
CREATE INDEX ix_vendor_contacts_tenant_id ON vendor_contacts (tenant_id);
CREATE INDEX ix_vendor_contacts_vendor_role ON vendor_contacts (vendor_id, contact_role);
CREATE INDEX ix_vendor_identifiers_lookup ON vendor_identifiers (scheme, value);
CREATE INDEX ix_vendor_identifiers_tenant_id ON vendor_identifiers (tenant_id);
CREATE INDEX ix_vendor_identifiers_vendor ON vendor_identifiers (vendor_id);
CREATE INDEX ix_pump_models_code ON pump_models (model_code);
CREATE INDEX ix_pump_models_pump_id ON pump_models (pump_id);
CREATE INDEX ix_pump_models_tenant_id ON pump_models (tenant_id);
CREATE INDEX ix_pump_models_tenant_pump ON pump_models (tenant_id, pump_id);
CREATE INDEX ix_comparison_items_comparison ON comparison_items (comparison_id, position);
CREATE INDEX ix_comparison_items_tenant_id ON comparison_items (tenant_id);
CREATE INDEX ix_documents_checksum_sha256 ON documents (checksum_sha256);
CREATE INDEX ix_documents_pump_model ON documents (pump_model_id);
CREATE INDEX ix_documents_source_id ON documents (source_id);
CREATE INDEX ix_documents_tenant_id ON documents (tenant_id);
CREATE INDEX ix_documents_tenant_kind ON documents (tenant_id, document_kind);
CREATE INDEX ix_documents_vendor ON documents (vendor_id);
CREATE INDEX ix_search_index_certs ON search_index USING gin (certifications);
CREATE INDEX ix_search_index_country ON search_index (tenant_id, vendor_country);
CREATE INDEX ix_search_index_duty ON search_index (tenant_id, rated_capacity_m3h, rated_head_m);
CREATE INDEX ix_search_index_lead_time ON search_index (tenant_id, standard_lead_time_weeks);
CREATE INDEX ix_search_index_price ON search_index (tenant_id, base_price_usd);
CREATE INDEX ix_search_index_pump_id ON search_index (pump_id);
CREATE INDEX ix_search_index_tenant_id ON search_index (tenant_id);
CREATE INDEX ix_search_index_tenant_type ON search_index (tenant_id, pump_type);
CREATE INDEX ix_search_index_trgm_label ON search_index USING gin (label gin_trgm_ops);
CREATE INDEX ix_search_index_tsv ON search_index USING gin (search_vector);
CREATE INDEX ix_search_index_vendor_id ON search_index (vendor_id);
CREATE INDEX ix_ai_jobs_celery_task_id ON ai_jobs (celery_task_id);
CREATE INDEX ix_ai_jobs_source_id ON ai_jobs (source_id);
CREATE INDEX ix_ai_jobs_subject ON ai_jobs (subject_type, subject_id);
CREATE INDEX ix_ai_jobs_tenant_id ON ai_jobs (tenant_id);
CREATE INDEX ix_ai_jobs_tenant_status ON ai_jobs (tenant_id, status);
CREATE INDEX ix_ai_jobs_type_created ON ai_jobs (job_type, created_at);
CREATE INDEX ix_administrative_specs_current ON administrative_specs (pump_model_id, is_current);
CREATE INDEX ix_administrative_specs_pump_model_id ON administrative_specs (pump_model_id);
CREATE INDEX ix_administrative_specs_tenant_id ON administrative_specs (tenant_id);
CREATE INDEX ix_administrative_specs_vendor ON administrative_specs (vendor_id);
CREATE INDEX ix_commercial_specs_current ON commercial_specs (pump_model_id, is_current);
CREATE INDEX ix_commercial_specs_price ON commercial_specs (base_price_usd);
CREATE INDEX ix_commercial_specs_pump_model_id ON commercial_specs (pump_model_id);
CREATE INDEX ix_commercial_specs_tenant_id ON commercial_specs (tenant_id);
CREATE INDEX ix_data_quality_flags_tenant_id ON data_quality_flags (tenant_id);
CREATE INDEX ix_dq_flags_entity ON data_quality_flags (entity_type, entity_id);
CREATE INDEX ix_dq_flags_tenant_open ON data_quality_flags (tenant_id, is_resolved, severity);
CREATE INDEX ix_delivery_specs_country_of_origin ON delivery_specs (country_of_origin);
CREATE INDEX ix_delivery_specs_current ON delivery_specs (pump_model_id, is_current);
CREATE INDEX ix_delivery_specs_lead_time ON delivery_specs (standard_lead_time_weeks);
CREATE INDEX ix_delivery_specs_primary_manufacturing_country ON delivery_specs (primary_manufacturing_country);
CREATE INDEX ix_delivery_specs_pump_model_id ON delivery_specs (pump_model_id);
CREATE INDEX ix_delivery_specs_tenant_id ON delivery_specs (tenant_id);
CREATE INDEX ix_dimensional_specs_current ON dimensional_specs (pump_model_id, is_current);
CREATE INDEX ix_dimensional_specs_pump_model_id ON dimensional_specs (pump_model_id);
CREATE INDEX ix_dimensional_specs_tenant_id ON dimensional_specs (tenant_id);
CREATE INDEX ix_dimensional_specs_weight ON dimensional_specs (dry_weight_kg);
CREATE INDEX ix_duplicate_candidates_open ON duplicate_candidates (tenant_id, status, similarity_score);
CREATE INDEX ix_duplicate_candidates_tenant_id ON duplicate_candidates (tenant_id);
CREATE INDEX ix_extracted_entities_source ON extracted_entities (source_id);
CREATE INDEX ix_extracted_entities_target ON extracted_entities (target_type, target_id);
CREATE INDEX ix_extracted_entities_tenant_id ON extracted_entities (tenant_id);
CREATE INDEX ix_extracted_entities_tenant_review ON extracted_entities (tenant_id, review_decision);
CREATE INDEX ix_operational_specs_current ON operational_specs (pump_model_id, is_current);
CREATE INDEX ix_operational_specs_fpso ON operational_specs (fpso_experience);
CREATE INDEX ix_operational_specs_pump_model_id ON operational_specs (pump_model_id);
CREATE INDEX ix_operational_specs_tenant_id ON operational_specs (tenant_id);
CREATE INDEX ix_record_versions_entity ON record_versions (entity_type, entity_id, version);
CREATE INDEX ix_record_versions_tenant_id ON record_versions (tenant_id);
CREATE INDEX ix_record_versions_tenant_time ON record_versions (tenant_id, created_at);
CREATE INDEX ix_technical_specs_area ON technical_specs (area_classification);
CREATE INDEX ix_technical_specs_current ON technical_specs (pump_model_id, is_current);
CREATE INDEX ix_technical_specs_duty ON technical_specs (rated_capacity_m3h, rated_head_m);
CREATE INDEX ix_technical_specs_pump_model_id ON technical_specs (pump_model_id);
CREATE INDEX ix_technical_specs_tenant_id ON technical_specs (tenant_id);
CREATE INDEX ix_ai_suggestions_entity ON ai_suggestions (entity_type, entity_id);
CREATE INDEX ix_ai_suggestions_tenant_decision ON ai_suggestions (tenant_id, decision);
CREATE INDEX ix_ai_suggestions_tenant_id ON ai_suggestions (tenant_id);
CREATE INDEX ix_field_provenance_entity ON field_provenance (entity_type, entity_id);
CREATE INDEX ix_field_provenance_field ON field_provenance (entity_type, entity_id, field_name, is_current);
CREATE INDEX ix_field_provenance_origin ON field_provenance (tenant_id, value_origin);
CREATE INDEX ix_field_provenance_source ON field_provenance (source_id);
CREATE INDEX ix_field_provenance_tenant_id ON field_provenance (tenant_id);

