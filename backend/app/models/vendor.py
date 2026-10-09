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


#: The identity columns migration 003 adds, named where they are declared.
#:
#: They are mapped `deferred`, which keeps an ordinary entity load working against a
#: database the migration has not reached yet. Anything that touches *every* column by
#: name - a response model built from the table, a full-record serialisation - defeats
#: that by loading each one, so those callers read this set and leave them out.
#:
#: Excluding them from the list response is also right once the migration *is* applied:
#: a deferred column in a list is one extra query per row.
MIGRATION_003_COLUMNS = frozenset(
    {
        "address_line",
        "state_region",
        "legal_entity_name",
        "client_since",
        "is_purchasing_blocked",
        "purchasing_block_note",
    }
)


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
    # ---------- added by migration 003 ----------
    #
    # `deferred` on every one of them, which is what lets this model describe a database
    # that has the columns and one that has not yet had the migration applied. A deferred
    # column is left out of the default SELECT, so the ordinary entity load that every
    # list, search and profile does keeps working either way, and the column is fetched
    # only when something actually asks for it.
    #
    # The alternative was discovered the hard way on `vendor_contacts`: declaring a
    # column the deployed database lacks makes *every* read of that table fail with
    # "column does not exist", because an ORM entity load asks for all of them.
    address_line: Mapped[str | None] = mapped_column(
        String(500), deferred=True, comment="Street address as the source states it"
    )
    state_region: Mapped[str | None] = mapped_column(
        String(120), deferred=True, comment="State, province or county"
    )
    legal_entity_name: Mapped[str | None] = mapped_column(
        String(255),
        deferred=True,
        comment="Registered name where it differs from the trading name",
    )
    client_since: Mapped[date | None] = mapped_column(
        Date,
        deferred=True,
        comment="When this client first opened an account with the supplier",
    )
    is_purchasing_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        deferred=True,
        comment="The client has barred purchasing from this supplier",
    )
    purchasing_block_note: Mapped[str | None] = mapped_column(Text, deferred=True)
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


class VendorApproval(UUIDPrimaryKey, Timestamps, Base):
    """One statement from a client document that a vendor may supply one package.

    The central fact in a signed approved suppliers list: *this* engineering authority
    approved *this* vendor for *this* equipment package on *this* project. It was being
    flattened into `Vendor.product_families`, which loses the project and the authority,
    and into `extra["approved_packages"]`, which loses the ability to query it.

    A row per statement makes "who may supply sea water injection pumps on KG-DWN-98/2"
    a query, and lets one approval lapse on its own date instead of a whole vendor being
    approved for ever.
    """

    __tablename__ = "vendor_approvals"
    __table_args__ = (
        UniqueConstraint("vendor_id", "project", "package", name="uq_vendor_approval"),
        Index("ix_vendor_approvals_vendor", "vendor_id"),
        Index("ix_vendor_approvals_project", "tenant_id", "project"),
        Index("ix_vendor_approvals_package", "package"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    project: Mapped[str] = mapped_column(String(160), nullable=False)
    package: Mapped[str] = mapped_column(String(300), nullable=False)
    approved_country: Mapped[str | None] = mapped_column(
        String(160),
        comment="Countries as the document writes them - 'UK / Brazil / India' - kept verbatim",
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="approved")
    document_reference: Mapped[str | None] = mapped_column(
        String(300), comment="The document number, so an answer can cite it"
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    approved_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<VendorApproval {self.package} on {self.project}>"


class VendorIdentifier(UUIDPrimaryKey, Timestamps, Base):
    """A registration or tax identifier: gst, pan, msme, vat, sap_vendor_no, duns.

    Scheme-keyed rather than a column per tax regime. The client's exports carry Indian
    GST, PAN and MSME numbers; a Norwegian or Brazilian list carries entirely different
    ones, and each would otherwise be another migration and another mostly-empty column.
    `scheme` is text on purpose: a new regime costs a row.

    It is also how a buyer finds a company they have only a tax number for.
    """

    __tablename__ = "vendor_identifiers"
    __table_args__ = (
        UniqueConstraint("vendor_id", "scheme", "value", name="uq_vendor_identifier"),
        Index("ix_vendor_identifiers_vendor", "vendor_id"),
        Index("ix_vendor_identifiers_lookup", "scheme", "value"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    scheme: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    issued_country: Mapped[str | None] = mapped_column(String(2))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<VendorIdentifier {self.scheme}={self.value}>"
