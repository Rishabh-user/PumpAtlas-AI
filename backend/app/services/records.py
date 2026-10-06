"""Read helpers that assemble a pump model's full intelligence record.

Scoring, quality checks and the comparison view all need the same thing: one flat dict
holding the current value of every field across the six spec tables plus vendor and
pump context. Building it in one place keeps those three consumers consistent.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.ai import DataQualityFlag, FieldProvenance
from app.models.enums import ValueOrigin
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.models.specs import (
    AdministrativeSpec,
    CommercialSpec,
    DeliverySpec,
    DimensionalSpec,
    OperationalSpec,
    TechnicalSpec,
)
from app.models.vendor import Vendor
from app.services.indexing import collect_certifications

SPEC_CLASSES = {
    "technical": TechnicalSpec,
    "commercial": CommercialSpec,
    "dimensional": DimensionalSpec,
    "delivery": DeliverySpec,
    "operational": OperationalSpec,
    "administrative": AdministrativeSpec,
}

# Columns that describe the row rather than the pump; excluded from flattened records.
META_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "pump_model_id",
        "created_at",
        "updated_at",
        "version",
        "is_current",
        "superseded_at",
        "schema_version",
        "source_id",
        "ai_job_id",
        "created_by_user_id",
        "source_units",
        "extra",
    }
)


def current_specs(db: Session, pump_model_id: uuid.UUID) -> dict[str, Any]:
    """The current version of each spec group, keyed by group name."""
    out: dict[str, Any] = {}
    for group, spec_cls in SPEC_CLASSES.items():
        out[group] = db.scalar(
            select(spec_cls)
            .where(spec_cls.pump_model_id == pump_model_id, spec_cls.is_current.is_(True))
            .order_by(spec_cls.version.desc())
            .limit(1)
        )
    return out


def current_specs_bulk(
    db: Session, pump_model_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """The current spec rows for many models: six queries, not six per model.

    :func:`current_specs` is one query per group, which is right for a single profile
    page and wrong for a list: eight records is 48 round trips, and against a hosted
    database at roughly a third of a second each that is fifteen seconds of waiting
    before anything renders. Here the group is the query and the models are the
    predicate, so the cost is flat in the number of records.
    """
    ids = list(pump_model_ids)
    out: dict[uuid.UUID, dict[str, Any]] = {
        model_id: {group: None for group in SPEC_CLASSES} for model_id in ids
    }
    if not ids:
        return out

    for group, spec_cls in SPEC_CLASSES.items():
        rows = db.scalars(
            select(spec_cls).where(spec_cls.pump_model_id.in_(ids), spec_cls.is_current.is_(True))
        ).all()
        for row in rows:
            held = out.get(row.pump_model_id)
            if held is None:
                continue
            # At most one row per group should be current. If a bad write ever left two,
            # take the later version - the same tie-break `current_specs` makes with its
            # `order_by(version.desc())`.
            existing = held[group]
            if existing is None or (row.version or 0) > (existing.version or 0):
                held[group] = row
    return out


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value
    return value


def _columns_to_dict(obj: Any, skip: frozenset[str] = META_COLUMNS) -> dict[str, Any]:
    if obj is None:
        return {}
    return {
        column.name: getattr(obj, column.name)
        for column in obj.__table__.columns
        if column.name not in skip
    }


def spec_values(spec: Any) -> dict[str, Any]:
    """One spec row as jsonable field values, without the bookkeeping columns."""
    return to_jsonable(_columns_to_dict(spec))


def flatten_pump_model(
    db: Session, pump_model_id: uuid.UUID, specs: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One flat record: vendor + pump + pump model + all current spec values.

    Later groups do not overwrite earlier ones, so a name collision between spec tables
    keeps the more specific (technical) value. Enum values are rendered as plain strings
    so scoring and quality code never has to import the enum classes.
    """
    model = db.get(PumpModel, pump_model_id)
    if model is None:
        return {}
    pump = db.get(Pump, model.pump_id)
    vendor = db.get(Vendor, pump.vendor_id) if pump else None
    if specs is None:
        specs = current_specs(db, pump_model_id)

    record: dict[str, Any] = {}
    for group in SPEC_CLASSES:
        for key, value in _columns_to_dict(specs.get(group)).items():
            record.setdefault(key, value)

    record.update(
        {
            "pump_model_id": str(model.id),
            "model_code": model.model_code,
            "size_designation": model.size_designation,
            "stages": model.stages,
            "orientation": model.orientation,
            "tag_number": model.tag_number,
            "confidence_level": _plain(model.confidence_level),
            "verification_status": _plain(model.verification_status),
            "data_completeness_pct": model.data_completeness_pct,
        }
    )
    if pump is not None:
        record.update(
            {
                "pump_id": str(pump.id),
                "pump_name": pump.name,
                "product_family": pump.product_family,
                "pump_type": _plain(pump.pump_type),
                "applicable_standard": _plain(pump.applicable_standard),
                "standard_edition": pump.standard_edition,
                "service_application": pump.service_application,
                "handled_fluids": pump.handled_fluids,
            }
        )
    if vendor is not None:
        record.update(
            {
                "vendor_id": str(vendor.id),
                "vendor_name": vendor.name,
                "vendor_country": vendor.country or vendor.hq_country,
                "vendor_tier": _plain(vendor.vendor_tier),
                "vendor_approval_status": _plain(vendor.approval_status),
                "sanctions_status": _plain(vendor.sanctions_status),
                "vendor_on_time_delivery_pct": vendor.on_time_delivery_pct,
                "vendor_fpso_experience": vendor.fpso_offshore_experience,
            }
        )

    record["certifications"] = collect_certifications(
        specs.get("technical"), specs.get("operational")
    )
    record["open_flag_count"] = (
        db.scalar(
            select(func.count())
            .select_from(DataQualityFlag)
            .where(
                DataQualityFlag.entity_id == pump_model_id,
                DataQualityFlag.is_resolved.is_(False),
            )
        )
        or 0
    )

    return {key: _plain(value) for key, value in record.items()}


def provenance_targets_for_pump_model(
    db: Session,
    pump_model_id: uuid.UUID,
    specs: dict[str, Any] | None = None,
) -> list[tuple[str, uuid.UUID]]:
    """Every row that holds a field belonging to one pump model.

    A pump model's intelligence is spread across its own row, its product line and the
    current version of six spec tables. Summarising provenance for the pump_models row
    alone reports almost nothing, because that is not where the fields live.
    """
    targets: list[tuple[str, uuid.UUID]] = [("pump_models", pump_model_id)]
    model = db.get(PumpModel, pump_model_id)
    if model is not None:
        targets.append(("pumps", model.pump_id))

    if specs is not None:
        # Reuse rows the caller already loaded rather than issuing six more queries.
        for group, spec in specs.items():
            if spec is not None:
                targets.append((SPEC_CLASSES[group].__tablename__, spec.id))
        return targets

    for spec_cls in SPEC_CLASSES.values():
        spec_id = db.scalar(
            select(spec_cls.id).where(
                spec_cls.pump_model_id == pump_model_id, spec_cls.is_current.is_(True)
            )
        )
        if spec_id is not None:
            targets.append((spec_cls.__tablename__, spec_id))
    return targets


def provenance_summary(db: Session, targets: Sequence[tuple[str, uuid.UUID]]) -> dict[str, Any]:
    """How much of a record is AI-derived, and how much a human has verified.

    ``targets`` is a list of ``(entity_type, entity_id)`` pairs, so a summary can span
    the several rows that together make up one logical record.
    """
    if not targets:
        return {
            "total_fields_with_provenance": 0,
            "by_origin": {},
            "by_confidence": {},
            "ai_derived_fields": 0,
            "ai_share_pct": None,
        }

    match_any = or_(
        *[
            and_(FieldProvenance.entity_type == entity_type, FieldProvenance.entity_id == entity_id)
            for entity_type, entity_id in targets
        ]
    )
    rows = db.execute(
        select(
            FieldProvenance.value_origin,
            FieldProvenance.confidence_level,
            func.count().label("count"),
        )
        .where(match_any, FieldProvenance.is_current.is_(True))
        .group_by(FieldProvenance.value_origin, FieldProvenance.confidence_level)
    ).all()

    by_origin: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    ai_fields = 0
    total = 0
    ai_origins = {
        ValueOrigin.AI_EXTRACTION.value,
        ValueOrigin.AI_NORMALIZATION.value,
        ValueOrigin.AI_INFERENCE.value,
    }
    for origin, confidence, count in rows:
        origin_key = _plain(origin)
        confidence_key = _plain(confidence)
        by_origin[origin_key] = by_origin.get(origin_key, 0) + int(count)
        by_confidence[confidence_key] = by_confidence.get(confidence_key, 0) + int(count)
        total += int(count)
        if origin_key in ai_origins:
            ai_fields += int(count)

    return {
        "total_fields_with_provenance": total,
        "by_origin": by_origin,
        "by_confidence": by_confidence,
        "ai_derived_fields": ai_fields,
        "ai_share_pct": round(ai_fields / total * 100, 2) if total else None,
    }


def search_row(db: Session, pump_model_id: uuid.UUID) -> SearchIndex | None:
    return db.scalar(select(SearchIndex).where(SearchIndex.pump_model_id == pump_model_id))


def to_jsonable(value: Any) -> Any:
    """JSON-safe rendering for comparison snapshots and API payloads."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _plain(value)
