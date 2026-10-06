"""Tenant management payloads."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.common import ORMModel


class TenantOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    legal_name: str | None = None
    country: str | None = None
    industry_segment: str | None = None
    status: str
    plan: str
    contract_start: date | None = None
    contract_end: date | None = None
    can_use_shared_master: bool
    can_contribute_shared_master: bool
    max_users: int
    max_ai_jobs_per_day: int
    max_storage_mb: int
    data_retention_days: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    primary_contact_email: str | None = None
    created_at: Any = None


class TenantStats(TenantOut):
    user_count: int = 0
    vendor_count: int = 0
    pump_model_count: int = 0
    source_count: int = 0
    ai_jobs_last_30d: int = 0
    storage_used_mb: float = 0.0
    open_flag_count: int = 0


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    name: str = Field(min_length=2, max_length=255)
    legal_name: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    industry_segment: str | None = None
    plan: str = "trial"
    primary_contact_email: EmailStr | None = None
    can_use_shared_master: bool = True
    can_contribute_shared_master: bool = False
    max_users: int = Field(default=25, ge=1, le=10_000)
    admin_email: EmailStr | None = Field(
        default=None, description="Creates the first tenant administrator"
    )
    admin_full_name: str | None = None
    admin_password: str | None = Field(default=None, min_length=12)

    @field_validator("country")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def _admin_fields_together(self):
        provided = [self.admin_email, self.admin_full_name, self.admin_password]
        if any(provided) and not all(provided):
            raise ValueError(
                "admin_email, admin_full_name and admin_password must be supplied together"
            )
        return self


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    legal_name: str | None = None
    country: str | None = None
    industry_segment: str | None = None
    status: str | None = None
    plan: str | None = None
    contract_start: date | None = None
    contract_end: date | None = None
    can_use_shared_master: bool | None = None
    can_contribute_shared_master: bool | None = None
    max_users: int | None = None
    max_ai_jobs_per_day: int | None = None
    max_storage_mb: int | None = None
    data_retention_days: int | None = None
    settings: dict[str, Any] | None = None
    primary_contact_email: EmailStr | None = None
    notes: str | None = None


class TenantPermissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str = Field(max_length=64)
    action: str = Field(default="read", max_length=32)
    granted: bool = True
    shared_with_tenant_id: uuid.UUID | None = Field(
        default=None, description="Grant another tenant access to this tenant's data"
    )
    constraints: dict[str, Any] = Field(default_factory=dict)


class TenantPermissionOut(ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    resource: str
    action: str
    granted: bool
    shared_with_tenant_id: uuid.UUID | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    expires_at: Any = None
