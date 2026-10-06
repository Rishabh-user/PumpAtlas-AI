"""Storing AI provider credentials in the database, safely.

Moving keys out of `.env` and into a settings screen is a real convenience - an operator
can switch model without a deploy - and it moves a secret from a file on one machine
into a hosted database. Three things make that acceptable rather than reckless:

* **Encrypted at rest.** The column holds Fernet ciphertext, so a database dump, a
  replica, a backup or the admin table browser yields nothing usable.
* **Write-only.** No endpoint returns a key, decrypted or otherwise. The screen shows a
  prefix, which is how a person recognises a key and how the vendors display them too.
* **Derived from a secret that is not in the database.** The encryption key comes from
  ``SECRET_KEY``, which stays in the environment. That is the one credential that cannot
  move to a settings page: something has to be able to decrypt the others, and if it
  lived beside them then obtaining the database would be enough.

So `SECRET_KEY` deliberately stays in `.env` after this change. Rotating it makes every
stored provider key unreadable, which is the correct behaviour - they must be re-entered
rather than silently failing later.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.ai_settings import AiProviderConfig

log = get_logger(__name__)

#: Roles a configuration can fill. Separate because the two halves of a run fail for
#: different reasons and not every vendor does both.
ROLES = ("search", "reading")

#: Which vendors can fill which role. Parallel AI only searches; Gemma via OpenRouter
#: only reads; OpenAI and Anthropic do both.
#: Anthropic first in both roles: it is the platform default, so it is what the form
#: preselects and what an operator gets by accepting the defaults.
PROVIDERS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "search": ("anthropic", "openai", "parallel"),
    "reading": ("anthropic", "openai", "openrouter"),
}

#: Sensible model defaults, offered by the API so the screen can prefill rather than
#: asking an operator to remember model identifiers.
DEFAULT_MODELS: dict[str, str | None] = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "openrouter": "google/gemma-3-27b-it",
    "parallel": None,
}


class AiSettingsError(RuntimeError):
    """A configuration that cannot be stored or used as asked."""


def _fernet() -> Fernet:
    """The encryption key, derived from ``SECRET_KEY``.

    SHA-256 of the secret, urlsafe-base64 encoded, which is the shape Fernet requires.
    Derivation rather than reuse means the signing secret and the encryption key are not
    literally the same bytes, so a JWT does not carry material related to the key that
    protects provider credentials.
    """
    secret = (settings.SECRET_KEY or "").encode("utf-8")
    if len(secret) < 16:
        raise AiSettingsError(
            "SECRET_KEY is too short to derive an encryption key from. Set a long, "
            "random SECRET_KEY before storing provider credentials."
        )
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def encrypt_key(plaintext: str) -> tuple[str, str]:
    """Encrypt a provider key. Returns (ciphertext, displayable hint)."""
    cleaned = (plaintext or "").strip()
    if not cleaned:
        raise AiSettingsError("An API key is required.")
    token = _fernet().encrypt(cleaned.encode("utf-8")).decode("ascii")
    # Enough to recognise which key this is, far too little to use. Vendor prefixes are
    # themselves ~8 characters ("sk-proj-"), so a fixed slice would show only the
    # prefix and identify nothing.
    hint = f"{cleaned[:6]}…{cleaned[-4:]}" if len(cleaned) > 14 else f"{cleaned[:3]}…"
    return token, hint


def decrypt_key(config: AiProviderConfig) -> str:
    """The plaintext key, for making a provider call. Never returned by the API."""
    try:
        return _fernet().decrypt(config.encrypted_api_key.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise AiSettingsError(
            f"The stored key for {config.label!r} cannot be decrypted. This happens when "
            "SECRET_KEY has changed since it was saved; re-enter the key."
        ) from exc


def validate(provider: str, role: str, model: str | None) -> None:
    """Refuse a combination that cannot work, at the point it is entered.

    Better here than at run time: a sweep that fails an hour in because Parallel AI was
    asked to read a page has already cost the searches it did.
    """
    if role not in ROLES:
        raise AiSettingsError(f"Unknown role {role!r}. Expected one of: {', '.join(ROLES)}.")
    allowed = PROVIDERS_BY_ROLE[role]
    if provider not in allowed:
        raise AiSettingsError(
            f"{provider!r} cannot do {role}. For {role}, choose one of: {', '.join(allowed)}."
        )
    if provider != "parallel" and not (model or "").strip():
        raise AiSettingsError(f"A model is required for {provider!r}.")


def is_installed(db: Session) -> bool:
    """Whether the configuration table exists yet.

    The application role has no DDL rights by design, so the table arrives through a
    migration applied by the schema owner. Until then the screen should say so - an
    unhandled UndefinedTable reaches the browser as a 500 and tells nobody what to do.
    """
    return bool(db.scalar(text("SELECT to_regclass('public.ai_provider_configs') IS NOT NULL")))


def setup_command() -> str:
    """The exact command to create the table, with this installation's host filled in.

    Only the owner's user and password are left as placeholders - everything else is
    read from the running configuration, because a hand-assembled connection string is
    where this goes wrong. The password is never included: the application connects as
    ``pumpatlas_app``, which has no DDL rights, and the owner's credential is not
    something the service holds.
    """
    target = settings.database_host_summary
    return (
        "python scripts/apply_schema.py "
        f'--url "postgresql://OWNER:PASSWORD@{target}?sslmode={settings.POSTGRES_SSLMODE}" '
        "--file db/migrations/001_ai_provider_configs.sql"
    )


SETUP_HINT = (
    "The ai_provider_configs table does not exist yet. Apply it as the schema owner - "
    "the application role cannot create tables by design."
)


def list_configs(db: Session, role: str | None = None) -> list[AiProviderConfig]:
    stmt = select(AiProviderConfig).order_by(
        AiProviderConfig.role, AiProviderConfig.is_active.desc(), AiProviderConfig.label
    )
    if role:
        stmt = stmt.where(AiProviderConfig.role == role)
    return list(db.scalars(stmt).all())


def active_config(db: Session, role: str) -> AiProviderConfig | None:
    """The configuration currently doing this role, or None."""
    return db.scalar(
        select(AiProviderConfig).where(
            AiProviderConfig.role == role, AiProviderConfig.is_active.is_(True)
        )
    )


def create(
    db: Session,
    *,
    label: str,
    provider: str,
    role: str,
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int | None = None,
    activate: bool = False,
    user_id: uuid.UUID | None = None,
) -> AiProviderConfig:
    validate(provider, role, model)
    token, hint = encrypt_key(api_key)

    config = AiProviderConfig(
        label=label.strip(),
        provider=provider,
        role=role,
        model=(model or "").strip() or None,
        encrypted_api_key=token,
        key_hint=hint,
        base_url=(base_url or "").strip() or None,
        timeout_seconds=timeout_seconds,
        is_active=False,
        created_by_user_id=user_id,
    )
    db.add(config)
    db.flush()
    if activate:
        activate_config(db, config)
    return config


def update(
    db: Session,
    config: AiProviderConfig,
    *,
    label: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int | None = None,
    api_key: str | None = None,
) -> AiProviderConfig:
    """Change a configuration. The key is replaced only when a new one is supplied.

    An empty key field means "leave it alone", not "clear it" - otherwise editing a
    label would silently destroy the credential.
    """
    if label is not None:
        config.label = label.strip()
    if model is not None:
        config.model = model.strip() or None
    if base_url is not None:
        config.base_url = base_url.strip() or None
    if timeout_seconds is not None:
        config.timeout_seconds = timeout_seconds
    if api_key and api_key.strip():
        config.encrypted_api_key, config.key_hint = encrypt_key(api_key)
        # A new key has not been checked yet; saying otherwise would be stale.
        config.last_checked_at = None
        config.last_check_ok = None
        config.last_check_detail = None

    validate(config.provider, config.role, config.model)
    db.flush()
    return config


def activate_config(db: Session, config: AiProviderConfig) -> AiProviderConfig:
    """Make this the active configuration for its role, deactivating the previous one.

    Both writes happen in one transaction, and the partial unique index would reject the
    pair if the order were wrong - so a failure here leaves the previous provider active
    rather than leaving the role with none.
    """
    current = active_config(db, config.role)
    if current is not None and current.id != config.id:
        current.is_active = False
        # Flushed before the new one is set, or the partial unique index sees two.
        db.flush()
    config.is_active = True
    db.flush()
    log.info(
        "ai_settings.activated", role=config.role, provider=config.provider, label=config.label
    )
    return config


def delete(db: Session, config: AiProviderConfig) -> None:
    """Remove a configuration.

    Deleting the active one is allowed but leaves the role unfilled, which stops
    discovery until another is activated - so the API says so rather than silently
    breaking the next run.
    """
    db.delete(config)
    db.flush()


def record_check(
    db: Session, config: AiProviderConfig, *, ok: bool, detail: str | None
) -> AiProviderConfig:
    config.last_checked_at = datetime.now(UTC)
    config.last_check_ok = ok
    config.last_check_detail = (detail or "")[:500] or None
    db.flush()
    return config


def as_dict(config: AiProviderConfig) -> dict[str, Any]:
    """The API representation. No key material, encrypted or otherwise."""
    return {
        "id": str(config.id),
        "label": config.label,
        "provider": config.provider,
        "role": config.role,
        "model": config.model,
        "base_url": config.base_url,
        "timeout_seconds": config.timeout_seconds,
        "is_active": config.is_active,
        "key_hint": config.key_hint,
        "last_checked_at": (config.last_checked_at.isoformat() if config.last_checked_at else None),
        "last_check_ok": config.last_check_ok,
        "last_check_detail": config.last_check_detail,
        "created_at": config.created_at.isoformat() if config.created_at else None,
    }
