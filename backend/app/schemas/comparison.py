"""Requirement profiles and comparison payloads."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ORMModel


class RequirementProfileIn(BaseModel):
    """The buyer's duty point and acceptance criteria - what "fit" is measured against."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    project_name: str | None = None
    tag_number: str | None = None
    required_capacity_m3h: Decimal | None = None
    required_head_m: Decimal | None = None
    max_npshr_m: Decimal | None = None
    min_efficiency_pct: Decimal | None = None
    fluid: str | None = None
    fluid_temperature_c: Decimal | None = None
    fluid_specific_gravity: Decimal | None = None
    required_standard: str | None = None
    required_pump_types: list[str] = Field(default_factory=list)
    required_area_classification: str | None = None
    required_certifications: list[str] = Field(default_factory=list)
    required_material_class: str | None = None
    nace_required: bool | None = None
    max_lead_time_weeks: Decimal | None = None
    max_budget_usd: Decimal | None = None
    max_dry_weight_kg: Decimal | None = None
    max_footprint_m2: Decimal | None = None
    excluded_countries: list[str] = Field(default_factory=list)
    local_content_min_pct: Decimal | None = None
    weight_technical: Decimal = Decimal("0.40")
    weight_commercial: Decimal = Decimal("0.25")
    weight_delivery: Decimal = Decimal("0.20")
    weight_data_confidence: Decimal = Decimal("0.15")
    is_active: bool = True

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = (
            self.weight_technical
            + self.weight_commercial
            + self.weight_delivery
            + self.weight_data_confidence
        )
        if abs(total - Decimal(1)) > Decimal("0.001"):
            raise ValueError(f"Scorecard weights must sum to 1.0, got {total}")
        return self


class RequirementProfileOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True, extra="allow")

    id: uuid.UUID
    name: str
    description: str | None = None
    project_name: str | None = None
    is_active: bool = True
    created_at: Any = None


class ComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    requirement_profile_id: uuid.UUID | None = None
    comparison_kind: str = Field(default="pump_model", description="pump_model | vendor")
    pump_model_ids: list[uuid.UUID] = Field(default_factory=list, max_length=12)
    vendor_ids: list[uuid.UUID] = Field(default_factory=list, max_length=12)
    fields_shown: list[str] = Field(default_factory=list)
    generate_narrative: bool = Field(
        default=False, description="Have Gemma draft the decision narrative"
    )

    @model_validator(mode="after")
    def _needs_subjects(self):
        if not self.pump_model_ids and not self.vendor_ids:
            raise ValueError("Provide at least one pump_model_id or vendor_id to compare")
        return self


class ComparisonItemOut(ORMModel):
    id: uuid.UUID
    pump_model_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    position: int
    label: str | None = None
    technical_score: float | None = None
    commercial_score: float | None = None
    delivery_risk_score: float | None = None
    data_confidence_score: float | None = None
    overall_score: float | None = None
    rank: int | None = None
    disqualified: bool = False
    disqualification_reason: str | None = None
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)


class ComparisonOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    comparison_kind: str
    requirement_profile_id: uuid.UUID | None = None
    status: str
    recommendation: str | None = None
    ai_narrative: str | None = None
    fields_shown: list[str] = Field(default_factory=list)
    items: list[ComparisonItemOut] = Field(default_factory=list)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: Any = None


class VendorComparisonRow(BaseModel):
    vendor_id: uuid.UUID
    vendor_name: str
    country: str | None = None
    vendor_tier: str | None = None
    approval_status: str | None = None
    sanctions_status: str | None = None
    pump_model_count: int = 0
    fpso_experience: bool | None = None
    on_time_delivery_pct: float | None = None
    total_units_supplied: int | None = None
    qaqc_certifications: list[str] = Field(default_factory=list)
    data_completeness_pct: float | None = None
    avg_lead_time_weeks: float | None = None
    min_price_usd: float | None = None
    scorecards: dict[str, Any] = Field(default_factory=dict)


class AuditLogOut(ORMModel):
    """Audit entry.

    ``ip_address`` is an INET column, which psycopg hands back as an
    ``IPv4Address``/``IPv6Address`` object. Coerced here rather than at each call site,
    so no route can forget and return a 500.
    """

    id: int
    occurred_at: Any = None
    action: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    entity_label: str | None = None
    user_id: uuid.UUID | None = None
    user_email: str | None = None
    actor_type: str
    summary: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    ip_address: str | None = None
    http_method: str | None = None
    http_path: str | None = None
    status_code: int | None = None

    @field_validator("ip_address", mode="before")
    @classmethod
    def _stringify_ip(cls, value: object) -> object:
        return None if value is None else str(value)


class RecordVersionOut(ORMModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    version: int
    operation: str
    diff: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    changed_by_user_id: uuid.UUID | None = None
    change_reason: str | None = None
    created_at: Any = None


class TagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = None
    color: str | None = Field(default=None, max_length=9)
    category: str | None = None


class TagOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None = None
    color: str | None = None
    category: str | None = None
    usage_count: int = 0


class TagAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(description="vendors | pumps | pump_models")
    entity_id: uuid.UUID
