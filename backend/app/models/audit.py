"""Audit logs and record version history."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantScoped, UUIDPrimaryKey
from app.models.enums import AuditAction
from app.models.types import Json, pg_enum


class AuditLog(TenantScoped, Base):
    """Append-only audit trail.

    Uses a bigint identity primary key rather than a UUID: this is the highest-volume
    table in the platform and is always read in time order. Partition by month in
    production (see ``db/partitions.sql``).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor", "user_id", "occurred_at"),
        Index("ix_audit_logs_action", "action", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        pg_enum(AuditAction, "audit_action"), nullable=False
    )
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    entity_label: Mapped[str | None] = mapped_column(
        String(500), comment="Human-readable subject, kept even if the row is later deleted"
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    user_email: Mapped[str | None] = mapped_column(String(320))
    actor_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="user", comment="user | system | worker | api_key"
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment='{"field": {"from": "...", "to": "..."}} - the diff that was applied',
    )
    context: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Route, job id, batch id, reason"
    )
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    http_method: Mapped[str | None] = mapped_column(String(10))
    http_path: Mapped[str | None] = mapped_column(String(500))
    status_code: Mapped[int | None] = mapped_column(Integer)


class RecordVersion(UUIDPrimaryKey, TenantScoped, Base):
    """Full-row snapshots for change tracking and rollback.

    Written on every mutation of a vendor, pump, pump model or spec row. Combined with
    ``field_provenance`` this gives both "what did the record look like then" and
    "why is this field what it is".
    """

    __tablename__ = "record_versions"
    __table_args__ = (
        Index("ix_record_versions_entity", "entity_type", "entity_id", "version"),
        Index("ix_record_versions_tenant_time", "tenant_id", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="insert | update | delete | merge"
    )
    snapshot: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    diff: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    change_reason: Mapped[str | None] = mapped_column(String(500))
    ai_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    schema_version: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
