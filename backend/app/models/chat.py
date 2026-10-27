"""Chat conversations: a person's transcript of questions put to the record.

Kept apart from the evidence tables on purpose. A conversation is a way of interrogating
the record, not part of it: nothing said here is evidence, and nothing here is read back
into search, scoring or a spec field. The only route from an answer to a stored fact is
the capture pipeline, where a field is written with a verbatim quote from a page that
PumpAtlas fetched. These tables only let a person come back to what they asked.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey
from app.models.types import Json


class ChatConversation(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """One thread in a user's history. Private to its owner, even within a tenant."""

    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("ix_chat_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_chat_conversations_tenant_updated", "tenant_id", "updated_at"),
    )

    # Null for a thread an API key asked: no person sits behind a key, so it belongs to
    # the tenant the key acts for and is attributed to the key instead.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="app", comment="app | api_key"
    )
    source_label: Mapped[str | None] = mapped_column(
        String(160), comment="The API key's name, kept so a thread outlives its key"
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)

    turns: Mapped[list[ChatTurn]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatTurn.position",
    )


class ChatTurn(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A question and what came back, or why nothing did."""

    __tablename__ = "chat_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "position"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[dict | None] = mapped_column(
        Json,
        comment="The answer exactly as /chat/ask returned it, citations included",
    )
    failed: Mapped[str | None] = mapped_column(
        Text, comment="Set when the question failed, so a reopened thread says so"
    )

    conversation: Mapped[ChatConversation] = relationship(back_populates="turns")
