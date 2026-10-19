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
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY as SAArray
from sqlalchemy import JSON as SAJson
from sqlalchemy import Enum as SAEnum
from sqlalchemy import String as SAString
from sqlalchemy import Text, and_, case, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models.pump import Pump, PumpModel
from app.models.vendor import Vendor, VendorContact
from app.schemas.specs import SPEC_FIELDS, SPEC_REGISTRY

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


def model_coverage(
    model: PumpModel, pump: Pump | None, specs: dict[str, Any]
) -> dict[str, dict[str, int]]:
    """Recorded and tracked field counts per group, rather than one number.

    One figure against 437 fields makes every record look broken. A good datasheet
    supplies around thirty fields and reads as 6% complete - while 60 commercial,
    52 delivery and 55 operational fields sit in the denominator waiting for data that
    only a quotation or a service history can provide. Measured against what a
    datasheet can actually answer, the same record is closer to a fifth of the way
    there, and the three empty groups say plainly that nobody has quoted it yet.

    Returns `{group: {"recorded": n, "tracked": m}}` with an `attributes` entry for the
    identity fields that belong to no spec group. The sum of `tracked` across every
    entry is `MODEL_TRACKED`, so the single percentage is still derivable from this.
    """
    coverage: dict[str, dict[str, int]] = {}

    attribute_recorded = sum(
        1 for name in MODEL_ATTRIBUTE_FIELDS if is_recorded(getattr(model, name, None))
    )
    if pump is not None:
        attribute_recorded += sum(
            1 for name in PUMP_ATTRIBUTE_FIELDS if is_recorded(getattr(pump, name, None))
        )
    coverage["attributes"] = {
        "recorded": attribute_recorded,
        "tracked": len(MODEL_ATTRIBUTE_FIELDS) + len(PUMP_ATTRIBUTE_FIELDS),
    }

    for group in SPEC_FIELDS:
        names = spec_field_names(group)
        spec = specs.get(group)
        recorded = (
            0
            if spec is None
            else sum(1 for name in names if is_recorded(getattr(spec, name, None)))
        )
        coverage[group] = {"recorded": recorded, "tracked": len(names)}
    return coverage


def _recorded_in_sql(column: Any) -> Any:
    """The SQL form of `is_recorded`, per column type.

    These two have to agree. The list page and the profile page showing different
    counts for the same record is the sort of thing nobody reports as a bug and
    everybody quietly stops trusting.
    """
    # Checked by type, not by the rendered name. `Enum` subclasses `String`, so a name
    # match sent `btrim()` at a Postgres enum column and the whole query failed with
    # "function btrim(driver_type) does not exist".
    if isinstance(column.type, SAArray):
        return func.coalesce(func.cardinality(column), 0) > 0
    if isinstance(column.type, SAEnum):
        # An enum cannot hold an empty string, so presence is the whole question.
        return column.is_not(None)
    if isinstance(column.type, SAString):
        return and_(column.is_not(None), func.btrim(column) != "")
    if isinstance(column.type, SAJson):
        # `is_recorded` calls an empty object or array empty, and these columns are
        # created as `{}` rather than left null, so IS NOT NULL counts every one of
        # them. `extra` on a technical spec row is the usual offender.
        return and_(
            column.is_not(None),
            cast(column, Text).notin_(("{}", "[]", "null")),
        )
    return column.is_not(None)


def coverage_for_models(
    db: Session, pump_model_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, dict[str, int]]]:
    """Per-group recorded counts for a page of models, in one round trip.

    The list page showed a single percentage against 437 tracked fields, so a
    well-documented pump read as 6% and sat indistinguishable from an empty row. Per
    group it is legible - and the six groups cannot be counted one model at a time,
    because that is 6 queries per row against a database 300ms away.

    A `UNION ALL` across the six spec tables, each counting its own recorded columns,
    answers the whole page at once. Groups with no current row are absent from the
    result and filled in as zero by the caller.
    """
    tracked = {group: len(spec_field_names(group)) for group in SPEC_FIELDS}
    base: dict[uuid.UUID, dict[str, dict[str, int]]] = {
        model_id: {g: {"recorded": 0, "tracked": n} for g, n in tracked.items()}
        for model_id in pump_model_ids
    }
    if not pump_model_ids:
        return base

    parts = []
    for group, (sa_model, _, _) in SPEC_REGISTRY.items():
        names = spec_field_names(group)
        if not names:
            continue
        recorded = sum(
            (
                case((_recorded_in_sql(getattr(sa_model, name)), 1), else_=0)
                for name in names
                if hasattr(sa_model, name)
            ),
            literal(0),
        )
        parts.append(
            select(
                sa_model.pump_model_id.label("pump_model_id"),
                literal(group).label("grp"),
                recorded.label("recorded"),
            ).where(
                sa_model.is_current.is_(True),
                sa_model.pump_model_id.in_(pump_model_ids),
            )
        )
    if not parts:
        return base

    for model_id, group, recorded in db.execute(union_all(*parts)):
        if model_id in base:
            base[model_id][group]["recorded"] = int(recorded or 0)
    return base


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
