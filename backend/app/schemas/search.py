"""Search request and response models."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.search import SORT_OPTIONS


class SearchRequest(BaseModel):
    """Full-text query plus every structured filter the dashboard exposes."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=500, description="Free-text search")

    # categorical
    countries: list[str] = Field(default_factory=list, description="Vendor country, ISO alpha-2")
    countries_of_origin: list[str] = Field(default_factory=list)
    vendor_ids: list[uuid.UUID] = Field(default_factory=list)
    vendor_name: str | None = None
    pump_types: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    service_application: str | None = None
    certifications: list[str] = Field(default_factory=list)
    area_classifications: list[str] = Field(default_factory=list)
    seal_system_types: list[str] = Field(default_factory=list)
    driver_types: list[str] = Field(default_factory=list)
    material_classes: list[str] = Field(default_factory=list)
    incoterms: list[str] = Field(default_factory=list)
    vendor_approval_statuses: list[str] = Field(default_factory=list)
    vendor_tiers: list[str] = Field(default_factory=list)

    # operating conditions and numeric ranges
    capacity_min: Decimal | None = Field(default=None, description="m3/h")
    capacity_max: Decimal | None = Field(default=None, description="m3/h")
    head_min: Decimal | None = Field(default=None, description="m")
    head_max: Decimal | None = Field(default=None, description="m")
    npshr_max: Decimal | None = Field(default=None, description="m")
    efficiency_min: Decimal | None = Field(default=None, description="%")
    speed_min: int | None = None
    speed_max: int | None = None
    power_min: Decimal | None = Field(default=None, description="kW")
    power_max: Decimal | None = Field(default=None, description="kW")
    temperature_max: Decimal | None = Field(default=None, description="degC")
    design_pressure_min: Decimal | None = Field(default=None, description="barg")
    price_min: Decimal | None = Field(default=None, description="USD")
    price_max: Decimal | None = Field(default=None, description="USD")
    lead_time_max: Decimal | None = Field(default=None, description="weeks")
    weight_max: Decimal | None = Field(default=None, description="kg dry")
    footprint_max: Decimal | None = Field(default=None, description="m2")
    otd_min: Decimal | None = Field(default=None, description="0-1 on-time delivery ratio")
    completeness_min: Decimal | None = Field(default=None, description="0-1 data completeness")

    # quality and flags
    fpso_experience: bool | None = None
    nace_compliant: bool | None = None
    confidence_levels: list[str] = Field(default_factory=list)
    verification_statuses: list[str] = Field(default_factory=list)
    max_open_flags: int | None = Field(default=None, ge=0)
    include_shared_master: bool = True
    only_shared_master: bool = False

    # paging and ordering
    sort: str = Field(default="relevance", description=f"One of: {', '.join(sorted(SORT_OPTIONS))}")
    limit: int = Field(default=25, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    include_facets: bool = False


class SearchResultRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    pump_model_id: str
    pump_id: str
    vendor_id: str
    label: str
    vendor_name: str
    pump_name: str
    model_code: str


class FacetValue(BaseModel):
    value: str | None
    count: int


class SearchResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    sort: str
    facets: dict[str, list[FacetValue]] = Field(default_factory=dict)
    took_ms: int | None = None


class SimilarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=50)
    duty_tolerance_pct: Decimal = Field(
        default=Decimal("25"),
        ge=Decimal("1"),
        le=Decimal("100"),
        description="How far a duty point may deviate and still be considered similar",
    )
