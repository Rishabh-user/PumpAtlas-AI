"""How much of a record is actually filled in.

`data_completeness_pct` is on `vendors`, on `pump_models` and on `search_index`; the
quality dashboard averages it, search sorts by it and `completeness_min` filters on it.
Nothing ever computed it. Every row held NULL - 0 of 77 vendors, 0 of 84 pump models -
so the dashboard reported nothing, the sort was a no-op and the filter could not match.
This is the missing half.

What it measures, deliberately narrow: **of the fields this platform tracks for a record
of this kind, how many hold a value.** Not quality, not confidence - those are
`confidence_level` and `verification_status`, and conflating them would let a record
full of guesses read as complete.

The field lists are the ones the profile page and the chat answer already count, so a
record that reads "8 of 46 recorded" on screen does not also claim 60% here.

Empty is empty: `None`, `""`, `[]` and `{}` all count as absent, because an unpopulated
JSON column comes back as `{}` and an untouched array as `[]`, and counting those as
filled is how a blank record ends up looking finished.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.pump import Pump, PumpModel
from app.models.vendor import Vendor, VendorContact
from app.schemas.specs import SPEC_FIELDS

#: Columns that describe the row rather than the thing. Mirrors `chat.ROW_META_COLUMNS`:
#: a spec row's own confidence and notes are bookkeeping, and counting them would give
#: every record a few free points for having been written at all.
ROW_META_COLUMNS = frozenset(
    {
        "confidence_level",
        "verification_status",
        "data_submission_date",
        "signal_list",
        "notes",
    }
)

#: What a usable supplier profile holds. Columns only - `extra.discovery` is where
#: refused values go, and a refused value is precisely what has *not* been recorded.
#:
#: The financial and track-record fields are in here even though a company website
#: rarely states them. That is the point: a supplier with a website, a country and
#: nothing else is not a qualified supplier record, and a number that hides the gap
#: would be worse than no number.
VENDOR_FIELDS: tuple[str, ...] = (
    "website",
    "hq_country",
    "hq_city",
    "description",
    "vendor_tier",
    "product_families",
    "manufacturing_countries",
    "annual_revenue_usd",
    "employee_count",
    "credit_rating",
    "total_units_supplied",
    "on_time_delivery_pct",
    "fpso_offshore_experience",
)

#: A contact counts as one field. A supplier record nobody can telephone is incomplete
#: in the way that matters most to the person using it.
VENDOR_TRACKED = len(VENDOR_FIELDS) + 1

#: Identity of the specific model, and of the family it belongs to. Same tuples the
#: profile page groups under "Attributes".
MODEL_ATTRIBUTE_FIELDS: tuple[str, ...] = (
    "model_code",
    "size_designation",
    "frame_size",
    "stages",
    "orientation",
    "generation",
    "tag_number",
    "project_reference",
)
PUMP_ATTRIBUTE_FIELDS: tuple[str, ...] = (
    "product_family",
    "pump_type",
    "pump_type_raw",
    "applicable_standard",
    "standard_edition",
    "additional_standards",
    "service_application",
    "handled_fluids",
    "is_discontinued",
)


def is_recorded(value: Any) -> bool:
    """Whether a value is a value. Zero is; an empty JSON column is not."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list | dict | tuple | set):
        return len(value) > 0
    return True


def _ratio(recorded: int, tracked: int) -> Decimal | None:
    """Stored as a fraction of one, despite the column being named `_pct`.

    `Ratio` is `NUMERIC(5, 4)` - "0.0000 to 1.0000" - so 85% is 0.8500 and anything of
    the order of 85 overflows the column and aborts the transaction it was written in.
    Every consumer already agrees with the type rather than the name: the results table
    renders it through `ratioAsPct`, and the quality dashboard multiplies by 100 on the
    way out.
    """
    if tracked <= 0:
        return None
    return Decimal(str(round(recorded / tracked, 4)))


def spec_field_names(group: str) -> list[str]:
    """The fields of one spec group that count towards completeness."""
    return [name for name in SPEC_FIELDS.get(group, []) if name not in ROW_META_COLUMNS]


TRACKED_SPEC_FIELDS = sum(len(spec_field_names(group)) for group in SPEC_FIELDS)
MODEL_TRACKED = (
    TRACKED_SPEC_FIELDS + len(MODEL_ATTRIBUTE_FIELDS) + len(PUMP_ATTRIBUTE_FIELDS)
)


def vendor_completeness(vendor: Vendor, *, contact_count: int) -> Decimal | None:
    """What share of a supplier profile this record holds, as a fraction of one.

    `vendor_tier` counts only when it says something: every vendor has a tier, and the
    default is `unclassified`, which is the absence of a classification wearing a value's
    clothes.
    """
    recorded = 0
    for name in VENDOR_FIELDS:
        value = getattr(vendor, name, None)
        if name == "vendor_tier":
            tier = getattr(value, "value", value)
            if tier and tier != "unclassified":
                recorded += 1
            continue
        if is_recorded(value):
            recorded += 1
    if contact_count > 0:
        recorded += 1
    return _ratio(recorded, VENDOR_TRACKED)


def contact_counts(db: Session, vendor_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many contacts each vendor holds, in one query.

    Counted, never loaded: `vendor_contacts` carries columns the database may not have
    yet (see `vendor_discovery.contact_rows`), and a count asks for none of them.
    """
    if not vendor_ids:
        return {}
    rows = db.execute(
        select(VendorContact.vendor_id, func.count())
        .where(VendorContact.vendor_id.in_(vendor_ids))
        .group_by(VendorContact.vendor_id)
    ).all()
    return dict(rows)


def refresh_vendor(db: Session, vendor: Vendor) -> Decimal | None:
    """Recompute and store a vendor's completeness. Returns the new value."""
    contacts = contact_counts(db, [vendor.id]).get(vendor.id, 0)
    value = vendor_completeness(vendor, contact_count=contacts)
    vendor.data_completeness_pct = value
    return value


def model_completeness(
    model: PumpModel, pump: Pump | None, specs: dict[str, Any]
) -> Decimal | None:
    """What share of the tracked pump fields this model holds, as a fraction of one.

    `specs` is the current row of each group, as `records.current_specs` returns them -
    the caller has usually just loaded them, and loading them again would cost six
    queries against a database 300ms away.
    """
    recorded = sum(
        1 for name in MODEL_ATTRIBUTE_FIELDS if is_recorded(getattr(model, name, None))
    )
    if pump is not None:
        recorded += sum(
            1 for name in PUMP_ATTRIBUTE_FIELDS if is_recorded(getattr(pump, name, None))
        )
    for group in SPEC_FIELDS:
        spec = specs.get(group)
        if spec is None:
            continue
        recorded += sum(
            1 for name in spec_field_names(group) if is_recorded(getattr(spec, name, None))
        )
    return _ratio(recorded, MODEL_TRACKED)


def refresh_model(
    db: Session, model: PumpModel, pump: Pump | None, specs: dict[str, Any]
) -> Decimal | None:
    """Recompute and store a pump model's completeness."""
    value = model_completeness(model, pump, specs)
    model.data_completeness_pct = value
    return value


def vendor_gaps(vendor: Vendor, *, contact_count: int) -> list[str]:
    """The tracked vendor fields this record does not hold, for "what is missing"."""
    missing = []
    for name in VENDOR_FIELDS:
        value = getattr(vendor, name, None)
        if name == "vendor_tier":
            tier = getattr(value, "value", value)
            if not tier or tier == "unclassified":
                missing.append(name)
            continue
        if not is_recorded(value):
            missing.append(name)
    if contact_count == 0:
        missing.append("contacts")
    return missing


def refresh_vendors(db: Session, vendors: list[Vendor]) -> dict[uuid.UUID, Decimal | None]:
    """Recompute a whole list of vendors on one contact query rather than one each."""
    counts = contact_counts(db, [vendor.id for vendor in vendors])
    out: dict[uuid.UUID, Decimal | None] = {}
    for vendor in vendors:
        value = vendor_completeness(vendor, contact_count=counts.get(vendor.id, 0))
        vendor.data_completeness_pct = value
        out[vendor.id] = value
    return out
