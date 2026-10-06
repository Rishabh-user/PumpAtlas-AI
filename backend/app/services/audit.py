"""Audit trail and record version history."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from ipaddress import IPv4Address, IPv6Address
from ipaddress import ip_address as parse_ip
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.logging import request_id_ctx
from app.models.audit import AuditLog, RecordVersion
from app.models.enums import AuditAction

SENSITIVE_FIELDS = {"hashed_password", "mfa_secret", "hashed_key"}


def _jsonable(value: Any) -> Any:
    """Render a column value for a JSONB column.

    Every branch here exists because psycopg refuses the type outright: a bare `date`,
    a `Decimal`, a `UUID` or an enum member in an audit snapshot raises
    "Object of type X is not JSON serializable" and fails the whole write. Decimals
    become strings rather than floats so a price never loses precision in the audit
    trail.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    # datetime is a subclass of date, so it must be tested first.
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, IPv4Address | IPv6Address):
        return str(value)
    return str(value)


def snapshot(obj: Any) -> dict[str, Any]:
    """Column values of an ORM row, minus secrets."""
    table = obj.__table__
    return {
        column.name: _jsonable(getattr(obj, column.name, None))
        for column in table.columns
        if column.name not in SENSITIVE_FIELDS
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changed: dict[str, dict[str, Any]] = {}
    for key in set(before) | set(after):
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {"from": old, "to": new}
    changed.pop("updated_at", None)
    return changed


def _valid_ip(value: str | None) -> str | None:
    """``ip_address`` is an INET column, so a non-address value aborts the INSERT.

    The client host is not always an address: a test client sends a name, and a
    misconfigured proxy can put anything in ``X-Forwarded-For``. An unparseable value is
    dropped rather than allowed to take down the audited request - losing one field of
    context is strictly better than losing the audit row and the operation with it.
    """
    if not value:
        return None
    candidate = value.split("%", 1)[0].strip()
    try:
        return str(parse_ip(candidate))
    except ValueError:
        return None


def record_audit(
    db: Session,
    *,
    action: AuditAction,
    principal: Principal | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    entity_label: str | None = None,
    summary: str | None = None,
    changes: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    tenant_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    http_method: str | None = None,
    http_path: str | None = None,
    status_code: int | None = None,
    actor_type: str = "user",
) -> AuditLog:
    """Append one audit row. Never raises on missing optional context."""
    entry = AuditLog(
        tenant_id=tenant_id or (principal.tenant_id if principal else None),
        occurred_at=datetime.now(UTC),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        user_id=principal.user_id if principal else None,
        user_email=principal.email if principal else None,
        actor_type=principal.actor_type if principal else actor_type,
        api_key_id=principal.api_key_id if principal else None,
        summary=summary,
        changes=_jsonable(changes or {}),
        context=_jsonable(context or {}),
        request_id=request_id_ctx.get(),
        ip_address=_valid_ip(ip_address),
        user_agent=user_agent,
        http_method=http_method,
        http_path=http_path,
        status_code=status_code,
    )
    db.add(entry)
    return entry


def record_version(
    db: Session,
    *,
    obj: Any,
    operation: str,
    before: dict[str, Any] | None = None,
    principal: Principal | None = None,
    change_reason: str | None = None,
    ai_job_id: uuid.UUID | None = None,
) -> RecordVersion:
    """Snapshot a row after a mutation, with the diff that produced it."""
    entity_type = obj.__tablename__
    after = snapshot(obj)
    next_version = (
        db.scalar(
            select(func.coalesce(func.max(RecordVersion.version), 0)).where(
                RecordVersion.entity_type == entity_type,
                RecordVersion.entity_id == obj.id,
            )
        )
        or 0
    ) + 1

    version = RecordVersion(
        tenant_id=getattr(obj, "tenant_id", None),
        entity_type=entity_type,
        entity_id=obj.id,
        version=next_version,
        operation=operation,
        snapshot=after,
        diff=diff(before or {}, after),
        changed_by_user_id=principal.user_id if principal else None,
        change_reason=change_reason,
        ai_job_id=ai_job_id,
        schema_version=getattr(obj, "schema_version", None),
        created_at=datetime.now(UTC),
    )
    db.add(version)
    return version
