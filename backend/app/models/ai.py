"""AI job orchestration, extraction output, provenance and data-quality flags.

The contract enforced by this module:

    no intelligence field may be written by AI without a ``field_provenance`` row
    that names the source, the job, the model and the confidence.

``ai_jobs`` records the call, ``extracted_entities`` records what the model returned
verbatim, ``ai_suggestions`` records what a human is asked to approve, and
``field_provenance`` records what was ultimately written and why.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    AiJobStatus,
    AiJobType,
    ConfidenceLevel,
    DataQualityFlagType,
    FlagSeverity,
    ReviewDecision,
    ScorecardKind,
    ValueOrigin,
)
from app.models.source import Source
from app.models.types import Json, Ratio, Score, pg_enum


class AiJob(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """One AI or web-search invocation, with full request/response accounting."""

    __tablename__ = "ai_jobs"
    __table_args__ = (
        Index("ix_ai_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_ai_jobs_type_created", "job_type", "created_at"),
        Index("ix_ai_jobs_subject", "subject_type", "subject_id"),
    )

    job_type: Mapped[AiJobType] = mapped_column(pg_enum(AiJobType, "ai_job_type"), nullable=False)
    status: Mapped[AiJobStatus] = mapped_column(
        pg_enum(AiJobStatus, "ai_job_status"), nullable=False, default=AiJobStatus.PENDING
    )
    provider: Mapped[str] = mapped_column(
        String(40), nullable=False, default="openrouter", comment="openrouter | parallel"
    )
    model: Mapped[str | None] = mapped_column(String(160))
    prompt_name: Mapped[str | None] = mapped_column(
        String(120), comment="Named template used, e.g. extract_technical_v3"
    )
    prompt_version: Mapped[str | None] = mapped_column(String(24))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    subject_type: Mapped[str | None] = mapped_column(
        String(60), comment="vendor | pump | pump_model | technical_spec | ..."
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    request_payload: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    response_payload: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    raw_response_text: Mapped[str | None] = mapped_column(
        Text, comment="Verbatim model output, kept for audit and re-parsing"
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    celery_task_id: Mapped[str | None] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    entities: Mapped[list[ExtractedEntity]] = relationship(back_populates="ai_job")

    def __repr__(self) -> str:
        return f"<AiJob {self.job_type} {self.status}>"


class ExtractedEntity(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Structured JSON the model pulled out of one source, before promotion.

    Nothing here is authoritative. Promotion to the spec tables happens only through
    the AI review screen (or auto-promotion above a confidence threshold), and always
    writes ``field_provenance`` rows.
    """

    __tablename__ = "extracted_entities"
    __table_args__ = (
        Index("ix_extracted_entities_tenant_review", "tenant_id", "review_decision"),
        Index("ix_extracted_entities_source", "source_id"),
        Index("ix_extracted_entities_target", "target_type", "target_id"),
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE")
    )
    ai_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    entity_type: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        comment="vendor | pump | pump_model | technical_spec | commercial_spec | ...",
    )
    payload: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Normalised candidate record"
    )
    raw_payload: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Pre-normalisation model output"
    )
    field_confidences: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment='{"rated_head_m": 0.82, ...}'
    )
    evidence_spans: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment='{"rated_head_m": {"quote": "...", "char_start": 1420}} - traceability',
    )
    overall_confidence: Mapped[Decimal | None] = mapped_column(Ratio)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"),
        nullable=False,
        default=ConfidenceLevel.AI_EXTRACTED,
    )
    review_decision: Mapped[ReviewDecision] = mapped_column(
        pg_enum(ReviewDecision, "review_decision"), nullable=False, default=ReviewDecision.PENDING
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewer_edits: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Field-level corrections a human made"
    )
    target_type: Mapped[str | None] = mapped_column(
        String(60), comment="Set on promotion: which table received the data"
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source | None] = relationship(back_populates="extracted_entities")
    ai_job: Mapped[AiJob | None] = relationship(back_populates="entities")


class FieldProvenance(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Per-field lineage. The answer to "where did this number come from?".

    One row per (entity, field) write. Old rows are kept, so a field's full history -
    manual entry, AI overwrite, human correction - is reconstructible.
    """

    __tablename__ = "field_provenance"
    __table_args__ = (
        Index("ix_field_provenance_entity", "entity_type", "entity_id"),
        Index("ix_field_provenance_field", "entity_type", "entity_id", "field_name", "is_current"),
        Index("ix_field_provenance_source", "source_id"),
        Index("ix_field_provenance_origin", "tenant_id", "value_origin"),
    )

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_text: Mapped[str | None] = mapped_column(
        Text, comment="Written value rendered as text, for diffing and audit"
    )
    previous_value_text: Mapped[str | None] = mapped_column(Text)
    value_origin: Mapped[ValueOrigin] = mapped_column(
        pg_enum(ValueOrigin, "value_origin"), nullable=False
    )
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"),
        nullable=False,
        default=ConfidenceLevel.UNKNOWN,
    )
    confidence_score: Mapped[Decimal | None] = mapped_column(Ratio)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    ai_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    extracted_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extracted_entities.id", ondelete="SET NULL")
    )
    model_used: Mapped[str | None] = mapped_column(String(160))
    evidence_quote: Mapped[str | None] = mapped_column(
        Text, comment="Verbatim snippet from the source that supports the value"
    )
    evidence_locator: Mapped[str | None] = mapped_column(
        String(255), comment="Page number, cell reference, char offset or CSS selector"
    )
    original_value: Mapped[str | None] = mapped_column(
        String(500), comment="Value as printed in the source, before unit normalisation"
    )
    original_unit: Mapped[str | None] = mapped_column(String(40))
    normalization_note: Mapped[str | None] = mapped_column(Text)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<FieldProvenance {self.entity_type}.{self.field_name}>"


class ConfidenceScore(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Scorecards: technical fit, commercial fit, delivery risk, data confidence.

    Computed by the scoring service against a tenant's weighting profile, and stored so
    a comparison can be reproduced exactly as it was shown to the buyer.
    """

    __tablename__ = "confidence_scores"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "scorecard_kind",
            "requirement_profile_id",
        ),
        Index("ix_confidence_scores_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scorecard_kind: Mapped[ScorecardKind] = mapped_column(
        pg_enum(ScorecardKind, "scorecard_kind"), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Score, nullable=False, comment="0.000 - 100.000")
    grade: Mapped[str | None] = mapped_column(String(4), comment="A / B / C / D / E")
    breakdown: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment='Per-criterion contributions: {"npsh_margin": {"score": 80, "weight": 0.1}}',
    )
    weighting_profile: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    requirement_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("requirement_profiles.id", ondelete="CASCADE"),
        comment="NULL means scored against platform defaults",
    )
    fields_evaluated: Mapped[int | None] = mapped_column(Integer)
    fields_missing: Mapped[int | None] = mapped_column(Integer)
    computed_by_version: Mapped[str | None] = mapped_column(String(24))
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DataQualityFlag(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Contradictions, out-of-range values, staleness, duplicate suspicion.

    Raised by the deterministic validators and by Gemma quality checks. Drives the
    Data Quality dashboard and the review workload.
    """

    __tablename__ = "data_quality_flags"
    __table_args__ = (
        Index("ix_dq_flags_tenant_open", "tenant_id", "is_resolved", "severity"),
        Index("ix_dq_flags_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(120))
    flag_type: Mapped[DataQualityFlagType] = mapped_column(
        pg_enum(DataQualityFlagType, "data_quality_flag_type"), nullable=False
    )
    severity: Mapped[FlagSeverity] = mapped_column(
        pg_enum(FlagSeverity, "flag_severity"), nullable=False, default=FlagSeverity.MEDIUM
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detected_value: Mapped[str | None] = mapped_column(String(500))
    expected_range: Mapped[str | None] = mapped_column(String(255))
    conflicting_entity_type: Mapped[str | None] = mapped_column(String(60))
    conflicting_entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    conflicting_value: Mapped[str | None] = mapped_column(String(500))
    detected_by: Mapped[str] = mapped_column(
        String(40), nullable=False, default="validator", comment="validator | ai | user"
    )
    ai_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution: Mapped[str | None] = mapped_column(
        String(40), comment="corrected | accepted_as_is | false_positive | deferred"
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str | None] = mapped_column(Text)


class AiSuggestion(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A single field-level proposal awaiting human approval (AI review screen)."""

    __tablename__ = "ai_suggestions"
    __table_args__ = (
        Index("ix_ai_suggestions_tenant_decision", "tenant_id", "decision"),
        Index("ix_ai_suggestions_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    suggestion_kind: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="fill_missing | normalize | correct | enrich | flag_removal",
    )
    current_value: Mapped[str | None] = mapped_column(Text)
    suggested_value: Mapped[str | None] = mapped_column(Text)
    suggested_value_json: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[Decimal | None] = mapped_column(Ratio)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"),
        nullable=False,
        default=ConfidenceLevel.AI_EXTRACTED,
    )
    ai_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    extracted_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extracted_entities.id", ondelete="SET NULL")
    )
    decision: Mapped[ReviewDecision] = mapped_column(
        pg_enum(ReviewDecision, "review_decision"), nullable=False, default=ReviewDecision.PENDING
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_value: Mapped[str | None] = mapped_column(
        Text, comment="What was actually written, if the reviewer edited the suggestion"
    )
    decision_notes: Mapped[str | None] = mapped_column(Text)


class DuplicateCandidate(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Suspected duplicate pairs, from deterministic keys plus AI adjudication."""

    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "entity_id_a", "entity_id_b"),
        Index("ix_duplicate_candidates_open", "tenant_id", "status", "similarity_score"),
    )

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id_a: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_id_b: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    similarity_score: Mapped[Decimal] = mapped_column(Ratio, nullable=False)
    match_signals: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment='{"normalized_name": 1.0, "duty_point": 0.97, "trigram": 0.88}',
    )
    detection_method: Mapped[str] = mapped_column(
        String(40), nullable=False, default="deterministic", comment="deterministic | ai | manual"
    )
    ai_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="open", comment="open | merged | distinct | deferred"
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
