"""Recover specification values that promotion dropped before it was fixed.

`promote_extracted_entity` used to choose which spec tables to write by looking
`entity.entity_type` up in `SPEC_MODEL_BY_ENTITY`. The entity type both real flows
produce is "pump_model", which is not a key in that map, so no version row was opened
and every specification value in an accepted candidate was discarded. The records still
looked plausible - they kept their vendor and pump-level fields - and only the six empty
spec panels on the profile page gave it away.

Nothing was lost permanently: each `extracted_entities` row still holds its full
`payload->'fields'`, `field_confidences` and `evidence_spans`. This re-applies them
through `promotion.write_spec_groups`, the same function the live path now uses, so the
repaired values carry the same provenance, land in the same versioned rows and appear in
the audit trail the same way.

    python -m scripts.backfill_dropped_specs              # dry run, writes nothing
    python -m scripts.backfill_dropped_specs --commit     # apply

Two values are never written. A field with no evidence quote is refused exactly as the
live path refuses it - a recovered number nobody can trace back to a document is worth
less than the gap it fills. A field naming no column on any spec table is reported and
left alone rather than guessed onto the nearest-looking column, because "max_viscosity_cp"
and `fluid_viscosity_cst` are different units, not different spellings.

Safe to re-run: a field the current version already held when the run started is left
alone, so a second pass writes nothing and cannot overwrite work done since.
"""

from __future__ import annotations

import argparse
import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.db import SessionLocal, set_tenant_guc
from app.core.logging import get_logger
from app.models.ai import ExtractedEntity
from app.models.enums import ValueOrigin
from app.models.pump import Pump, PumpModel
from app.services import comparison, indexing, promotion, provenance
from app.services.promotion import (
    PUMP_FIELDS,
    PUMP_MODEL_FIELDS,
    SPEC_MODEL_BY_ENTITY,
    VENDOR_FIELDS,
)

log = get_logger(__name__)

IDENTITY_FIELDS = VENDOR_FIELDS | PUMP_FIELDS | PUMP_MODEL_FIELDS

CHANGE_REASON = "Backfill of specification values dropped by promotion defect"


def candidates_to_repair(db: Session) -> list[ExtractedEntity]:
    """Accepted candidates that were promoted to a pump model, oldest first.

    ``target_type == "pump_model"`` is what identifies a damaged promotion. A candidate
    promoted since the fix has the spec table it landed in recorded there instead, and
    its ``target_id`` is a spec row rather than a pump model - including those would look
    up a pump model by a specification's id and find nothing.

    Ordered by promotion time so that where several candidates describe one model they
    are re-applied in the order the reviewer accepted them, which is the order the live
    path would have written them in.

    ``ai_job`` is eagerly loaded because the provenance context records the model that
    produced the value, and a lazy load per candidate is a round trip per candidate.
    """
    return list(
        db.scalars(
            select(ExtractedEntity)
            .options(selectinload(ExtractedEntity.ai_job))
            .where(
                ExtractedEntity.entity_type == "pump_model",
                ExtractedEntity.promoted_at.is_not(None),
                ExtractedEntity.target_type == "pump_model",
                ExtractedEntity.target_id.is_not(None),
            )
            .order_by(ExtractedEntity.promoted_at)
        ).all()
    )


def spec_fields_of(entity: ExtractedEntity) -> dict[str, Any]:
    """The candidate's specification-level fields: everything not identity."""
    fields = (entity.payload or {}).get("fields") or {}
    return {
        name: value
        for name, value in fields.items()
        if name not in IDENTITY_FIELDS and value is not None
    }


def owning_table(field_name: str) -> str | None:
    """The spec table a field belongs to, or None if no spec table has such a column.

    Membership is tested the same way ``write_spec_groups`` routes the value, so this
    cannot disagree with where the field actually lands. No column name is shared by two
    spec models, so there is at most one answer.
    """
    for spec_cls in SPEC_MODEL_BY_ENTITY.values():
        if hasattr(spec_cls, field_name):
            return spec_cls.__tablename__
    return None


def unmapped_fields(fields: dict[str, Any]) -> list[str]:
    """Field names that match no column on any spec table.

    ``write_spec_groups`` routes a field by column membership, so these are dropped
    there silently. They are the one part of the payload this script cannot recover, so
    they are counted and named rather than passed over: an operator deciding whether to
    re-extract needs to know they exist.
    """
    return sorted(name for name in fields if owning_table(name) is None)


def resolve_pump_models(db: Session, model_ids: set[uuid.UUID]) -> dict[uuid.UUID, PumpModel]:
    """Load every target model at once, with the pump and vendor used for labels."""
    if not model_ids:
        return {}
    models = db.scalars(
        select(PumpModel)
        .options(selectinload(PumpModel.pump).selectinload(Pump.vendor))
        .where(PumpModel.id.in_(model_ids), PumpModel.deleted_at.is_(None))
    ).all()
    return {model.id: model for model in models}


def existing_spec_values(
    db: Session, model_ids: set[uuid.UUID]
) -> dict[uuid.UUID, dict[str, set[str]]]:
    """Which fields each model's current spec versions already hold, in one query per table.

    This is the snapshot rule 3 is enforced against, and the reason the run is usable at
    all: asking per model per table is six queries per candidate against a database a
    third of a second away, where this is six queries for the whole run.

    Deliberately taken once, before anything is written. A value this run puts in is
    therefore not in the snapshot, so where two candidates carry the same field the later
    one overwrites the earlier - what the live path would have done - while a value that
    predates the run is never touched.
    """
    snapshot: dict[uuid.UUID, dict[str, set[str]]] = defaultdict(dict)
    if not model_ids:
        return snapshot
    for spec_cls in SPEC_MODEL_BY_ENTITY.values():
        table = spec_cls.__tablename__
        rows = db.scalars(
            select(spec_cls).where(
                spec_cls.pump_model_id.in_(model_ids),
                spec_cls.is_current.is_(True),
            )
        ).all()
        for row in rows:
            snapshot[row.pump_model_id][table] = {
                column.name
                for column in spec_cls.__table__.columns
                if getattr(row, column.name, None) is not None
            }
    return snapshot


def context_for(entity: ExtractedEntity) -> provenance.ProvenanceContext:
    """The same context the promotion would have built.

    Origin stays AI extraction and the original source, job and candidate ids are
    carried, because that is what these values are - nothing here is a human decision,
    and dressing the repair up as one would put a person's name on a machine's reading.
    """
    return provenance.ProvenanceContext(
        origin=ValueOrigin.AI_EXTRACTION,
        confidence_level=entity.confidence_level,
        confidence_score=entity.overall_confidence,
        source_id=entity.source_id,
        ai_job_id=entity.ai_job_id,
        extracted_entity_id=entity.id,
        model_used=entity.ai_job.model if entity.ai_job else None,
        changed_by_user_id=None,
        tenant_id=entity.tenant_id,
    )


def repair(
    entity: ExtractedEntity,
    db: Session,
    *,
    pump_model: PumpModel,
    fields_with_a_value: dict[str, set[str]],
) -> dict[str, Any]:
    """Re-apply one candidate's specification values. Returns its outcome."""
    fields = spec_fields_of(entity)
    unmapped = unmapped_fields(fields)
    evidence = {
        name: (span or {}).get("quote", "") for name, span in (entity.evidence_spans or {}).items()
    }

    _, outcomes = promotion.write_spec_groups(
        db,
        entity=entity,
        pump_model=pump_model,
        context=context_for(entity),
        fields=fields,
        evidence=evidence,
        source_units=(entity.payload or {}).get("source_units") or {},
        principal=None,
        change_reason=CHANGE_REASON,
        # Never overwrite a value that was already recorded; only fill the gaps.
        skip_fields_with_a_value=True,
        fields_with_a_value=fields_with_a_value,
    )

    applied: list[str] = []
    unchanged: list[str] = []
    refused: dict[str, str] = {}
    for outcome in outcomes.values():
        applied.extend(outcome.get("applied") or [])
        unchanged.extend(outcome.get("unchanged") or [])
        refused.update(outcome.get("refused") or {})

    # Fields the snapshot already held never reach apply_fields, so account for them here.
    already = {
        name
        for name in fields
        if name not in unmapped and name in (fields_with_a_value.get(owning_table(name)) or ())
    }
    return {
        "applied": applied,
        "unchanged": unchanged,
        "refused": refused,
        "unmapped": unmapped,
        "already_had_a_value": sorted(already),
    }


def label_for(model: PumpModel) -> str:
    pump = model.pump
    vendor = pump.vendor if pump else None
    parts = [p for p in (vendor.name if vendor else None, pump.name if pump else None) if p]
    return f"{' / '.join(parts)} / {model.model_code}" if parts else model.model_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--commit", action="store_true", help="write the repairs (default is a dry run)"
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written and roll it back (the default)",
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after N candidates")
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        metavar="PUMP_MODEL_ID",
        help="only repair this pump model; repeatable, for verifying on a few first",
    )
    args = parser.parse_args()
    commit = args.commit

    db = SessionLocal()
    # Platform scope for the survey: the damage is not scoped to a tenant's request.
    set_tenant_guc(db, None, is_platform_admin=True)

    entities = candidates_to_repair(db)
    if args.models:
        wanted = {uuid.UUID(value) for value in args.models}
        entities = [e for e in entities if e.target_id in wanted]
    entities = [e for e in entities if spec_fields_of(e)]
    if args.limit:
        entities = entities[: args.limit]

    models = resolve_pump_models(db, {e.target_id for e in entities})
    snapshot = existing_spec_values(db, set(models))

    print()
    print(f"  candidates carrying spec values : {len(entities)}")
    print(f"  pump models they belong to      : {len(models)}")
    print(f"  values in their payloads        : {sum(len(spec_fields_of(e)) for e in entities)}")
    print()

    per_model: dict[uuid.UUID, Counter] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    refusal_reasons: Counter[str] = Counter()
    unmapped_names: Counter[str] = Counter()
    touched: dict[uuid.UUID, uuid.UUID | None] = {}

    # Every candidate is written under its own tenant, the way a request would be. They
    # are grouped so the setting is applied once per tenant instead of once per candidate.
    for entity in sorted(entities, key=lambda e: (str(e.tenant_id), e.promoted_at)):
        pump_model = models.get(entity.target_id)
        if pump_model is None:
            totals["skipped_deleted_model"] += 1
            continue
        set_tenant_guc(db, entity.tenant_id, is_platform_admin=False)
        try:
            outcome = repair(
                entity,
                db,
                pump_model=pump_model,
                fields_with_a_value=snapshot.get(pump_model.id, {}),
            )
        except Exception as exc:  # one bad candidate must not abandon the rest
            db.rollback()
            totals["errors"] += 1
            log.warning("backfill.candidate_failed", entity_id=str(entity.id), error=str(exc))
            print(f"    ! {entity.id}: {exc}")
            continue

        counts = per_model[pump_model.id]
        counts["applied"] += len(outcome["applied"])
        counts["unchanged"] += len(outcome["unchanged"])
        counts["refused"] += len(outcome["refused"])
        counts["unmapped"] += len(outcome["unmapped"])
        counts["already_had_a_value"] += len(outcome["already_had_a_value"])
        for key in ("applied", "unchanged", "refused", "unmapped", "already_had_a_value"):
            totals[key] += len(outcome[key])
        for reason in outcome["refused"].values():
            refusal_reasons["no evidence quote" if "evidence quote" in reason else reason] += 1
        for name in outcome["unmapped"]:
            unmapped_names[name] += 1
        if outcome["applied"]:
            touched[pump_model.id] = entity.tenant_id

        if commit:
            db.commit()

    # Search rows and scorecards are derived from the values just written, so they are
    # refreshed once per model rather than once per candidate - several candidates often
    # describe the same model.
    if commit and touched:
        print(f"  reindexing {len(touched)} models and marking their scorecards stale")
        for model_id, tenant_id in touched.items():
            set_tenant_guc(db, tenant_id, is_platform_admin=False)
            indexing.reindex_pump_model(db, model_id)
            comparison.mark_scores_stale(db, model_id)
        db.commit()

    for model_id, counts in sorted(per_model.items(), key=lambda item: -item[1]["applied"]):
        if not any(counts.values()):
            continue
        detail = ", ".join(
            f"{counts[key]} {label}"
            for key, label in (
                ("applied", "applied"),
                ("already_had_a_value", "already set"),
                ("refused", "refused"),
                ("unmapped", "no such field"),
                ("unchanged", "unchanged"),
            )
            if counts[key]
        )
        print(f"    {label_for(models[model_id]):<58} {detail}")

    print()
    print(f"  values applied            : {totals['applied']}")
    print(f"  already had a value       : {totals['already_had_a_value']}")
    print(f"  refused                   : {totals['refused']}")
    print(f"  named no spec field       : {totals['unmapped']}")
    print(f"  written, value unchanged  : {totals['unchanged']}")
    print(f"  pump models repaired      : {len(touched)}")
    if totals["skipped_deleted_model"]:
        print(f"  models since deleted      : {totals['skipped_deleted_model']}")
    if totals["errors"]:
        print(f"  candidates failed         : {totals['errors']}")
    if refusal_reasons:
        print(f"  refusal reasons           : {dict(refusal_reasons)}")
    if unmapped_names:
        print(f"  unrecoverable field names : {dict(unmapped_names)}")

    print()
    if commit:
        print("  committed")
    else:
        # One rollback at the end, not one per candidate: rolling back mid-run expires
        # every loaded object and turns the next candidate back into extra round trips,
        # and keeping the writes in the transaction is what makes the report accurate
        # where several candidates touch one model.
        db.rollback()
        print("  DRY RUN - nothing written (pass --commit)")
    db.close()


if __name__ == "__main__":
    main()
