"""Declarative base and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDelete:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class TenantScoped:
    """Adds ``tenant_id`` and the index every tenant-filtered query relies on.

    ``tenant_id IS NULL`` means *shared master data*: readable by every tenant that has
    ``can_use_shared_master`` enabled, writable only by platform admins.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        )


class Versioned:
    """Row-level version history support for spec tables."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schema_version: Mapped[str] = mapped_column(
        # Bumped whenever the meaning of a field changes; lets readers interpret old rows.
        nullable=False,
        default="1.0.0",
        server_default="1.0.0",
    )
