"""Generated request/response models for the six spec tables."""

from __future__ import annotations

from app.models.specs import (
    AdministrativeSpec,
    CommercialSpec,
    DeliverySpec,
    DimensionalSpec,
    OperationalSpec,
    TechnicalSpec,
)
from app.schemas.derive import build_read_model, build_write_model, writable_field_names

TechnicalSpecOut = build_read_model(TechnicalSpec, "TechnicalSpecOut")
TechnicalSpecIn = build_write_model(TechnicalSpec, "TechnicalSpecIn")

CommercialSpecOut = build_read_model(CommercialSpec, "CommercialSpecOut")
CommercialSpecIn = build_write_model(CommercialSpec, "CommercialSpecIn")

DimensionalSpecOut = build_read_model(DimensionalSpec, "DimensionalSpecOut")
DimensionalSpecIn = build_write_model(DimensionalSpec, "DimensionalSpecIn")

DeliverySpecOut = build_read_model(DeliverySpec, "DeliverySpecOut")
DeliverySpecIn = build_write_model(DeliverySpec, "DeliverySpecIn")

OperationalSpecOut = build_read_model(OperationalSpec, "OperationalSpecOut")
OperationalSpecIn = build_write_model(OperationalSpec, "OperationalSpecIn")

AdministrativeSpecOut = build_read_model(AdministrativeSpec, "AdministrativeSpecOut")
AdministrativeSpecIn = build_write_model(AdministrativeSpec, "AdministrativeSpecIn")

# group name -> (SQLAlchemy model, read schema, write schema)
SPEC_REGISTRY: dict[str, tuple[type, type, type]] = {
    "technical": (TechnicalSpec, TechnicalSpecOut, TechnicalSpecIn),
    "commercial": (CommercialSpec, CommercialSpecOut, CommercialSpecIn),
    "dimensional": (DimensionalSpec, DimensionalSpecOut, DimensionalSpecIn),
    "delivery": (DeliverySpec, DeliverySpecOut, DeliverySpecIn),
    "operational": (OperationalSpec, OperationalSpecOut, OperationalSpecIn),
    "administrative": (AdministrativeSpec, AdministrativeSpecOut, AdministrativeSpecIn),
}

SPEC_FIELDS: dict[str, list[str]] = {
    group: writable_field_names(sa_model) for group, (sa_model, _, _) in SPEC_REGISTRY.items()
}

ALL_TRACKED_FIELDS: list[str] = sorted(
    {field for fields in SPEC_FIELDS.values() for field in fields}
)
