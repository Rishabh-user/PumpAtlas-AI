"""Authentication and identity payloads."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str


class RoleOut(ORMModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: str | None = None
    is_platform_role: bool
    permissions: dict = Field(default_factory=dict)


class UserOut(ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    email: EmailStr
    full_name: str
    job_title: str | None = None
    is_active: bool
    is_platform_admin: bool
    mfa_enabled: bool
    roles: list[RoleOut] = Field(default_factory=list)


class CurrentUser(UserOut):
    tenant_name: str | None = None
    tenant_slug: str | None = None
    permissions: dict[str, list[str]] = Field(default_factory=dict)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    job_title: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["client_user"])
    tenant_id: uuid.UUID | None = Field(
        default=None, description="Platform admins only; otherwise the caller's tenant"
    )
    is_platform_admin: bool = False


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    job_title: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    scopes: list[str] = Field(
        default_factory=list,
        description='Resource:action pairs, e.g. ["search:read", "vendor:read"]',
    )
    expires_in_days: int | None = Field(default=365, ge=1, le=3650)


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str] = Field(default_factory=list)
    is_active: bool


class ApiKeyCreated(ApiKeyOut):
    api_key: str = Field(description="Shown once; only a hash is stored")
