"""A person's chat history: the threads they have had with the record.

Separate from ``chat_routes`` on purpose. ``/chat/ask`` reads the record and writes
nothing; this module only stores what a person asked and what came back, so they can
return to it. A conversation is a transcript, not evidence - nothing here feeds search,
scoring or a spec field, and the only route from an answer to a stored fact is still the
capture pipeline.

A person's own threads are private to them, even within a tenant. Row level security
isolates tenants; ``chat_log.visible_to`` isolates colleagues. The one exception is a
thread an API key started (see ``services/chat_log``): platform staff and a tenant's
administrators can read those, and each carries a tenant tag so it is clear which tenant
asked.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.chat import ChatConversation, ChatTurn
from app.schemas.common import Message
from app.services import chat_log

router = APIRouter(prefix="/chat/conversations", tags=["chat"])

#: Keeps a person's history to a size the sidebar can show. The oldest are shed, as the
#: browser-side store did, so the list stays something a person can scan.
MAX_CONVERSATIONS_PER_USER = 100
TITLE_MAX = chat_log.TITLE_MAX


class TurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    answer: dict[str, Any] | None = Field(
        default=None, description="The answer exactly as /chat/ask returned it"
    )
    failed: str | None = Field(default=None, max_length=2000)


class ConversationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    turn: TurnIn | None = Field(
        default=None, description="The first turn, so a thread is created and filled in one call"
    )


def _turn_out(turn: ChatTurn) -> dict[str, Any]:
    return {
        "question": turn.question,
        "answer": turn.answer,
        "failed": turn.failed,
    }


def _summary(
    row: ChatConversation, turn_count: int, tags: dict[Any, dict[str, Any]]
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "updated_at": row.updated_at.isoformat(),
        "turn_count": turn_count,
        # Which tenant had this conversation, and whether a person or an API key did.
        "tenant": tags.get(row.tenant_id) or tags[None],
        "source": row.source,
        "source_label": row.source_label,
    }


def _find(
    db: DbSession, conversation_id: uuid.UUID, principal: CurrentPrincipal
) -> ChatConversation:
    """A conversation this principal may see. Someone else's is a 404, not a 403."""
    row = db.get(ChatConversation, conversation_id)
    if row is None or not chat_log.may_see(row, principal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return row


def _own(
    db: DbSession, conversation_id: uuid.UUID, principal: CurrentPrincipal
) -> ChatConversation:
    """A conversation this user started themselves - the only kind they may add to."""
    row = _find(db, conversation_id, principal)
    if row.source != chat_log.SOURCE_APP or row.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return row


def _append(db: DbSession, row: ChatConversation, payload: TurnIn) -> ChatTurn:
    position = (
        db.scalar(select(func.max(ChatTurn.position)).where(ChatTurn.conversation_id == row.id))
        or 0
    ) + 1
    turn = ChatTurn(
        tenant_id=row.tenant_id,
        conversation_id=row.id,
        position=position,
        question=payload.question,
        answer=payload.answer,
        failed=payload.failed,
    )
    db.add(turn)
    # `onupdate` only fires when the row itself changes, and appending a turn does not
    # touch it - so the thread would sort by when it was created, not last used.
    row.updated_at = func.now()
    return turn


@router.get("", dependencies=[Depends(require("search", "read"))])
def list_conversations(principal: CurrentPrincipal, db: DbSession) -> list[dict[str, Any]]:
    """Threads this user may see, most recently used first. Titles only - turns load on open."""
    counts = (
        select(ChatTurn.conversation_id, func.count(ChatTurn.id).label("n"))
        .group_by(ChatTurn.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(ChatConversation, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.conversation_id == ChatConversation.id)
        .where(chat_log.visible_to(principal))
        .order_by(ChatConversation.updated_at.desc())
        .limit(MAX_CONVERSATIONS_PER_USER)
    ).all()
    tags = chat_log.tenant_tags(db, [row for row, _ in rows])
    return [_summary(row, int(n), tags) for row, n in rows]


@router.post(
    "", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require("search", "read"))]
)
def create_conversation(
    payload: ConversationIn, principal: CurrentPrincipal, db: DbSession
) -> dict[str, Any]:
    if principal.user_id is None:
        # An API key has no person behind it, so there is nobody to keep a history for.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Conversation history belongs to a signed-in user"
        )
    row = ChatConversation(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        source=chat_log.SOURCE_APP,
        title=payload.title.strip()[:TITLE_MAX] or "New conversation",
    )
    db.add(row)
    db.flush()
    if payload.turn is not None:
        _append(db, row, payload.turn)

    # Shed the oldest beyond the cap, so history cannot grow without bound.
    stale = db.scalars(
        select(ChatConversation.id)
        .where(ChatConversation.user_id == principal.user_id)
        .order_by(ChatConversation.updated_at.desc())
        .offset(MAX_CONVERSATIONS_PER_USER)
    ).all()
    for old_id in stale:
        old = db.get(ChatConversation, old_id)
        if old is not None:
            db.delete(old)

    db.commit()
    db.refresh(row)
    return _summary(
        row, 1 if payload.turn is not None else 0, chat_log.tenant_tags(db, [row])
    )


@router.get("/{conversation_id}", dependencies=[Depends(require("search", "read"))])
def get_conversation(
    conversation_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> dict[str, Any]:
    row = _find(db, conversation_id, principal)
    tags = chat_log.tenant_tags(db, [row])
    return {**_summary(row, len(row.turns), tags), "turns": [_turn_out(t) for t in row.turns]}


@router.post(
    "/{conversation_id}/turns",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("search", "read"))],
)
def add_turn(
    conversation_id: uuid.UUID, payload: TurnIn, principal: CurrentPrincipal, db: DbSession
) -> dict[str, Any]:
    row = _own(db, conversation_id, principal)
    turn = _append(db, row, payload)
    db.commit()
    return _turn_out(turn)


@router.delete(
    "/{conversation_id}",
    response_model=Message,
    dependencies=[Depends(require("search", "read"))],
)
def delete_conversation(
    conversation_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> Message:
    # A key may read what it asked and not erase it. The point of logging an API
    # thread is that an administrator can see which tenant searched what; letting the
    # key delete its own trail would remove the only record of it. A person deleting
    # their own conversation is different - nobody else was ever meant to read it.
    if principal.api_key_id is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "An API key may read its conversation history but not delete it.",
        )
    row = _find(db, conversation_id, principal)
    db.delete(row)
    db.commit()
    return Message(detail="Conversation deleted")
