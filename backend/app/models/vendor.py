"""Vendors - the manufacturer / packager / distributor dimension."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
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
    ConfidenceLevel,
    SanctionsScreeningStatus,
    VendorApprovalStatus,
    VendorTier,
    VerificationStatus,
)
from app.models.types import Json, Money, Ratio, pg_enum

if TYPE_CHECKING:
    from app.models.pump import Pump


class Vendor(UUIDPrimaryKey, Timestamps, SoftDelete, TenantScoped, Base):
    """A pump supplier.

    ``tenant_id IS NULL`` marks a shared-master vendor curated by Targeticon and
    readable by every tenant with ``can_use_shared_master``.
    """

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_name", "country"),
        Index("ix_vendors_tenant_status", "tenant_id", "approval_status"),
        Index("ix_vendors_tier", "vendor_tier"),
    )

    # ---------- identity ----------
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Lowercased, legal-suffix-stripped; dedupe key"
    )
    aliases: Mapped[list | None] = mapped_column(ARRAY(String(255)))
    website: Mapped[str | None] = mapped_column(String(500))
    hq_country: Mapped[str | None] = mapped_column(String(2), index=True)
    country: Mapped[str | None] = mapped_column(
        String(2), index=True, comment="Operating country for this record"
    )
    hq_city: Mapped[str | None] = mapped_column(String(120))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(
        Text, comment="Gemma-generated vendor briefing; regenerated on material change"
    )
    ai_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ---------- classification ----------
    vendor_tier: Mapped[VendorTier] = mapped_column(
        pg_enum(VendorTier, "vendor_tier"), nullable=False, default=VendorTier.UNCLASSIFIED
    )
    vendor_category: Mapped[str | None] = mapped_column(
        String(120), comment="Client-specific category label"
    )
    product_families: Mapped[list | None] = mapped_column(ARRAY(String(120)))
    manufacturing_countries: Mapped[list | None] = mapped_column(ARRAY(String(2)))

    # ---------- vendor governance ----------
    approval_status: Mapped[VendorApprovalStatus] = mapped_column(
        pg_enum(VendorApprovalStatus, "vendor_approval_status"),
        nullable=False,
        default=VendorApprovalStatus.PENDING_QUALIFICATION,
    )
    approval_expiry: Mapped[date | None] = mapped_column(Date)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    sanctions_status: Mapped[SanctionsScreeningStatus] = mapped_column(
        pg_enum(SanctionsScreeningStatus, "sanctions_screening_status"),
        nullable=False,
        default=SanctionsScreeningStatus.NOT_SCREENED,
    )
    sanctions_screened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sanctions_notes: Mapped[str | None] = mapped_column(Text)
    geopolitical_risk_notes: Mapped[str | None] = mapped_column(Text)

    # ---------- financial standing ----------
    annual_revenue_usd: Mapped[Decimal | None] = mapped_column(Money)
    revenue_year: Mapped[int | None] = mapped_column(Integer)
    employee_count: Mapped[int | None] = mapped_column(Integer)
    credit_rating_agency: Mapped[str | None] = mapped_column(String(80))
    credit_rating: Mapped[str | None] = mapped_column(String(32))
    dun_bradstreet_number: Mapped[str | None] = mapped_column(String(32))
    financial_standing_notes: Mapped[str | None] = mapped_column(Text)
    bonding_capacity_usd: Mapped[Decimal | None] = mapped_column(Money)
    can_provide_performance_bond: Mapped[bool | None] = mapped_column(Boolean)
    can_provide_advance_payment_guarantee: Mapped[bool | None] = mapped_column(Boolean)
    insurance_coverage_usd: Mapped[Decimal | None] = mapped_column(Money)
    insurance_details: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    # ---------- aggregate intelligence (recomputed by workers) ----------
    on_time_delivery_pct: Mapped[Decimal | None] = mapped_column(Ratio)
    total_units_supplied: Mapped[int | None] = mapped_column(Integer)
    fpso_offshore_experience: Mapped[bool | None] = mapped_column(Boolean, index=True)
    data_completeness_pct: Mapped[Decimal | None] = mapped_column(Ratio)

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
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_shared_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    merged_into_vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="SET NULL"),
        comment="Set when this record was merged away as a duplicate",
    )
    extra: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    pumps: Mapped[list[Pump]] = relationship(back_populates="vendor")
    contacts: Mapped[list[VendorContact]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Vendor {self.name}>"


class VendorContact(UUIDPrimaryKey, Timestamps, Base):
    """Authorized representatives, agents and service contacts."""

    __tablename__ = "vendor_contacts"
    __table_args__ = (Index("ix_vendor_contacts_vendor_role", "vendor_id", "contact_role"),)

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    contact_role: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="commercial",
        comment="commercial | technical | agent | service | authorized_representative",
    )
    full_name: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(
        String(255), comment="Set when the contact is an agent/representative entity"
    )
    email: Mapped[str | None] = mapped_column(String(320))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        comment="The captured page this detail was read from; null when entered by hand",
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str | None] = mapped_column(
        String(24), comment="manual | ai_extraction, mirroring field_provenance"
    )
    phone: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(2))
    territory: Mapped[str | None] = mapped_column(String(255))
    agency_agreement_valid_until: Mapped[date | None] = mapped_column(Date)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    vendor: Mapped[Vendor] = relationship(back_populates="contacts")
