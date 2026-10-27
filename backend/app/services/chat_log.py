"""Who asked what: the transcript store behind the chat history.

Two kinds of thread land in ``chat_conversations``:

* ``app`` - a signed-in person's own conversation, written by the app through the
  ``/chat/conversations`` routes. Private to that person.
* ``api_key`` - a question another application put to ``/chat/ask`` with an API key.
  There is no person to own it, so it belongs to the tenant the key acts for and carries
  the key's name, which is what lets an administrator see *which tenant searched what*.

Neither is evidence. Nothing here is read back into search, scoring or a spec field; the
only route from an answer to a stored fact is still the capture pipeline.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.deps import Principal
from app.core.logging import get_logger
from app.models.chat import ChatConversation, ChatTurn
from app.models.tenant import Tenant
from app.models.user import ApiKey

log = get_logger(__name__)

SOURCE_APP = "app"
SOURCE_API_KEY = "api_key"
TITLE_MAX = 120


def title_for(question: str) -> str:
    flat = " ".join(question.split())
    if not flat:
        return "New conversation"
    return flat if len(flat) <= TITLE_MAX else f"{flat[: TITLE_MAX - 1]}…"


def can_review_api_threads(principal: Principal) -> bool:
    """Platform staff, and a tenant's own administrators, may read what its keys asked."""
    return principal.is_platform_admin or "admin" in (principal.roles or [])


def visible_to(principal: Principal) -> ColumnElement[bool]:
    """The rows this principal may see.

    Tenant isolation is row level security's job; this narrows within it.

    A key reads back what *that key* asked. Without the first branch it fell through to
    the personal-thread clause and compiled to ``user_id IS NULL AND source = 'app'`` -
    and a key's own threads are stored with ``source = 'api_key'``, so the clause
    excluded precisely the rows the key is entitled to and matched nothing else. An
    integration could log questions through `/chat/ask` and never read one back.

    Its own key, not its tenant's other keys: two applications sharing a tenant have no
    business reading each other's queries, and an administrator who should see all of
    them signs in and gets the `can_review_api_threads` branch instead.
    """
    if principal.api_key_id is not None:
        return ChatConversation.api_key_id == principal.api_key_id
    own = ChatConversation.user_id == principal.user_id
    if can_review_api_threads(principal):
        return or_(own, ChatConversation.source == SOURCE_API_KEY)
    return and_(own, ChatConversation.source == SOURCE_APP)


def may_see(row: ChatConversation, principal: Principal) -> bool:
    """The row-at-a-time form of `visible_to`, and it must agree with it.

    The two are deliberately kept side by side: a list that hides a thread and a fetch
    that returns it is a leak, and the reverse is a thread you can see in the list and
    cannot open.
    """
    if principal.api_key_id is not None:
        return row.api_key_id == principal.api_key_id
    if row.source == SOURCE_API_KEY:
        return can_review_api_threads(principal)
    return row.user_id is not None and row.user_id == principal.user_id


def tenant_tags(
    db: Session, rows: list[ChatConversation]
) -> dict[uuid.UUID | None, dict[str, Any]]:
    """Tenant id -> the tag the history shows beside a thread."""
    ids = {row.tenant_id for row in rows if row.tenant_id is not None}
    tags: dict[uuid.UUID | None, dict[str, Any]] = {
        None: {"id": None, "name": "Shared catalogue", "slug": None}
    }
    if ids:
        for tenant in db.scalars(select(Tenant).where(Tenant.id.in_(ids))):
            tags[tenant.id] = {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug}
    return tags


def record_api_ask(
    db: Session, principal: Principal, question: str, result: dict[str, Any]
) -> None:
    """Log a question an API key asked, with its answer, against the key's tenant.

    Best effort, and it must never fail the answer: the caller is waiting on it. A key
    with no tenant cannot be recorded - row level security gives a tenant-less principal
    no rows to write - so shared-only keys are simply not logged.
    """
    if principal.api_key_id is None or principal.tenant_id is None:
        return
    try:
        key = db.get(ApiKey, principal.api_key_id)
        row = ChatConversation(
            tenant_id=principal.tenant_id,
            user_id=None,
            api_key_id=principal.api_key_id,
            source=SOURCE_API_KEY,
            source_label=key.name if key else None,
            title=title_for(question),
        )
        db.add(row)
        db.flush()
        db.add(
            ChatTurn(
                tenant_id=row.tenant_id,
                conversation_id=row.id,
                position=1,
                question=question,
                answer=result,
                failed=None,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - logging must not take the answer down with it
        db.rollback()
        log.warning("chat_log.record_failed", exc_info=True)
