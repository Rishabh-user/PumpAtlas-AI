"""Configured AI providers, managed from the platform rather than from a file.

Deliberately *not* tenant scoped. Which model reads a datasheet is an operational choice
about cost, speed and quality for the whole installation, not something one customer
should be able to change for everyone else.

The API key is stored encrypted and is never read back out to a browser - see
:mod:`app.services.ai_settings` for the reasoning and the key derivation. The column
holds ciphertext, so it is also listed in the admin table browser's redaction set: a
page that can display any table must not become the way an encrypted secret is read.

One row per configuration, and at most one active per role. The uniqueness of "active"
is enforced by a partial unique index rather than by application code, because two
active search providers is not a state the platform can be in - the runner would have
to pick one arbitrarily and the screen would show something untrue.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class AiProviderConfig(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ai_provider_configs"

    #: What the operator called it, so several configurations of one vendor are
    #: distinguishable ("GPT-4o mini (cheap)" against "GPT-4o (accurate)").
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Which vendor contract to speak: openrouter | openai | anthropic | parallel.
    #: Validated against `app.ai.providers` at the API boundary rather than by a
    #: database enum, so adding a provider does not need a migration.
    provider: Mapped[str] = mapped_column(String(40), nullable=False)

    #: What this configuration is for: "search" finds pages, "reading" extracts fields
    #: from one. Kept separate because the two roles fail differently and not every
    #: vendor does both - Parallel AI only searches, Gemma only reads.
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    #: Empty for a search provider that takes no model (Parallel AI).
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: Fernet ciphertext. Never returned by the API.
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)

    #: First few characters of the plaintext key, kept so the screen can show *which*
    #: key is configured without being able to reveal it. A prefix is what a person
    #: recognises a key by, and it is what vendors themselves display.
    key_hint: Mapped[str | None] = mapped_column(String(24), nullable=True)

    #: Overrides the vendor default when an operator points at a gateway or a region.
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    timeout_seconds: Mapped[int | None] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Result of the last credential check, so a key that has stopped working is
    #: visible before a 150-page sweep discovers it.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_check_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("label", "role", name="uq_ai_provider_configs_label_role"),
        # At most one active configuration per role. A partial unique index is the only
        # way to say that in the schema; doing it in Python would leave the invariant to
        # whichever request happened to run last.
        Index(
            "uq_ai_provider_configs_one_active_per_role",
            "role",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
