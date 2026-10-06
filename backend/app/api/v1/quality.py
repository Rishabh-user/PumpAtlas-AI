"""Data-quality dashboard, flags and duplicate review."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import (
    AiSuggestion,
    DataQualityFlag,
    DuplicateCandidate,
    ExtractedEntity,
    FieldProvenance,
)
from app.models.enums import AuditAction, ReviewDecision, ValueOrigin
from app.models.pump import PumpModel
from app.models.search import SearchIndex
from app.models.vendor import Vendor
from app.schemas.ai import (
    DuplicateCandidateOut,
    FlagResolutionRequest,
    QualityDashboard,
)
from app.schemas.common import FieldFlag, Message, Page
from app.services import audit
from app.services import quality as quality_service

router = APIRouter(prefix="/quality", tags=["data quality"])

STALE_AFTER_DAYS = 365


@router.get(
    "/dashboard",
    response_model=QualityDashboard,
    dependencies=[Depends(require("data_quality", "read"))],
)
def dashboard(db: DbSession) -> QualityDashboard:
    """The data-quality screen. Every number here is scoped by RLS to the caller's tenant."""
    total_models = (
        db.scalar(select(func.count()).select_from(PumpModel).where(PumpModel.deleted_at.is_(None)))
        or 0
    )
    total_vendors = (
        db.scalar(select(func.count()).select_from(Vendor).where(Vendor.deleted_at.is_(None))) or 0
    )
    avg_completeness = db.scalar(select(func.avg(SearchIndex.data_completeness_pct)))

    by_confidence = {
        str(level.value if hasattr(level, "value") else level): int(count)
        for level, count in db.execute(
            select(PumpModel.confidence_level, func.count())
            .where(PumpModel.deleted_at.is_(None))
            .group_by(PumpModel.confidence_level)
        ).all()
    }
    by_verification = {
        str(status_value.value if hasattr(status_value, "value") else status_value): int(count)
        for status_value, count in db.execute(
            select(PumpModel.verification_status, func.count())
            .where(PumpModel.deleted_at.is_(None))
            .group_by(PumpModel.verification_status)
        ).all()
    }
    flags_by_severity = {
        str(sev.value if hasattr(sev, "value") else sev): int(count)
        for sev, count in db.execute(
            select(DataQualityFlag.severity, func.count())
            .where(DataQualityFlag.is_resolved.is_(False))
            .group_by(DataQualityFlag.severity)
        ).all()
    }
    flags_by_type = {
        str(kind.value if hasattr(kind, "value") else kind): int(count)
        for kind, count in db.execute(
            select(DataQualityFlag.flag_type, func.count())
            .where(DataQualityFlag.is_resolved.is_(False))
            .group_by(DataQualityFlag.flag_type)
        ).all()
    }
    top_missing = [
        {"field_name": field_name, "count": int(count)}
        for field_name, count in db.execute(
            select(DataQualityFlag.field_name, func.count())
            .where(
                DataQualityFlag.is_resolved.is_(False),
                DataQualityFlag.flag_type == "missing_required_field",
                DataQualityFlag.field_name.isnot(None),
            )
            .group_by(DataQualityFlag.field_name)
            .order_by(func.count().desc())
            .limit(15)
        ).all()
    ]

    stale_cutoff = datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS)
    stale = (
        db.scalar(
            select(func.count())
            .select_from(SearchIndex)
            .where(
                (SearchIndex.last_source_captured_at < stale_cutoff)
                | (SearchIndex.last_source_captured_at.is_(None))
            )
        )
        or 0
    )
    open_duplicates = (
        db.scalar(
            select(func.count())
            .select_from(DuplicateCandidate)
            .where(DuplicateCandidate.status == "open")
        )
        or 0
    )
    pending_reviews = (
        db.scalar(
            select(func.count())
            .select_from(ExtractedEntity)
            .where(ExtractedEntity.review_decision == ReviewDecision.PENDING)
        )
        or 0
    )

    ai_origins = [
        ValueOrigin.AI_EXTRACTION.value,
        ValueOrigin.AI_NORMALIZATION.value,
        ValueOrigin.AI_INFERENCE.value,
    ]
    total_provenance = (
        db.scalar(
            select(func.count())
            .select_from(FieldProvenance)
            .where(FieldProvenance.is_current.is_(True))
        )
        or 0
    )
    ai_provenance = (
        db.scalar(
            select(func.count())
            .select_from(FieldProvenance)
            .where(
                FieldProvenance.is_current.is_(True),
                FieldProvenance.value_origin.in_(ai_origins),
            )
        )
        or 0
    )

    return QualityDashboard(
        total_pump_models=int(total_models),
        total_vendors=int(total_vendors),
        avg_completeness_pct=(
            round(float(avg_completeness) * 100, 2) if avg_completeness is not None else None
        ),
        records_by_confidence=by_confidence,
        records_by_verification=by_verification,
        open_flags_by_severity=flags_by_severity,
        open_flags_by_type=flags_by_type,
        top_missing_fields=top_missing,
        stale_records=int(stale),
        duplicate_candidates_open=int(open_duplicates),
        pending_ai_reviews=int(pending_reviews),
        ai_field_share_pct=(
            round(ai_provenance / total_provenance * 100, 2) if total_provenance else None
        ),
    )


@router.get(
    "/flags",
    response_model=Page[FieldFlag],
    dependencies=[Depends(require("data_quality", "read"))],
)
def list_flags(
    db: DbSession,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    severity: list[str] = Query(default_factory=list),
    flag_type: list[str] = Query(default_factory=list),
    detected_by: str | None = None,
    is_resolved: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(DataQualityFlag).where(DataQualityFlag.is_resolved.is_(is_resolved))
    if entity_type:
        stmt = stmt.where(DataQualityFlag.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(DataQualityFlag.entity_id == entity_id)
    if severity:
        stmt = stmt.where(DataQualityFlag.severity.in_(severity))
    if flag_type:
        stmt = stmt.where(DataQualityFlag.flag_type.in_(flag_type))
    if detected_by:
        stmt = stmt.where(DataQualityFlag.detected_by == detected_by)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(DataQualityFlag.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[FieldFlag](items=rows, total=int(total), limit=limit, offset=offset)


@router.post(
    "/flags/{flag_id}/resolve",
    response_model=Message,
    dependencies=[Depends(require("data_quality", "write"))],
)
def resolve_flag(
    flag_id: uuid.UUID,
    payload: FlagResolutionRequest,
    principal: CurrentPrincipal,
    db: DbSession,
) -> Message:
    """Close a flag. ``corrected`` should be paired with an actual field edit."""
    flag = db.get(DataQualityFlag, flag_id)
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flag not found")
    if flag.is_resolved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Flag is already resolved")

    flag.is_resolved = True
    flag.resolution = payload.resolution
    flag.resolved_by_user_id = principal.user_id
    flag.resolved_at = datetime.now(UTC)
    flag.resolution_notes = payload.notes

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="data_quality_flags",
        entity_id=flag.id,
        entity_label=flag.flag_type.value,
        summary=f"Flag resolved as {payload.resolution}",
        context={"notes": payload.notes, "corrected_value": payload.corrected_value},
    )
    db.commit()
    return Message(detail=f"Flag resolved as {payload.resolution}")


@router.post("/validate/{pump_model_id}", dependencies=[Depends(require("data_quality", "write"))])
def revalidate(
    pump_model_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    run_ai_check: bool = Query(
        default=False, description="Also run the Gemma judgement-call review"
    ),
) -> dict:
    """Re-run the deterministic validators, optionally followed by the AI check."""
    from app.services import records

    model = db.get(PumpModel, pump_model_id)
    if model is None or model.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pump model not found")

    flat = records.flatten_pump_model(db, pump_model_id)
    findings = quality_service.validate_record("pump_models", flat)
    for entity_type in (
        "technical_specs",
        "commercial_specs",
        "dimensional_specs",
        "delivery_specs",
        "operational_specs",
        "administrative_specs",
    ):
        findings.extend(quality_service.check_completeness(entity_type, flat))

    persisted = quality_service.persist_findings(
        db,
        tenant_id=model.tenant_id,
        entity_type="pump_models",
        entity_id=model.id,
        findings=findings,
    )
    db.commit()

    ai_task_id = None
    if run_ai_check:
        from app.workers.tasks import ai_quality_check_task

        ai_task_id = ai_quality_check_task.delay(
            str(pump_model_id),
            str(model.tenant_id) if model.tenant_id else None,
            str(principal.user_id) if principal.user_id else None,
        ).id

    return {
        "pump_model_id": str(pump_model_id),
        "validator_flags": len(persisted),
        "by_severity": {
            severity: sum(1 for f in findings if f.severity.value == severity)
            for severity in {f.severity.value for f in findings}
        },
        "ai_check_task_id": ai_task_id,
    }


@router.get(
    "/duplicates",
    response_model=Page[DuplicateCandidateOut],
    dependencies=[Depends(require("data_quality", "read"))],
)
def list_duplicates(
    db: DbSession,
    entity_type: str | None = Query(default=None, description="vendors | pump_models"),
    status_filter: str = Query(default="open", alias="status"),
    min_score: float = Query(default=0.55, ge=0, le=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Suspected duplicate pairs for review."""
    stmt = select(DuplicateCandidate).where(DuplicateCandidate.similarity_score >= min_score)
    if status_filter != "all":
        stmt = stmt.where(DuplicateCandidate.status == status_filter)
    if entity_type:
        stmt = stmt.where(DuplicateCandidate.entity_type == entity_type)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(DuplicateCandidate.similarity_score.desc()).limit(limit).offset(offset)
    ).all()

    items: list[DuplicateCandidateOut] = []
    for row in rows:
        item = DuplicateCandidateOut.model_validate(row)
        item.similarity_score = float(row.similarity_score)
        item.label_a = _label_for(db, row.entity_type, row.entity_id_a)
        item.label_b = _label_for(db, row.entity_type, row.entity_id_b)
        items.append(item)
    return Page[DuplicateCandidateOut](items=items, total=int(total), limit=limit, offset=offset)


def _label_for(db: DbSession, entity_type: str, entity_id: uuid.UUID) -> str | None:
    if entity_type == "vendors":
        vendor = db.get(Vendor, entity_id)
        return vendor.name if vendor else None
    if entity_type == "pump_models":
        row = db.scalar(select(SearchIndex.label).where(SearchIndex.pump_model_id == entity_id))
        if row:
            return row
        model = db.get(PumpModel, entity_id)
        return model.model_code if model else None
    return None


@router.post(
    "/duplicates/{candidate_id}/resolve",
    response_model=Message,
    dependencies=[Depends(require("data_quality", "write"))],
)
def resolve_duplicate(
    candidate_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    resolution: str = Query(description="distinct | deferred"),
    notes: str | None = None,
) -> Message:
    """Mark a pair as genuinely distinct or defer it. Merging is a separate action."""
    if resolution not in {"distinct", "deferred"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Use the vendor merge endpoint to merge; this endpoint only dismisses pairs",
        )
    candidate = db.get(DuplicateCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Duplicate candidate not found")

    candidate.status = resolution
    candidate.reviewed_by_user_id = principal.user_id
    candidate.reviewed_at = datetime.now(UTC)
    candidate.notes = notes
    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="duplicate_candidates",
        entity_id=candidate.id,
        summary=f"Duplicate pair marked {resolution}",
        context={"notes": notes},
    )
    db.commit()
    return Message(detail=f"Pair marked {resolution}")


@router.post(
    "/duplicates/{candidate_id}/adjudicate",
    dependencies=[Depends(require("data_quality", "write"))],
)
def adjudicate_duplicate(
    candidate_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> dict:
    """Ask Gemma whether two records describe the same subject. Advisory only."""
    from app.services import dedupe, records

    candidate = db.get(DuplicateCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Duplicate candidate not found")

    def _record(entity_id: uuid.UUID) -> dict[str, Any]:
        if candidate.entity_type == "vendors":
            vendor = db.get(Vendor, entity_id)
            if vendor is None:
                return {}
            return records.to_jsonable(
                {
                    "name": vendor.name,
                    "aliases": vendor.aliases,
                    "country": vendor.country,
                    "website": vendor.website,
                    "vendor_tier": vendor.vendor_tier,
                    "description": vendor.description,
                    "registration": vendor.dun_bradstreet_number,
                }
            )
        return records.flatten_pump_model(db, entity_id)

    try:
        verdict = dedupe.adjudicate_with_ai(
            db,
            tenant_id=candidate.tenant_id,
            entity_type=candidate.entity_type,
            record_a=_record(candidate.entity_id_a),
            record_b=_record(candidate.entity_id_b),
            candidate=candidate,
            user_id=principal.user_id,
        )
    except Exception as exc:  # noqa: BLE001 - surface provider errors to the caller
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    db.commit()
    return {"candidate_id": str(candidate_id), "verdict": verdict}


@router.get("/suggestions/pending-count", dependencies=[Depends(require("data_quality", "read"))])
def pending_counts(db: DbSession) -> dict:
    """Badge counts for the dashboard navigation.

    One statement, not one per badge. The navigation shell asks for these on every page
    in the app, and against a hosted database a third of a second away four separate
    counts cost more than most pages spend on their own data. Four scalar subqueries in
    a single SELECT are one round trip and the same four numbers.
    """
    row = db.execute(
        select(
            select(func.count())
            .select_from(ExtractedEntity)
            .where(ExtractedEntity.review_decision == ReviewDecision.PENDING)
            .scalar_subquery()
            .label("ai_review"),
            select(func.count())
            .select_from(AiSuggestion)
            .where(AiSuggestion.decision == ReviewDecision.PENDING)
            .scalar_subquery()
            .label("field_suggestions"),
            select(func.count())
            .select_from(DataQualityFlag)
            .where(DataQualityFlag.is_resolved.is_(False))
            .scalar_subquery()
            .label("open_flags"),
            select(func.count())
            .select_from(DuplicateCandidate)
            .where(DuplicateCandidate.status == "open")
            .scalar_subquery()
            .label("duplicates"),
        )
    ).one()
    return {
        "ai_review": int(row.ai_review or 0),
        "field_suggestions": int(row.field_suggestions or 0),
        "open_flags": int(row.open_flags or 0),
        "duplicates": int(row.duplicates or 0),
    }
