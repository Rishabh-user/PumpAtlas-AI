"""Vendor, pump and pump-model request/response models."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.fields import FieldInfo

from app.models.enums import VendorApprovalStatus
from app.models.pump import Pump, PumpModel
from app.models.vendor import Vendor, VendorContact
from app.schemas.common import ORMModel
from app.schemas.derive import build_read_model, build_write_model

VendorOut = build_read_model(Vendor, "VendorOut")

# Not a column: how many *other* tenancies hold a vendor with this normalised name. The
# list sets it per page so a platform administrator can tell a genuine duplicate from the
# same company recorded once per client, which is how the tenancy model is supposed to
# work. Declared here because a field absent from the response model is silently dropped
# by FastAPI, whatever the route puts on the object.
VendorOut.model_fields["also_in_other_tenancies"] = FieldInfo(annotation=int, default=0)
VendorOut.model_rebuild(force=True)
VendorIn = build_write_model(Vendor, "VendorIn")
class QualificationDecision(BaseModel):
    """One person's decision about whether a supplier may be used.

    A decision needs a reason. `approval_status` is the field a buyer defends in a tender
    review - "why is this supplier approved" has to have an answer that is not "the
    website said so", which is exactly what the extractor used to write here.
    """

    approval_status: VendorApprovalStatus
    approval_expiry: date | None = Field(
        default=None,
        description="When this decision lapses and the supplier must be requalified",
    )
    note: str = Field(
        min_length=8,
        max_length=2000,
        description="Why. Stored as the evidence behind the status.",
    )


VendorContactOut = build_read_model(VendorContact, "VendorContactOut")
# `source_id`, `captured_at` and `origin` say where a contact came from, and only the
# capture path may set them. Leaving them writable would let a client post a contact
# labelled as read from a page it was never on - provenance that says nothing is worse
# than none.
VendorContactIn = build_write_model(
    VendorContact,
    "VendorContactIn",
    exclude={"vendor_id", "source_id", "captured_at", "origin"},
)

PumpOut = build_read_model(Pump, "PumpOut")
PumpIn = build_write_model(Pump, "PumpIn", include_system={"vendor_id"})

PumpModelOut = build_read_model(PumpModel, "PumpModelOut")
PumpModelIn = build_write_model(PumpModel, "PumpModelIn", include_system={"pump_id"})


class VendorCreate(BaseModel):
    """Minimum viable vendor. Everything else can be enriched later."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    website: str | None = None
    vendor_tier: str | None = None
    description: str | None = None
    is_shared_master: bool = Field(
        default=False, description="Platform admins only: publish as shared master data"
    )

    @field_validator("country")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class PumpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    pump_type: str | None = None
    applicable_standard: str | None = None
    service_application: str | None = None
    product_family: str | None = None
    description: str | None = None


class PumpModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pump_id: uuid.UUID
    model_code: str = Field(min_length=1, max_length=160)
    size_designation: str | None = None
    stages: int | None = Field(default=None, ge=1, le=40)
    orientation: str | None = None
    tag_number: str | None = None
    project_reference: str | None = None


class PumpProfile(ORMModel):
    """Everything the pump profile page renders in one response."""

    pump_model: dict[str, Any]
    pump: dict[str, Any]
    vendor: dict[str, Any]
    specs: dict[str, Any] = Field(
        default_factory=dict, description="Current version of each spec group"
    )
    scorecards: list[dict[str, Any]] = Field(default_factory=list)
    open_flags: list[dict[str, Any]] = Field(default_factory=list)
    provenance_summary: dict[str, Any] = Field(default_factory=dict)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    similar: list[dict[str, Any]] = Field(default_factory=list)
