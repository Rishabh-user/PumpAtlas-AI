"""AI review screen, enrichment and job monitoring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import AiJob, AiSuggestion, ExtractedEntity
from app.models.enums import AuditAction, ReviewDecision, ValueOrigin
from app.models.source import Source
from app.models.vendor import Vendor
from app.schemas.ai import (
    AiJobOut,
    AiSuggestionOut,
    BulkReviewRequest,
    EnrichRequest,
    ExtractedEntityOut,
    ReviewDecisionRequest,
    ReviewQueueItem,
    SuggestionDecisionRequest,
)
from app.schemas.common import Message, Page
from app.services import audit, comparison, indexing, promotion, provenance

router = APIRouter(prefix="/ai", tags=["ai review"])


#: The vendor states a reviewer sorts by.
#:
#: Whether a candidate can be promoted at all turns on this: no manufacturer name means
#: there is no vendor to hang the record on, and it is the most common reason a card is
#: unusable. The state is derived rather than stored, so it has to be computed in one
#: place - otherwise a filtered list shows cards whose badge contradicts the filter.
VENDOR_MATCH_STATES = ("matched", "new", "missing")

#: What each ``decision`` filter value actually selects.
#:
#: "accepted" has to cover ``accepted_with_edits`` too: a reviewer who corrected a value
#: before promoting it still accepted the candidate, and matching the enum exactly hid
#: those rows under every filter except "all" - a filter that quietly loses records is
#: worse than no filter. ``escalated`` is listed because the review screen can set it.
DECISION_GROUPS: dict[str, tuple[str, ...]] = {
    "pending": ("pending",),
    "accepted": ("accepted", "accepted_with_edits"),
    "rejected": ("rejected",),
    "escalated": ("escalated",),
}


def _decision_clause(decision: str):
    """WHERE clause for a decision filter value, or None for "all"."""
    if decision == "all":
        return None
    values = DECISION_GROUPS.get(decision)
    if values is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown decision {decision!r}. Expected any of: "
            f"{', '.join([*DECISION_GROUPS, 'all'])}.",
        )
    return ExtractedEntity.review_decision.in_(values)


def _vendor_name_expr():
    """The manufacturer name Gemma put in the candidate's subject."""
    return ExtractedEntity.payload["subject"]["vendor_name"].astext


def _matched_vendor_subquery():
    """The id of the vendor this candidate would merge into, as a column.

    Asked one row at a time this was a query each: 25 cards meant 25 round trips to a
    hosted database and the screen took six seconds to open. As a correlated subquery it
    costs nothing extra - and it is also more correct, because
    ``pumpatlas_normalize_company_name`` applies ``unaccent`` and the Python mirror does
    not, so a vendor such as "Apollo Gossnitz GmbH" was reported as new when it already
    existed.
    """
    return (
        select(Vendor.id)
        .where(
            Vendor.normalized_name == func.pumpatlas_normalize_company_name(_vendor_name_expr()),
            Vendor.deleted_at.is_(None),
        )
        .limit(1)
        .correlate(ExtractedEntity)
        .scalar_subquery()
    )


def _has_fields_expr():
    """Whether the extraction produced any fields at all.

    A candidate with none is a page Gemma could not read anything off. They dominate a
    large queue and there is nothing in them for a reviewer to judge, so they are worth
    hiding - but not deleting, because the source still records what was tried.
    """
    # Coalesced, because a NULL here would make the row vanish from *both* has_fields
    # and its negation: `NULL NOT IN (...)` and its inverse are both NULL, so a
    # candidate with no "fields" key at all would be silently unreachable by either
    # filter and the two counts would no longer add up to the total.
    return func.coalesce(ExtractedEntity.payload["fields"].astext, "{}").notin_(("{}", "null"))


def _vendor_match_clause(states: list[str]):
    """WHERE clause for the requested vendor states, or None for no restriction."""
    wanted = [state for state in VENDOR_MATCH_STATES if state in states]
    if not wanted or len(wanted) == len(VENDOR_MATCH_STATES):
        return None

    name = _vendor_name_expr()
    named = and_(name.is_not(None), name != "")
    matched = _matched_vendor_subquery().is_not(None)
    clauses = {
        "matched": and_(named, matched),
        "new": and_(named, ~matched),
        "missing": or_(name.is_(None), name == ""),
    }
    return or_(*(clauses[state] for state in wanted))


@router.get("/review-queue/facets", dependencies=[Depends(require("ai_review", "read"))])
def review_queue_facets(
    db: DbSession,
    decision: str = Query(
        default="pending",
        description="pending | accepted | rejected | escalated | all",
    ),
) -> Any:
    """How many candidates sit in each bucket, so the filters can carry counts.

    One query with conditional aggregation rather than one per bucket: against a remote
    database the counts are only worth showing if they cost a single round trip.
    """
    name = _vendor_name_expr()
    named = and_(name.is_not(None), name != "")
    matched = _matched_vendor_subquery().is_not(None)
    has_fields = _has_fields_expr()

    stmt = select(
        func.count().label("total"),
        func.count().filter(and_(named, matched)).label("matched"),
        func.count().filter(and_(named, ~matched)).label("new_vendor"),
        func.count().filter(or_(name.is_(None), name == "")).label("missing"),
        func.count().filter(has_fields).label("with_fields"),
        func.count().filter(~has_fields).label("without_fields"),
    ).select_from(ExtractedEntity)
    decision_clause = _decision_clause(decision)
    if decision_clause is not None:
        stmt = stmt.where(decision_clause)

    row = db.execute(stmt).one()

    # A second small query rather than a wider first one: the entity types are open -
    # a new extraction contract adds one - so they cannot be conditional columns.
    type_stmt = select(ExtractedEntity.entity_type, func.count().label("n")).group_by(
        ExtractedEntity.entity_type
    )
    if decision_clause is not None:
        type_stmt = type_stmt.where(decision_clause)

    return {
        "total": int(row.total),
        "vendor_match": {
            "matched": int(row.matched),
            "new": int(row.new_vendor),
            "missing": int(row.missing),
        },
        "fields": {
            "with_fields": int(row.with_fields),
            "without_fields": int(row.without_fields),
        },
        "entity_type": {
            entity_type: int(count) for entity_type, count in db.execute(type_stmt).all()
        },
    }


@router.get(
    "/review-queue",
    response_model=Page[ReviewQueueItem],
    dependencies=[Depends(require("ai_review", "read"))],
)
def review_queue(
    db: DbSession,
    entity_type: list[str] = Query(default_factory=list),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_confidence: float | None = Query(default=None, ge=0, le=1),
    source_id: uuid.UUID | None = None,
    decision: str = Query(
        default="pending",
        description="pending | accepted | rejected | escalated | all",
    ),
    vendor_match: list[str] = Query(
        default_factory=list,
        description="matched | new | missing - repeat to allow several",
    ),
    has_fields: bool | None = Query(
        default=None, description="true keeps only candidates that extracted a field"
    ),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Candidates awaiting human judgement, least-confident first."""
    unknown = sorted({state for state in vendor_match if state not in VENDOR_MATCH_STATES})
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown vendor_match value(s): {', '.join(unknown)}."
            f" Expected any of: {', '.join(VENDOR_MATCH_STATES)}.",
        )

    matched_vendor_id = _matched_vendor_subquery()
    stmt = select(ExtractedEntity, Source, matched_vendor_id.label("matched_vendor_id")).join(
        Source, Source.id == ExtractedEntity.source_id, isouter=True
    )
    decision_clause = _decision_clause(decision)
    if decision_clause is not None:
        stmt = stmt.where(decision_clause)
    if entity_type:
        stmt = stmt.where(ExtractedEntity.entity_type.in_(entity_type))
    if min_confidence is not None:
        stmt = stmt.where(ExtractedEntity.overall_confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(ExtractedEntity.overall_confidence <= max_confidence)
    if source_id:
        stmt = stmt.where(ExtractedEntity.source_id == source_id)
    if has_fields is not None:
        stmt = stmt.where(_has_fields_expr() if has_fields else ~_has_fields_expr())
    vendor_clause = _vendor_match_clause(vendor_match)
    if vendor_clause is not None:
        stmt = stmt.where(vendor_clause)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(
            ExtractedEntity.overall_confidence.asc().nullsfirst(),
            ExtractedEntity.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()

    items: list[ReviewQueueItem] = []
    for entity, source, matched_id in rows:
        subject = (entity.payload or {}).get("subject") or {}
        vendor_name = subject.get("vendor_name")
        item = ReviewQueueItem.model_validate(entity)
        item.source_title = source.title if source else None
        item.source_url = source.source_url if source else None
        item.source_type = source.source_type.value if source else None
        item.source_captured_at = source.captured_at if source else None
        item.suggested_vendor = vendor_name
        item.suggested_model_code = subject.get("model_code")
        item.field_count = len((entity.payload or {}).get("fields") or {})
        item.matched_existing_vendor_id = matched_id
        # Derived server-side so a card's badge can never disagree with the filter that
        # selected it.
        item.vendor_match = "matched" if matched_id else "new" if vendor_name else "missing"
        items.append(item)

    return Page[ReviewQueueItem](items=items, total=int(total), limit=limit, offset=offset)


@router.get(
    "/review-queue/{entity_id}",
    response_model=ExtractedEntityOut,
    dependencies=[Depends(require("ai_review", "read"))],
)
def get_candidate(entity_id: uuid.UUID, db: DbSession) -> ExtractedEntity:
    entity = db.get(ExtractedEntity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extraction candidate not found")
    return entity


@router.post(
    "/review-queue/{entity_id}/decide", dependencies=[Depends(require("ai_review", "approve"))]
)
def decide_candidate(
    entity_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    principal: CurrentPrincipal,
    db: DbSession,
) -> dict:
    """Accept, edit-and-accept, reject or escalate one extraction candidate.

    Accepting promotes it into the system of record and writes provenance rows for every
    field, naming the source, the model and the evidence quote.
    """
    entity = db.get(ExtractedEntity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extraction candidate not found")
    if entity.promoted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Already promoted to {entity.target_type} {entity.target_id}",
        )
    try:
        decision = ReviewDecision(payload.decision)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown decision '{payload.decision}'",
        ) from exc

    if decision in {ReviewDecision.REJECTED, ReviewDecision.ESCALATED}:
        entity.review_decision = decision
        entity.reviewed_by_user_id = principal.user_id
        entity.reviewed_at = datetime.now(UTC)
        entity.review_notes = payload.notes
        audit.record_audit(
            db,
            action=AuditAction.AI_SUGGESTION_REJECTED,
            principal=principal,
            entity_type="extracted_entities",
            entity_id=entity.id,
            entity_label=entity.entity_type,
            summary=f"Extraction {decision.value}",
            context={"notes": payload.notes},
        )
        db.commit()
        return {"status": decision.value, "entity_id": str(entity.id)}

    # Binding to an existing vendor/model is how a reviewer fixes a mis-identified subject.
    edits = dict(payload.edits)
    if payload.vendor_id:
        vendor = db.get(Vendor, payload.vendor_id)
        if vendor is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
        subject = dict((entity.payload or {}).get("subject") or {})
        subject["vendor_name"] = vendor.name
        payload_data = dict(entity.payload or {})
        payload_data["subject"] = subject
        entity.payload = payload_data
    if payload.pump_model_id:
        from app.models.pump import PumpModel

        model = db.get(PumpModel, payload.pump_model_id)
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pump model not found")
        edits.setdefault("model_code", model.model_code)

    try:
        report = promotion.promote_extracted_entity(
            db,
            entity,
            principal=principal,
            reviewer_edits=edits,
            overwrite_verified=payload.overwrite_verified,
            decision=decision,
        )
    except promotion.PromotionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    pump_model_id = uuid.UUID(report["pump_model_id"])
    indexing.reindex_pump_model(db, pump_model_id)
    comparison.mark_scores_stale(db, pump_model_id)
    db.commit()
    return {"status": decision.value, **report}


@router.post("/review-queue/bulk", dependencies=[Depends(require("ai_review", "approve"))])
def bulk_decide(payload: BulkReviewRequest, principal: CurrentPrincipal, db: DbSession) -> dict:
    """Bulk accept or reject. Used to clear a high-confidence batch quickly."""
    try:
        decision = ReviewDecision(payload.decision)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown decision '{payload.decision}'"
        ) from exc
    if decision not in {ReviewDecision.ACCEPTED, ReviewDecision.REJECTED}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Bulk decisions support accepted or rejected only"
        )

    processed, skipped = [], []
    errors: dict[str, str] = {}
    reindex: set[uuid.UUID] = set()

    for entity_id in payload.entity_ids:
        entity = db.get(ExtractedEntity, entity_id)
        if entity is None or entity.promoted_at is not None:
            skipped.append(str(entity_id))
            continue
        if payload.min_confidence is not None and (
            entity.overall_confidence is None
            or float(entity.overall_confidence) < payload.min_confidence
        ):
            skipped.append(str(entity_id))
            continue

        if decision is ReviewDecision.REJECTED:
            entity.review_decision = decision
            entity.reviewed_by_user_id = principal.user_id
            entity.reviewed_at = datetime.now(UTC)
            entity.review_notes = payload.notes
            processed.append(str(entity_id))
            continue

        try:
            report = promotion.promote_extracted_entity(
                db, entity, principal=principal, decision=decision
            )
            reindex.add(uuid.UUID(report["pump_model_id"]))
            processed.append(str(entity_id))
        except promotion.PromotionError as exc:
            errors[str(entity_id)] = str(exc)

    for pump_model_id in reindex:
        indexing.reindex_pump_model(db, pump_model_id)
        comparison.mark_scores_stale(db, pump_model_id)

    audit.record_audit(
        db,
        action=(
            AuditAction.AI_SUGGESTION_APPLIED
            if decision is ReviewDecision.ACCEPTED
            else AuditAction.AI_SUGGESTION_REJECTED
        ),
        principal=principal,
        entity_type="extracted_entities",
        summary=f"Bulk {decision.value}: {len(processed)} processed, {len(skipped)} skipped",
        context={"errors": errors},
    )
    db.commit()
    return {
        "decision": decision.value,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }


@router.get(
    "/suggestions",
    response_model=Page[AiSuggestionOut],
    dependencies=[Depends(require("ai_review", "read"))],
)
def list_suggestions(
    db: DbSession,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    decision: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Field-level enrichment proposals awaiting approval."""
    stmt = select(AiSuggestion)
    if decision != "all":
        stmt = stmt.where(AiSuggestion.decision == decision)
    if entity_type:
        stmt = stmt.where(AiSuggestion.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AiSuggestion.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AiSuggestion.confidence_score.desc().nullslast()).limit(limit).offset(offset)
    ).all()
    return Page[AiSuggestionOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.post(
    "/suggestions/{suggestion_id}/decide", dependencies=[Depends(require("ai_review", "approve"))]
)
def decide_suggestion(
    suggestion_id: uuid.UUID,
    payload: SuggestionDecisionRequest,
    principal: CurrentPrincipal,
    db: DbSession,
) -> dict:
    """Apply or reject one field suggestion, with provenance on the applied value."""
    suggestion = db.get(AiSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
    if suggestion.decision != ReviewDecision.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already {suggestion.decision.value}")
    try:
        decision = ReviewDecision(payload.decision)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown decision '{payload.decision}'"
        ) from exc

    suggestion.decision = decision
    suggestion.decided_by_user_id = principal.user_id
    suggestion.decided_at = datetime.now(UTC)
    suggestion.decision_notes = payload.notes

    if decision is ReviewDecision.REJECTED:
        audit.record_audit(
            db,
            action=AuditAction.AI_SUGGESTION_REJECTED,
            principal=principal,
            entity_type=suggestion.entity_type,
            entity_id=suggestion.entity_id,
            entity_label=suggestion.field_name,
            summary="AI suggestion rejected",
        )
        db.commit()
        return {"status": "rejected", "suggestion_id": str(suggestion_id)}

    target = _load_entity(db, suggestion.entity_type, suggestion.entity_id)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Target {suggestion.entity_type} {suggestion.entity_id} no longer exists",
        )

    value = (
        payload.applied_value if payload.applied_value is not None else (suggestion.suggested_value)
    )
    suggestion.applied_value = value
    # A reviewer-edited value is human-origin; an accepted one keeps its AI origin.
    origin = (
        ValueOrigin.MANUAL
        if decision is ReviewDecision.ACCEPTED_WITH_EDITS
        else ValueOrigin.AI_INFERENCE
    )
    context = provenance.ProvenanceContext(
        origin=origin,
        confidence_level=suggestion.confidence_level,
        confidence_score=suggestion.confidence_score,
        source_id=suggestion.source_id,
        ai_job_id=suggestion.ai_job_id,
        changed_by_user_id=principal.user_id,
        tenant_id=suggestion.tenant_id,
    )
    try:
        changed = provenance.apply_field(
            db,
            target,
            suggestion.field_name,
            value,
            context,
            evidence_quote=suggestion.evidence_quote or "Reviewer-approved AI suggestion",
        )
    except provenance.ProvenanceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    audit.record_audit(
        db,
        action=AuditAction.AI_SUGGESTION_APPLIED,
        principal=principal,
        entity_type=suggestion.entity_type,
        entity_id=suggestion.entity_id,
        entity_label=suggestion.field_name,
        summary=f"AI suggestion applied to {suggestion.field_name}",
        changes={suggestion.field_name: {"from": suggestion.current_value, "to": value}},
    )
    pump_model_id = getattr(target, "pump_model_id", None) or (
        target.id if suggestion.entity_type == "pump_models" else None
    )
    if pump_model_id:
        indexing.reindex_pump_model(db, pump_model_id)
        comparison.mark_scores_stale(db, pump_model_id)
    db.commit()
    return {
        "status": decision.value,
        "field_changed": changed,
        "field_name": suggestion.field_name,
        "applied_value": value,
    }


def _load_entity(db: DbSession, entity_type: str, entity_id: uuid.UUID):
    from app.models.pump import Pump, PumpModel
    from app.models.specs import (
        AdministrativeSpec,
        CommercialSpec,
        DeliverySpec,
        DimensionalSpec,
        OperationalSpec,
        TechnicalSpec,
    )

    table_map = {
        "vendors": Vendor,
        "pumps": Pump,
        "pump_models": PumpModel,
        "technical_specs": TechnicalSpec,
        "commercial_specs": CommercialSpec,
        "dimensional_specs": DimensionalSpec,
        "delivery_specs": DeliverySpec,
        "operational_specs": OperationalSpec,
        "administrative_specs": AdministrativeSpec,
    }
    model = table_map.get(entity_type)
    return db.get(model, entity_id) if model else None


@router.post(
    "/enrich/{pump_model_id}",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ai_review", "write"))],
)
def enrich_pump_model(
    pump_model_id: uuid.UUID,
    payload: EnrichRequest,
    principal: CurrentPrincipal,
    db: DbSession,
) -> dict:
    """Queue enrichment: missing-field detection, quality checks, optional web search."""
    from app.models.pump import PumpModel
    from app.workers.tasks import enrich_pump_model_task

    model = db.get(PumpModel, pump_model_id)
    if model is None or model.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pump model not found")

    task = enrich_pump_model_task.delay(
        str(pump_model_id),
        str(model.tenant_id) if model.tenant_id else None,
        payload.tasks,
        payload.run_web_search,
        str(principal.user_id) if principal.user_id else None,
    )
    return {
        "queued": True,
        "task_id": task.id,
        "pump_model_id": str(pump_model_id),
        "tasks": payload.tasks,
    }


@router.get(
    "/jobs", response_model=Page[AiJobOut], dependencies=[Depends(require("ai_review", "read"))]
)
def list_ai_jobs(
    db: DbSession,
    job_type: list[str] = Query(default_factory=list),
    status_filter: list[str] = Query(default_factory=list, alias="status"),
    source_id: uuid.UUID | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Every AI call, with tokens, cost, latency and the prompt version used."""
    stmt = select(AiJob)
    if job_type:
        stmt = stmt.where(AiJob.job_type.in_(job_type))
    if status_filter:
        stmt = stmt.where(AiJob.status.in_(status_filter))
    if source_id:
        stmt = stmt.where(AiJob.source_id == source_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AiJob.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[AiJobOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.get("/jobs/{job_id}", dependencies=[Depends(require("ai_review", "read"))])
def get_ai_job(
    job_id: uuid.UUID,
    db: DbSession,
    include_raw: bool = Query(default=False, description="Include the verbatim model output"),
) -> dict:
    """One AI job in full - the audit record for a model call."""
    job = db.get(AiJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AI job not found")
    payload = AiJobOut.model_validate(job).model_dump()
    payload["request_payload"] = job.request_payload
    payload["response_payload"] = job.response_payload
    if include_raw:
        payload["raw_response_text"] = job.raw_response_text
    return payload


@router.get("/usage", dependencies=[Depends(require("ai_review", "read"))])
def ai_usage(
    db: DbSession,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Token and cost accounting per job type - what the assistant layer is costing."""
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(
            AiJob.job_type,
            AiJob.status,
            func.count().label("jobs"),
            func.coalesce(func.sum(AiJob.prompt_tokens), 0),
            func.coalesce(func.sum(AiJob.completion_tokens), 0),
            func.coalesce(func.sum(AiJob.cost_usd), 0),
            func.avg(AiJob.latency_ms),
        )
        .where(AiJob.created_at >= since)
        .group_by(AiJob.job_type, AiJob.status)
    ).all()

    breakdown = [
        {
            "job_type": job_type.value if hasattr(job_type, "value") else str(job_type),
            "status": job_status.value if hasattr(job_status, "value") else str(job_status),
            "jobs": int(jobs),
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "cost_usd": float(cost),
            "avg_latency_ms": round(float(latency), 1) if latency else None,
        }
        for job_type, job_status, jobs, prompt_tokens, completion_tokens, cost, latency in rows
    ]
    return {
        "window_days": days,
        "total_jobs": sum(row["jobs"] for row in breakdown),
        "total_tokens": sum(row["prompt_tokens"] + row["completion_tokens"] for row in breakdown),
        "total_cost_usd": round(sum(row["cost_usd"] for row in breakdown), 4),
        "breakdown": breakdown,
    }


@router.post(
    "/review-queue/{entity_id}/reset",
    response_model=Message,
    dependencies=[Depends(require("ai_review", "write"))],
)
def reset_candidate(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Message:
    """Put a rejected candidate back in the queue - reviewers change their minds."""
    entity = db.get(ExtractedEntity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extraction candidate not found")
    if entity.promoted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Promoted candidates cannot be reset; correct the record"
        )
    entity.review_decision = ReviewDecision.PENDING
    entity.reviewed_by_user_id = None
    entity.reviewed_at = None
    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="extracted_entities",
        entity_id=entity.id,
        summary="Candidate returned to the review queue",
    )
    db.commit()
    return Message(detail="Candidate returned to the review queue")
