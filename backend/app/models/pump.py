"""Pumps (product lines) and pump models (orderable variants)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

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
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDelete, TenantScoped, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    ApplicableStandard,
    ConfidenceLevel,
    PumpType,
    VerificationStatus,
)
from app.models.types import Json, pg_enum
from app.models.vendor import Vendor

if TYPE_CHECKING:
    from app.models.specs import (
        AdministrativeSpec,
        CommercialSpec,
        DeliverySpec,
        DimensionalSpec,
        OperationalSpec,
        TechnicalSpec,
    )


class Pump(UUIDPrimaryKey, Timestamps, SoftDelete, TenantScoped, Base):
    """A vendor product line, e.g. "Sulzer MSD" or "Flowserve HPX".

    One row per (vendor, product family). Orderable variants live in ``pump_models``.
    """

    __tablename__ = "pumps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "vendor_id", "normalized_name"),
        Index("ix_pumps_type_standard", "pump_type", "applicable_standard"),
        Index("ix_pumps_tenant_vendor", "tenant_id", "vendor_id"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_family: Mapped[str | None] = mapped_column(String(160))
    pump_type: Mapped[PumpType] = mapped_column(
        pg_enum(PumpType, "pump_type"), nullable=False, default=PumpType.OTHER, index=True
    )
    pump_type_raw: Mapped[str | None] = mapped_column(
        String(255), comment="Original uncontrolled string as captured from the source"
    )
    applicable_standard: Mapped[ApplicableStandard] = mapped_column(
        pg_enum(ApplicableStandard, "applicable_standard"),
        nullable=False,
        default=ApplicableStandard.OTHER,
        index=True,
    )
    additional_standards: Mapped[list | None] = mapped_column(ARRAY(String(64)))
    standard_edition: Mapped[str | None] = mapped_column(
        String(64), comment="e.g. API 610 12th Edition / ISO 13709:2009"
    )
    service_application: Mapped[str | None] = mapped_column(
        String(255), comment="e.g. crude export, produced water injection, firewater"
    )
    handled_fluids: Mapped[list | None] = mapped_column(ARRAY(String(120)))
    description: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    is_discontinued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ---------- provenance ----------
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"),
        nullable=False,
        default=ConfidenceLevel.UNKNOWN,
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        pg_enum(VerificationStatus, "verification_status"),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    primary_source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_shared_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    merged_into_pump_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pumps.id", ondelete="SET NULL")
    )
    extra: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    vendor: Mapped[Vendor] = relationship(back_populates="pumps")
    models: Mapped[list[PumpModel]] = relationship(
        back_populates="pump", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Pump {self.name}>"


class PumpModel(UUIDPrimaryKey, Timestamps, SoftDelete, TenantScoped, Base):
    """A specific orderable configuration, e.g. "HPX 4x6x11B, 2 stage".

    Every spec table hangs off this row, so a quotation, a datasheet and a track
    record all resolve to the same intelligence subject.
    """

    __tablename__ = "pump_models"
    __table_args__ = (
        UniqueConstraint("tenant_id", "pump_id", "model_code"),
        Index("ix_pump_models_tenant_pump", "tenant_id", "pump_id"),
        Index("ix_pump_models_code", "model_code"),
    )

    pump_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pumps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_code: Mapped[str] = mapped_column(String(160), nullable=False)
    size_designation: Mapped[str | None] = mapped_column(
        String(120), comment="Suction x discharge x nominal impeller, e.g. 4x6x11"
    )
    frame_size: Mapped[str | None] = mapped_column(String(80))
    stages: Mapped[int | None] = mapped_column(Integer)
    orientation: Mapped[str | None] = mapped_column(
        String(32), comment="horizontal | vertical | inline"
    )
    generation: Mapped[str | None] = mapped_column(String(64))
    tag_number: Mapped[str | None] = mapped_column(
        String(80), comment="Client tag when the record came from a project datasheet"
    )
    project_reference: Mapped[str | None] = mapped_column(String(255))

    # ---------- provenance ----------
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"),
        nullable=False,
        default=ConfidenceLevel.UNKNOWN,
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        pg_enum(VerificationStatus, "verification_status"),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    data_completeness_pct: Mapped[float | None] = mapped_column(
        comment="Share of required intelligence fields populated; recomputed by worker"
    )
    primary_source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_shared_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    merged_into_pump_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pump_models.id", ondelete="SET NULL")
    )
    extra: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    pump: Mapped[Pump] = relationship(back_populates="models")
    technical_specs: Mapped[list[TechnicalSpec]] = relationship(
        back_populates="pump_model", cascade="all, delete-orphan"
    )
    commercial_specs: Mapped[list[CommercialSpec]] = relationship(
        back_populates="pump_model", cascade="all, delete-orphan"
    )
    dimensional_specs: Mapped[list[DimensionalSpec]] = relationship(
        back_populates="pump_model", cascade="all, delete-orphan"
    )
    delivery_specs: Mapped[list[DeliverySpec]] = relationship(
        back_populates="pump_model", cascade="all, delete-orphan"
    )
    operational_specs: Mapped[list[OperationalSpec]] = relationship(
        back_populates="pump_model", cascade="all, delete-orphan"
    )
    administrative_specs: Mapped[list[AdministrativeSpec]] = relationship(
        back_populates="pump_model", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<PumpModel {self.model_code}>"
