"""Users, roles and API keys."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey
from app.models.enums import UserRoleName
from app.models.types import Json, pg_enum

if TYPE_CHECKING:
    from app.models.tenant import Tenant

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Role(UUIDPrimaryKey, Timestamps, Base):
    """System roles. Seeded once; permissions live in ``permissions`` JSONB."""

    __tablename__ = "roles"

    name: Mapped[UserRoleName] = mapped_column(
        pg_enum(UserRoleName, "user_role_name"), nullable=False, unique=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_platform_role: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Role operates across all tenants"
    )
    # {"vendors": ["read","write"], "pumps": ["read"], ...}
    permissions: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        Index("ix_users_tenant_active", "tenant_id", "is_active"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL for Targeticon platform staff",
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(160))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Can administer every tenant"
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    tenant: Mapped[Tenant | None] = relationship(back_populates="users")
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )

    @property
    def role_names(self) -> list[str]:
        return [r.name.value for r in self.roles]

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class ApiKey(UUIDPrimaryKey, Timestamps, Base):
    """Machine credentials for the API-first integrations."""

    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    hashed_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
