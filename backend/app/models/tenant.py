"""Tenants (client companies) and their entitlements."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey
from app.models.enums import TenantPlan, TenantStatus
from app.models.types import Json, pg_enum

if TYPE_CHECKING:
    from app.models.user import User


class Tenant(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """A client company. The root of every isolation boundary in the platform."""

    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(2), comment="ISO 3166-1 alpha-2")
    industry_segment: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. upstream FPSO operator, EPC contractor"
    )
    status: Mapped[TenantStatus] = mapped_column(
        pg_enum(TenantStatus, "tenant_status"), nullable=False, default=TenantStatus.TRIAL
    )
    plan: Mapped[TenantPlan] = mapped_column(
        pg_enum(TenantPlan, "tenant_plan"), nullable=False, default=TenantPlan.TRIAL
    )
    contract_start: Mapped[date | None] = mapped_column(Date)
    contract_end: Mapped[date | None] = mapped_column(Date)

    # Entitlements / quotas
    can_use_shared_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_contribute_shared_master: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    max_ai_jobs_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    max_storage_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=10_240)
    data_retention_days: Mapped[int | None] = mapped_column(Integer)

    # Tenant-specific weighting for scorecards, unit preferences, branding
    settings: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    primary_contact_email: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list[User]] = relationship(back_populates="tenant")
    # tenant_permissions has two FKs to tenants (tenant_id and shared_with_tenant_id),
    # so both sides of this relationship must say which one they mean.
    permissions: Mapped[list[TenantPermission]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        foreign_keys="TenantPermission.tenant_id",
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.slug}>"


class TenantPermission(UUIDPrimaryKey, Timestamps, Base):
    """Per-tenant feature and data-scope grants.

    Two shapes are supported:
      * ``resource`` + ``action``  - feature entitlement (e.g. ``comparison``/``export``)
      * ``resource`` + ``shared_with_tenant_id`` - cross-tenant data sharing grant
    """

    __tablename__ = "tenant_permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource",
            "action",
            "shared_with_tenant_id",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="read")
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    shared_with_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    constraints: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    tenant: Mapped[Tenant] = relationship(back_populates="permissions", foreign_keys=[tenant_id])
