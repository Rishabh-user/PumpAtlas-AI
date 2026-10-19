"""AI review screen, enrichment and job monitoring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import AiJob
from app.schemas.ai import (
    AiJobOut,
    EnrichRequest,
)
from app.schemas.common import Page

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


