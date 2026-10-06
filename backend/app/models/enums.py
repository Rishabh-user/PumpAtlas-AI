"""Controlled vocabularies for PumpAtlas AI.

These are stored as native PostgreSQL enum types. They are intentionally narrow: the
platform serves Oil & Gas pump intelligence only, so the vocabulary is domain specific.
Free-text variants captured from the web are normalised into these values by the AI
layer, with the original string preserved in the matching ``*_raw`` column.
"""

from __future__ import annotations

from enum import StrEnum


class UserRoleName(StrEnum):
    ADMIN = "admin"
    RESEARCH_ANALYST = "research_analyst"
    PROCUREMENT = "procurement"
    ENGINEERING = "engineering"
    VENDOR_MANAGER = "vendor_manager"
    CLIENT_USER = "client_user"


class SourceType(StrEnum):
    WEB_PAGE = "web_page"
    PDF = "pdf"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    API = "api"
    MANUAL_FORM = "manual_form"
    EMAIL = "email"
    VENDOR_PORTAL = "vendor_portal"
    PARALLEL_SEARCH = "parallel_search"


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    FETCHING = "fetching"
    PARSING = "parsing"
    PARSED = "parsed"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    PROMOTED = "promoted"
    FAILED = "failed"
    REJECTED = "rejected"


class ConfidenceLevel(StrEnum):
    """How much a value can be trusted. Drives the data-quality dashboard."""

    VERIFIED = "verified"
    VENDOR_DECLARED = "vendor_declared"
    THIRD_PARTY = "third_party"
    AI_EXTRACTED = "ai_extracted"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"


class ValueOrigin(StrEnum):
    """Where a single field value came from - the traceability primitive."""

    MANUAL = "manual"
    AI_EXTRACTION = "ai_extraction"
    AI_NORMALIZATION = "ai_normalization"
    AI_INFERENCE = "ai_inference"
    IMPORT = "import"
    API_SYNC = "api_sync"
    CALCULATED = "calculated"


class AiJobType(StrEnum):
    EXTRACT_STRUCTURED = "extract_structured"
    NORMALIZE_VALUES = "normalize_values"
    SUMMARIZE_VENDOR = "summarize_vendor"
    CLASSIFY_RECORD = "classify_record"
    DETECT_MISSING_FIELDS = "detect_missing_fields"
    QUALITY_CHECK = "quality_check"
    CONTRADICTION_CHECK = "contradiction_check"
    DEDUPE_CANDIDATE = "dedupe_candidate"
    WEB_SEARCH = "web_search"
    SIMILARITY_MATCH = "similarity_match"


class AiJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_REVIEW = "awaiting_review"


class ReviewDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    ACCEPTED_WITH_EDITS = "accepted_with_edits"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class PumpType(StrEnum):
    """API 610 / API 674 / API 675 families plus common offshore utility types."""

    CENTRIFUGAL_OH1 = "centrifugal_oh1"
    CENTRIFUGAL_OH2 = "centrifugal_oh2"
    CENTRIFUGAL_OH3 = "centrifugal_oh3"
    CENTRIFUGAL_OH5 = "centrifugal_oh5"
    CENTRIFUGAL_OH6 = "centrifugal_oh6"
    BETWEEN_BEARINGS_BB1 = "between_bearings_bb1"
    BETWEEN_BEARINGS_BB2 = "between_bearings_bb2"
    BETWEEN_BEARINGS_BB3 = "between_bearings_bb3"
    BETWEEN_BEARINGS_BB4 = "between_bearings_bb4"
    BETWEEN_BEARINGS_BB5 = "between_bearings_bb5"
    VERTICALLY_SUSPENDED_VS1 = "vertically_suspended_vs1"
    VERTICALLY_SUSPENDED_VS4 = "vertically_suspended_vs4"
    VERTICALLY_SUSPENDED_VS6 = "vertically_suspended_vs6"
    SUBMERSIBLE = "submersible"
    RECIPROCATING_PLUNGER = "reciprocating_plunger"
    RECIPROCATING_DIAPHRAGM = "reciprocating_diaphragm"
    ROTARY_SCREW = "rotary_screw"
    ROTARY_GEAR = "rotary_gear"
    ROTARY_PROGRESSIVE_CAVITY = "rotary_progressive_cavity"
    METERING_DOSING = "metering_dosing"
    MULTIPHASE = "multiphase"
    ESP = "esp"
    FIREWATER = "firewater"
    OTHER = "other"


class ApplicableStandard(StrEnum):
    API_610 = "api_610"
    API_674 = "api_674"
    API_675 = "api_675"
    API_676 = "api_676"
    API_682 = "api_682"
    API_685 = "api_685"
    ISO_13709 = "iso_13709"
    ISO_5199 = "iso_5199"
    ISO_2858 = "iso_2858"
    ASME_B73_1 = "asme_b73_1"
    ASME_B73_2 = "asme_b73_2"
    NFPA_20 = "nfpa_20"
    HYDRAULIC_INSTITUTE = "hydraulic_institute"
    EN_733 = "en_733"
    CLIENT_SPEC = "client_spec"
    OTHER = "other"


class DriverType(StrEnum):
    ELECTRIC_MOTOR = "electric_motor"
    VFD_ELECTRIC_MOTOR = "vfd_electric_motor"
    STEAM_TURBINE = "steam_turbine"
    GAS_TURBINE = "gas_turbine"
    DIESEL_ENGINE = "diesel_engine"
    HYDRAULIC = "hydraulic"
    AIR_MOTOR = "air_motor"
    OTHER = "other"


class SealSystemType(StrEnum):
    """API 682 seal arrangements plus non-API options."""

    ARRANGEMENT_1 = "api682_arrangement_1"
    ARRANGEMENT_2 = "api682_arrangement_2"
    ARRANGEMENT_3 = "api682_arrangement_3"
    PACKED_GLAND = "packed_gland"
    MAGNETIC_DRIVE = "magnetic_drive"
    CANNED_MOTOR = "canned_motor"
    SEAL_LESS_OTHER = "seal_less_other"
    OTHER = "other"


class AreaClassification(StrEnum):
    ZONE_0 = "zone_0"
    ZONE_1 = "zone_1"
    ZONE_2 = "zone_2"
    CLASS_I_DIV_1 = "class_i_div_1"
    CLASS_I_DIV_2 = "class_i_div_2"
    SAFE_AREA = "safe_area"
    OTHER = "other"


class Incoterm(StrEnum):
    EXW = "exw"
    FCA = "fca"
    FAS = "fas"
    FOB = "fob"
    CFR = "cfr"
    CIF = "cif"
    CPT = "cpt"
    CIP = "cip"
    DAP = "dap"
    DPU = "dpu"
    DDP = "ddp"


class VendorApprovalStatus(StrEnum):
    APPROVED = "approved"
    CONDITIONALLY_APPROVED = "conditionally_approved"
    PENDING_QUALIFICATION = "pending_qualification"
    UNDER_REVIEW = "under_review"
    NOT_APPROVED = "not_approved"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"


class VendorTier(StrEnum):
    TIER_1_OEM = "tier_1_oem"
    TIER_2_OEM = "tier_2_oem"
    TIER_3_OEM = "tier_3_oem"
    PACKAGER = "packager"
    AUTHORIZED_DISTRIBUTOR = "authorized_distributor"
    AGENT_REPRESENTATIVE = "agent_representative"
    AFTERMARKET_SERVICE = "aftermarket_service"
    UNCLASSIFIED = "unclassified"


class SanctionsScreeningStatus(StrEnum):
    CLEARED = "cleared"
    FLAGGED_REVIEW = "flagged_review"
    RESTRICTED = "restricted"
    SANCTIONED = "sanctioned"
    NOT_SCREENED = "not_screened"


class DocumentKind(StrEnum):
    DATASHEET = "datasheet"
    PERFORMANCE_CURVE = "performance_curve"
    GA_DRAWING = "ga_drawing"
    QUOTATION = "quotation"
    CERTIFICATE = "certificate"
    TEST_REPORT = "test_report"
    MANUAL = "manual"
    REFERENCE_LIST = "reference_list"
    COMPANY_PROFILE = "company_profile"
    FINANCIAL_STATEMENT = "financial_statement"
    SPREADSHEET = "spreadsheet"
    OTHER = "other"


class ScorecardKind(StrEnum):
    TECHNICAL_FIT = "technical_fit"
    COMMERCIAL_FIT = "commercial_fit"
    DELIVERY_RISK = "delivery_risk"
    DATA_CONFIDENCE = "data_confidence"
    OVERALL = "overall"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ_SENSITIVE = "read_sensitive"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    EXPORT = "export"
    IMPORT = "import"
    AI_SUGGESTION_APPLIED = "ai_suggestion_applied"
    AI_SUGGESTION_REJECTED = "ai_suggestion_rejected"
    PERMISSION_CHANGE = "permission_change"
    TENANT_CHANGE = "tenant_change"
    MERGE = "merge"


class FlagSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DataQualityFlagType(StrEnum):
    MISSING_REQUIRED_FIELD = "missing_required_field"
    OUT_OF_RANGE = "out_of_range"
    UNIT_MISMATCH = "unit_mismatch"
    CONTRADICTION = "contradiction"
    SUSPICIOUS_VALUE = "suspicious_value"
    STALE_DATA = "stale_data"
    DUPLICATE_SUSPECT = "duplicate_suspect"
    UNNORMALIZED_VALUE = "unnormalized_value"
    SOURCE_UNVERIFIED = "source_unverified"


class TenantStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CHURNED = "churned"


class TenantPlan(StrEnum):
    TRIAL = "trial"
    STANDARD = "standard"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
