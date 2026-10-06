"""Denormalised search index.

PostgreSQL full-text search is the Phase 1 engine. One row per pump model, refreshed
by a worker whenever the model or any of its current specs change. Numeric columns are
duplicated here so range filters (price, lead time, flow, head, weight) never have to
join six spec tables.

Moving to OpenSearch later means writing a second consumer of this same table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    ApplicableStandard,
    ConfidenceLevel,
    PumpType,
    VendorApprovalStatus,
    VerificationStatus,
)
from app.models.types import Money, Quantity, Ratio, Score, pg_enum


class SearchIndex(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "search_index"
    __table_args__ = (
        UniqueConstraint("pump_model_id"),
        Index("ix_search_index_tsv", "search_vector", postgresql_using="gin"),
        Index("ix_search_index_tenant_type", "tenant_id", "pump_type"),
        Index("ix_search_index_country", "tenant_id", "vendor_country"),
        Index("ix_search_index_duty", "tenant_id", "rated_capacity_m3h", "rated_head_m"),
        Index("ix_search_index_price", "tenant_id", "base_price_usd"),
        Index("ix_search_index_lead_time", "tenant_id", "standard_lead_time_weeks"),
        Index("ix_search_index_certs", "certifications", postgresql_using="gin"),
        Index(
            "ix_search_index_trgm_label",
            "label",
            postgresql_using="gin",
            postgresql_ops={"label": "gin_trgm_ops"},
        ),
    )

    pump_model_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pump_models.id", ondelete="CASCADE"), nullable=False
    )
    pump_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pumps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ---------- display ----------
    label: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="Vendor + pump + model, as shown in result rows"
    )
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pump_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_code: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)

    # ---------- full text ----------
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    searchable_text: Mapped[str | None] = mapped_column(
        Text, comment="Concatenated haystack the tsvector is generated from"
    )

    # ---------- categorical filters ----------
    vendor_country: Mapped[str | None] = mapped_column(String(2))
    manufacturing_countries: Mapped[list | None] = mapped_column(ARRAY(String(2)))
    country_of_origin: Mapped[str | None] = mapped_column(String(2))
    pump_type: Mapped[PumpType | None] = mapped_column(pg_enum(PumpType, "pump_type"))
    applicable_standard: Mapped[ApplicableStandard | None] = mapped_column(
        pg_enum(ApplicableStandard, "applicable_standard")
    )
    service_application: Mapped[str | None] = mapped_column(String(255))
    area_classification: Mapped[str | None] = mapped_column(String(40))
    seal_system_type: Mapped[str | None] = mapped_column(String(60))
    driver_type: Mapped[str | None] = mapped_column(String(60))
    material_class: Mapped[str | None] = mapped_column(String(24))
    certifications: Mapped[list | None] = mapped_column(ARRAY(String(120)))
    incoterms_offered: Mapped[list | None] = mapped_column(ARRAY(String(8)))
    vendor_approval_status: Mapped[VendorApprovalStatus | None] = mapped_column(
        pg_enum(VendorApprovalStatus, "vendor_approval_status")
    )
    vendor_tier: Mapped[str | None] = mapped_column(String(40))
    fpso_experience: Mapped[bool | None] = mapped_column(Boolean)
    nace_compliant: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- numeric filters ----------
    rated_capacity_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    rated_head_m: Mapped[Decimal | None] = mapped_column(Quantity)
    npsh_required_m: Mapped[Decimal | None] = mapped_column(Quantity)
    hydraulic_efficiency_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    rated_speed_rpm: Mapped[int | None] = mapped_column(Integer)
    rated_power_kw: Mapped[Decimal | None] = mapped_column(Quantity)
    fluid_temperature_max_c: Mapped[Decimal | None] = mapped_column(Quantity)
    casing_design_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)
    base_price_usd: Mapped[Decimal | None] = mapped_column(Money)
    standard_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    expedited_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    dry_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    operating_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    footprint_area_m2: Mapped[Decimal | None] = mapped_column(Quantity)
    on_time_delivery_pct: Mapped[Decimal | None] = mapped_column(Ratio)
    units_installed: Mapped[int | None] = mapped_column(Integer)
    mtbf_hours: Mapped[int | None] = mapped_column(Integer)

    # ---------- quality ----------
    confidence_level: Mapped[ConfidenceLevel | None] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level")
    )
    verification_status: Mapped[VerificationStatus | None] = mapped_column(
        pg_enum(VerificationStatus, "verification_status")
    )
    data_completeness_pct: Mapped[Decimal | None] = mapped_column(Ratio)
    data_confidence_score: Mapped[Decimal | None] = mapped_column(Score)
    open_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_shared_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_source_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_version: Mapped[str | None] = mapped_column(String(24))
