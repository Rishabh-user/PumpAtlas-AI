"""Field-level provenance.

Single entry point for writing intelligence values: ``apply_field``. It sets the
attribute, records a ``field_provenance`` row and returns whether anything changed.
Services must not assign spec attributes directly - going through here is what
guarantees the platform can answer "where did this number come from?" for every field.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ai import FieldProvenance
from app.models.enums import ConfidenceLevel, ValueOrigin
from app.services import vocabulary

log = get_logger(__name__)

# AI may not write a field without evidence unless the origin is a pure calculation.
EVIDENCE_REQUIRED_ORIGINS = {
    ValueOrigin.AI_EXTRACTION,
    ValueOrigin.AI_NORMALIZATION,
    ValueOrigin.AI_INFERENCE,
}


class ProvenanceError(ValueError):
    """Raised when a write would leave an AI-derived value untraceable."""


class TypeMismatchError(ProvenanceError):
    """The value cannot be stored in the column it was aimed at."""


class VocabularyError(ProvenanceError):
    """Raised when a value cannot be mapped onto a controlled vocabulary.

    A subclass of ProvenanceError so bulk writes already report it as a refused field
    rather than failing the whole batch.
    """


@dataclass
class ProvenanceContext:
    """Everything needed to justify a write."""

    origin: ValueOrigin
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    confidence_score: float | Decimal | None = None
    source_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    ai_job_id: uuid.UUID | None = None
    extracted_entity_id: uuid.UUID | None = None
    model_used: str | None = None
    changed_by_user_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    normalization_note: str | None = None

    @property
    def requires_evidence(self) -> bool:
        return self.origin in EVIDENCE_REQUIRED_ORIGINS


def missing_evidence_reason(field_name: str) -> str:
    """Why an unevidenced AI value is refused.

    Exposed because a caller writing a whole group of fields needs to know which of them
    will be refused *before* it opens a version row for them, and the two answers must be
    the same sentence.
    """
    return (
        f"AI-derived value for {field_name!r} has no evidence quote; refusing to "
        "write an untraceable value"
    )


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return str(value)
    return str(value)


def apply_field(
    db: Session,
    entity: Any,
    field_name: str,
    value: Any,
    context: ProvenanceContext,
    *,
    evidence_quote: str | None = None,
    evidence_locator: str | None = None,
    original_value: str | None = None,
    original_unit: str | None = None,
    overwrite_verified: bool = False,
    record_unchanged: bool = False,
) -> bool:
    """Write one field with provenance. Returns True if the stored value changed.

    ``overwrite_verified`` guards the most common data-integrity failure in a platform
    like this: a fresh crawl silently overwriting a human-verified figure. AI writes are
    refused against a verified field unless a human explicitly allows it.

    ``record_unchanged`` records provenance even when the column already holds the value.
    A record's identity fields have to be set when the row is created - a vendor cannot
    be inserted without a name - which would otherwise leave the most important AI-derived
    value on the record as the one value with no traceable source.
    """
    if not hasattr(entity, field_name):
        raise ProvenanceError(f"{entity.__class__.__name__} has no field {field_name!r}")

    if context.requires_evidence and not evidence_quote:
        raise ProvenanceError(missing_evidence_reason(field_name))

    # Enum columns are native PostgreSQL types: an unrecognised value does not fail
    # gracefully, it raises LookupError and aborts the whole transaction. Coerce what can
    # be coerced, and divert what cannot to the *_raw companion column.
    allowed = vocabulary.enum_values_for(entity, field_name)
    if allowed is not None:
        coerced, refusal = vocabulary.coerce_enum(value, allowed)
        if coerced is None:
            raw_column = vocabulary.raw_column_for(entity, field_name)
            if raw_column is not None and value is not None:
                setattr(entity, raw_column, str(value)[:255])
                log.info(
                    "provenance.enum_diverted_to_raw",
                    entity=entity.__tablename__,
                    field=field_name,
                    raw_column=raw_column,
                    reason=refusal,
                )
            else:
                log.info(
                    "provenance.enum_refused",
                    entity=entity.__tablename__,
                    field=field_name,
                    reason=refusal,
                )
            raise VocabularyError(refusal or f"{value!r} is not a valid {field_name}")
        if coerced != value:
            log.info(
                "provenance.enum_coerced",
                entity=entity.__tablename__,
                field=field_name,
                supplied=str(value)[:60],
                stored=coerced,
            )
        value = coerced

    # Enum columns are handled above. Every other column still has a type the model
    # can miss: a sentence aimed at a boolean, a scalar aimed at an array, a country
    # name aimed at a 2-character code. Refuse those with a reason rather than let the
    # flush raise and abort an otherwise good write.
    coerced, type_refusal = vocabulary.coerce_for_column(entity, field_name, value)
    if type_refusal is not None:
        log.info(
            "provenance.type_refused",
            entity=entity.__tablename__,
            field=field_name,
            reason=type_refusal,
        )
        raise TypeMismatchError(type_refusal)
    value = coerced

    current = getattr(entity, field_name)
    unchanged = _as_text(current) == _as_text(value)
    if unchanged and not record_unchanged:
        return False

    if (
        not overwrite_verified
        and context.origin in EVIDENCE_REQUIRED_ORIGINS
        and current is not None
        and _is_verified_field(db, entity, field_name)
    ):
        log.info(
            "provenance.refused_overwrite_of_verified",
            entity=entity.__tablename__,
            field=field_name,
        )
        return False

    setattr(entity, field_name, value)
    db.add(
        FieldProvenance(
            tenant_id=context.tenant_id or getattr(entity, "tenant_id", None),
            entity_type=entity.__tablename__,
            entity_id=entity.id,
            field_name=field_name,
            value_text=_as_text(value),
            previous_value_text=None if unchanged else _as_text(current),
            value_origin=context.origin,
            confidence_level=context.confidence_level,
            confidence_score=(
                Decimal(str(context.confidence_score))
                if context.confidence_score is not None
                else None
            ),
            source_id=context.source_id,
            document_id=context.document_id,
            ai_job_id=context.ai_job_id,
            extracted_entity_id=context.extracted_entity_id,
            model_used=context.model_used,
            evidence_quote=(evidence_quote or "")[:4000] or None,
            evidence_locator=evidence_locator,
            original_value=(original_value or "")[:500] or None,
            original_unit=original_unit,
            normalization_note=context.normalization_note,
            changed_by_user_id=context.changed_by_user_id,
            is_current=True,
        )
    )
    return not unchanged


def _is_verified_field(db: Session, entity: Any, field_name: str) -> bool:
    row = db.scalar(
        select(FieldProvenance.confidence_level).where(
            FieldProvenance.entity_type == entity.__tablename__,
            FieldProvenance.entity_id == entity.id,
            FieldProvenance.field_name == field_name,
            FieldProvenance.is_current.is_(True),
        )
    )
    return row == ConfidenceLevel.VERIFIED


def apply_fields(
    db: Session,
    entity: Any,
    values: dict[str, Any],
    context: ProvenanceContext,
    *,
    evidence: dict[str, str] | None = None,
    confidences: dict[str, float] | None = None,
    source_units: dict[str, str] | None = None,
    skip_unknown: bool = True,
) -> dict[str, Any]:
    """Bulk apply. Returns a report of applied, unchanged and refused fields."""
    evidence = evidence or {}
    confidences = confidences or {}
    source_units = source_units or {}
    applied: list[str] = []
    unchanged: list[str] = []
    refused: dict[str, str] = {}

    for field_name, value in values.items():
        if value is None:
            continue
        if not hasattr(entity, field_name):
            if skip_unknown:
                refused[field_name] = "unknown field"
                continue
            raise ProvenanceError(f"unknown field {field_name!r}")

        field_context = ProvenanceContext(
            origin=context.origin,
            confidence_level=context.confidence_level,
            confidence_score=confidences.get(field_name, context.confidence_score),
            source_id=context.source_id,
            document_id=context.document_id,
            ai_job_id=context.ai_job_id,
            extracted_entity_id=context.extracted_entity_id,
            model_used=context.model_used,
            changed_by_user_id=context.changed_by_user_id,
            tenant_id=context.tenant_id,
            normalization_note=context.normalization_note,
        )
        try:
            changed = apply_field(
                db,
                entity,
                field_name,
                value,
                field_context,
                evidence_quote=evidence.get(field_name),
                original_value=source_units.get(field_name),
            )
        except ProvenanceError as exc:
            refused[field_name] = str(exc)
            continue
        (applied if changed else unchanged).append(field_name)

    return {"applied": applied, "unchanged": unchanged, "refused": refused}


def field_history(
    db: Session, entity_type: str, entity_id: uuid.UUID, field_name: str | None = None
) -> list[FieldProvenance]:
    query = select(FieldProvenance).where(
        FieldProvenance.entity_type == entity_type, FieldProvenance.entity_id == entity_id
    )
    if field_name:
        query = query.where(FieldProvenance.field_name == field_name)
    return list(db.scalars(query.order_by(FieldProvenance.created_at.desc())).all())


def coverage(db: Session, entity_type: str, entity_id: uuid.UUID) -> dict[str, Any]:
    """Count current fields by origin - feeds the "how much of this is AI?" widget."""
    rows = db.execute(
        select(FieldProvenance.value_origin, FieldProvenance.confidence_level).where(
            FieldProvenance.entity_type == entity_type,
            FieldProvenance.entity_id == entity_id,
            FieldProvenance.is_current.is_(True),
        )
    ).all()
    by_origin: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    for origin, confidence in rows:
        by_origin[str(origin)] = by_origin.get(str(origin), 0) + 1
        by_confidence[str(confidence)] = by_confidence.get(str(confidence), 0) + 1
    return {"total": len(rows), "by_origin": by_origin, "by_confidence": by_confidence}
