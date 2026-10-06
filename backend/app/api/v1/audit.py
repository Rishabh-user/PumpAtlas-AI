"""Audit trail and change history endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import DbSession, require
from app.models.audit import AuditLog, RecordVersion
from app.schemas.common import Page
from app.schemas.comparison import AuditLogOut, RecordVersionOut

router = APIRouter(tags=["audit"])


@router.get(
    "/audit-logs",
    response_model=Page[AuditLogOut],
    dependencies=[Depends(require("audit", "read"))],
)
def list_audit_logs(
    db: DbSession,
    action: list[str] = Query(default_factory=list),
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = Query(default=None, description="Summary contains"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """The audit trail screen. Append-only; nothing here can be edited or deleted."""
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.in_(action))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if since:
        stmt = stmt.where(AuditLog.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditLog.occurred_at <= until)
    if q:
        stmt = stmt.where(AuditLog.summary.ilike(f"%{q}%") | AuditLog.entity_label.ilike(f"%{q}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.occurred_at.desc()).limit(limit).offset(offset)).all()
    return Page[AuditLogOut](items=list(rows), total=int(total), limit=limit, offset=offset)


@router.get("/audit-logs/actions", dependencies=[Depends(require("audit", "read"))])
def audit_action_summary(
    db: DbSession,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Counts per action for the audit screen's filter chips."""
    from datetime import UTC, timedelta

    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(AuditLog.action, func.count())
        .where(AuditLog.occurred_at >= since)
        .group_by(AuditLog.action)
        .order_by(func.count().desc())
    ).all()
    return {
        "window_days": days,
        "actions": [
            {
                "action": action.value if hasattr(action, "value") else str(action),
                "count": int(count),
            }
            for action, count in rows
        ],
    }


@router.get(
    "/record-versions",
    response_model=Page[RecordVersionOut],
    dependencies=[Depends(require("audit", "read"))],
)
def list_record_versions(
    db: DbSession,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Row snapshots, for reconstructing what a record looked like at a point in time."""
    stmt = select(RecordVersion)
    if entity_type:
        stmt = stmt.where(RecordVersion.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(RecordVersion.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(RecordVersion.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[RecordVersionOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.get(
    "/record-versions/{version_id}",
    response_model=RecordVersionOut,
    dependencies=[Depends(require("audit", "read"))],
)
def get_record_version(version_id: uuid.UUID, db: DbSession) -> RecordVersion:
    version = db.get(RecordVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record version not found")
    return version
