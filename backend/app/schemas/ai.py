"""AI review, enrichment and data-quality payloads."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel


class AiJobOut(ORMModel):
    id: uuid.UUID
    job_type: str
    status: str
    provider: str
    model: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    source_id: uuid.UUID | None = None
    subject_type: str | None = None
    subject_id: uuid.UUID | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    error_message: str | None = None
    started_at: Any = None
    finished_at: Any = None
    created_at: Any = None


class ExtractedEntityOut(ORMModel):
    id: uuid.UUID
    source_id: uuid.UUID | None = None
    ai_job_id: uuid.UUID | None = None
    entity_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    field_confidences: dict[str, Any] = Field(default_factory=dict)
    evidence_spans: dict[str, Any] = Field(default_factory=dict)
    overall_confidence: float | None = None
    confidence_level: str
    review_decision: str
    review_notes: str | None = None
    reviewer_edits: dict[str, Any] = Field(default_factory=dict)
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    promoted_at: Any = None
    created_at: Any = None


class ReviewQueueItem(ExtractedEntityOut):
    """One card on the AI review screen, with the context a reviewer needs."""

    source_title: str | None = None
    source_url: str | None = None
    source_type: str | None = None
    source_captured_at: Any = None
    suggested_vendor: str | None = None
    suggested_model_code: str | None = None
    field_count: int = 0
    matched_existing_vendor_id: uuid.UUID | None = None
    vendor_match: str = Field(
        default="missing",
        description="matched | new | missing - whether a vendor exists for this candidate",
    )


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(description="accepted | accepted_with_edits | rejected | escalated")
    edits: dict[str, Any] = Field(
        default_factory=dict, description="Field-level corrections applied before promotion"
    )
    vendor_id: uuid.UUID | None = Field(
        default=None, description="Bind the extraction to an existing vendor"
    )
    pump_model_id: uuid.UUID | None = Field(
        default=None, description="Bind the extraction to an existing pump model"
    )
    notes: str | None = None
    overwrite_verified: bool = Field(
        default=False,
        description="Allow overwriting human-verified fields (recorded in the audit log)",
    )


class BulkReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    decision: str = Field(description="accepted | rejected")
    notes: str | None = None
    min_confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Only act on candidates at or above this overall confidence",
    )


class AiSuggestionOut(ORMModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    field_name: str
    suggestion_kind: str
    current_value: str | None = None
    suggested_value: str | None = None
    rationale: str | None = None
    evidence_quote: str | None = None
    confidence_score: float | None = None
    confidence_level: str
    decision: str
    source_id: uuid.UUID | None = None
    ai_job_id: uuid.UUID | None = None
    created_at: Any = None


class SuggestionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(description="accepted | accepted_with_edits | rejected")
    applied_value: str | None = Field(
        default=None, description="Overrides the suggested value when the reviewer edits it"
    )
    notes: str | None = None


class EnrichRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[str] = Field(
        default_factory=lambda: ["detect_missing_fields", "quality_check"],
        description=(
            "detect_missing_fields | quality_check | normalize_values | summarize_vendor | "
            "contradiction_check | web_search"
        ),
    )
    run_web_search: bool = Field(
        default=False, description="Use Parallel AI to look for the missing fields"
    )


class QualityDashboard(BaseModel):
    """Aggregates behind the data-quality screen."""

    total_pump_models: int
    total_vendors: int
    avg_completeness_pct: float | None = None
    records_by_confidence: dict[str, int] = Field(default_factory=dict)
    records_by_verification: dict[str, int] = Field(default_factory=dict)
    open_flags_by_severity: dict[str, int] = Field(default_factory=dict)
    open_flags_by_type: dict[str, int] = Field(default_factory=dict)
    top_missing_fields: list[dict[str, Any]] = Field(default_factory=list)
    stale_records: int = 0
    duplicate_candidates_open: int = 0
    pending_ai_reviews: int = 0
    ai_field_share_pct: float | None = Field(
        default=None, description="Share of current field values written by AI"
    )


class FlagResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str = Field(description="corrected | accepted_as_is | false_positive | deferred")
    notes: str | None = None
    corrected_value: str | None = None


class DuplicateCandidateOut(ORMModel):
    id: uuid.UUID
    entity_type: str
    entity_id_a: uuid.UUID
    entity_id_b: uuid.UUID
    similarity_score: float
    match_signals: dict[str, Any] = Field(default_factory=dict)
    detection_method: str
    status: str
    label_a: str | None = None
    label_b: str | None = None
    created_at: Any = None


class MergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_id: uuid.UUID
    merge_id: uuid.UUID
    notes: str | None = None
