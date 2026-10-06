"""Comparisons, requirement profiles, saved searches and tags."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey
from app.models.types import Json, Money, Quantity, Score


class RequirementProfile(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """The buyer's duty point and acceptance criteria - what "fit" is measured against.

    A profile is the reusable definition of a requisition: required duty, required
    standards and certifications, weighting of technical vs commercial vs delivery.
    """

    __tablename__ = "requirement_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        Index("ix_requirement_profiles_tenant", "tenant_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    project_name: Mapped[str | None] = mapped_column(String(255))
    tag_number: Mapped[str | None] = mapped_column(String(80))

    # required duty point
    required_capacity_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    required_head_m: Mapped[Decimal | None] = mapped_column(Quantity)
    max_npshr_m: Mapped[Decimal | None] = mapped_column(Quantity)
    min_efficiency_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    fluid: Mapped[str | None] = mapped_column(String(160))
    fluid_temperature_c: Mapped[Decimal | None] = mapped_column(Quantity)
    fluid_specific_gravity: Mapped[Decimal | None] = mapped_column(Quantity)

    # hard requirements
    required_standard: Mapped[str | None] = mapped_column(String(64))
    required_pump_types: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    required_area_classification: Mapped[str | None] = mapped_column(String(40))
    required_certifications: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    required_material_class: Mapped[str | None] = mapped_column(String(24))
    nace_required: Mapped[bool | None] = mapped_column(Boolean)
    max_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    # Money, not an engineering quantity: this is compared directly against
    # commercial_specs.base_price_usd, so the precision has to match.
    max_budget_usd: Mapped[Decimal | None] = mapped_column(Money)
    max_dry_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    max_footprint_m2: Mapped[Decimal | None] = mapped_column(Quantity)
    excluded_countries: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    local_content_min_pct: Mapped[Decimal | None] = mapped_column(Quantity)

    # scorecard weighting - must sum to 1.0, validated in the service layer
    weight_technical: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0.40)
    weight_commercial: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0.25)
    weight_delivery: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0.20)
    weight_data_confidence: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0.15)
    criteria_overrides: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Comparison(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A saved side-by-side evaluation - the procurement deliverable."""

    __tablename__ = "comparisons"
    __table_args__ = (Index("ix_comparisons_tenant_created", "tenant_id", "created_at"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    requirement_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirement_profiles.id", ondelete="SET NULL")
    )
    comparison_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="pump_model", comment="pump_model | vendor"
    )
    fields_shown: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    snapshot: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment="Frozen values as displayed, so a decision record stays reproducible",
    )
    recommendation: Mapped[str | None] = mapped_column(Text)
    ai_narrative: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="draft", comment="draft | final | archived"
    )
    is_shared_in_tenant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    finalised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[ComparisonItem]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan"
    )


class ComparisonItem(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "comparison_items"
    __table_args__ = (
        UniqueConstraint("comparison_id", "pump_model_id", "vendor_id"),
        Index("ix_comparison_items_comparison", "comparison_id", "position"),
    )

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("comparisons.id", ondelete="CASCADE"), nullable=False
    )
    pump_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pump_models.id", ondelete="CASCADE")
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    technical_score: Mapped[Decimal | None] = mapped_column(Score)
    commercial_score: Mapped[Decimal | None] = mapped_column(Score)
    delivery_risk_score: Mapped[Decimal | None] = mapped_column(Score)
    data_confidence_score: Mapped[Decimal | None] = mapped_column(Score)
    overall_score: Mapped[Decimal | None] = mapped_column(Score)
    rank: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    disqualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disqualification_reason: Mapped[str | None] = mapped_column(String(500))
    reviewer_notes: Mapped[str | None] = mapped_column(Text)

    comparison: Mapped[Comparison] = relationship(back_populates="items")


class SavedSearch(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A stored query + filter set, optionally alerting on new matches (Phase 3)."""

    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("tenant_id", "created_by_user_id", "name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    query_text: Mapped[str | None] = mapped_column(String(1000))
    filters: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    sort_by: Mapped[str | None] = mapped_column(String(80))
    is_shared_in_tenant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_frequency: Mapped[str | None] = mapped_column(
        String(24), comment="daily | weekly | on_change"
    )
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result_count: Mapped[int | None] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


tagged_records = Table(
    "tagged_records",
    Base.metadata,
    Column(
        "tag_id", PGUUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("entity_type", String(60), primary_key=True),
    Column("entity_id", PGUUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")),
    Column("tagged_by_user_id", PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_tagged_records_entity", "entity_type", "entity_id"),
    Index("ix_tagged_records_tenant_tag", "tenant_id", "tag_id"),
)


class Tag(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Analyst-managed labels: watchlists, project codes, risk markers."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    color: Mapped[str | None] = mapped_column(String(9), comment="Hex, for dashboard chips")
    category: Mapped[str | None] = mapped_column(
        String(60), comment="watchlist | project | risk | commodity | custom"
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
