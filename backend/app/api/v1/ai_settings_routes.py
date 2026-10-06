"""AI provider settings: add several, activate one per role.

Its own API rather than part of the system settings, because it handles credentials and
that deserves a boundary you can point at. Every route is platform-admin only, and no
route returns a key - not decrypted, not encrypted. What comes back is a prefix, which
is enough to recognise which key is configured and useless for anything else.

Two roles, and one active configuration each:

* **search** finds candidate pages - Parallel AI, OpenAI or Claude.
* **reading** extracts fields from a captured page - Gemma, OpenAI or Claude.

They are separate because not every vendor does both, and because a run needs both
filled to work at all. A single "active AI" would either be unable to search or unable
to read, depending on which vendor it was.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.ai import providers
from app.core.deps import DbSession, PlatformAdmin
from app.core.logging import get_logger
from app.models.ai_settings import AiProviderConfig
from app.models.enums import AuditAction
from app.schemas.common import Message
from app.services import ai_settings, audit

log = get_logger(__name__)

router = APIRouter(prefix="/ai-settings", tags=["ai settings"])


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    provider: str = Field(description="parallel | openrouter | openai | anthropic")
    role: str = Field(description="search | reading")
    api_key: str = Field(min_length=8, description="Stored encrypted; never returned")
    model: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=255)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    activate: bool = Field(default=False, description="Make it the active one for its role")


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=255)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    #: Omit to keep the stored key. An empty string is treated the same way, because
    #: editing a label must not be able to destroy a credential.
    api_key: str | None = Field(default=None)


def require_table(db: DbSession) -> None:
    """Refuse with a usable message when the table has not been migrated yet.

    A dependency rather than a check inside each handler: guarding only the list route
    meant Save still failed with an unhandled UndefinedTable, which reached the browser
    as a bare 500 while the page helpfully displayed the setup instructions right
    underneath it. Anything added here later inherits the guard.

    503 because it is a deployment step that has not happened, not something wrong with
    the request.
    """
    if not ai_settings.is_installed(db):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, ai_settings.SETUP_HINT)


#: Every route that touches the table. `/options` and the list route are excluded: the
#: first needs no table, and the second reports the missing table as data so the screen
#: can render the instructions.
TableRequired = Depends(require_table)


def _get(db: DbSession, config_id: uuid.UUID) -> AiProviderConfig:
    config = db.get(AiProviderConfig, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AI provider configuration not found")
    return config


@router.get("/options")
def options(principal: PlatformAdmin) -> dict[str, Any]:
    """What the screen needs to build its form, so it hardcodes nothing.

    A vendor that cannot fill a role must not be offerable for it - refusing at the form
    is better than a sweep failing an hour in because Parallel AI was asked to read.
    """
    return {
        "roles": list(ai_settings.ROLES),
        "providers_by_role": {
            role: list(names) for role, names in ai_settings.PROVIDERS_BY_ROLE.items()
        },
        "default_models": ai_settings.DEFAULT_MODELS,
        "labels": {
            "parallel": "Parallel AI",
            "openrouter": "Gemma (OpenRouter)",
            "openai": "OpenAI",
            "anthropic": "Claude",
        },
    }


@router.get("/providers")
def list_providers(principal: PlatformAdmin, db: DbSession) -> dict[str, Any]:
    """Every configuration, plus which one is active for each role.

    Answers with 200 and ``installed: false`` when the table has not been migrated yet,
    rather than letting an UndefinedTable become a 500. The screen can then print the
    one command that fixes it; a stack trace in a red box cannot.
    """
    if not ai_settings.is_installed(db):
        return {
            "items": [],
            "active": {role: None for role in ai_settings.ROLES},
            "ready": False,
            "installed": False,
            "setup_hint": ai_settings.SETUP_HINT,
            # Host and database filled in from the running configuration; only the
            # owner's user and password are left to substitute.
            "setup_command": ai_settings.setup_command(),
        }

    configs = ai_settings.list_configs(db)
    active = {
        role: next(
            (ai_settings.as_dict(c) for c in configs if c.role == role and c.is_active), None
        )
        for role in ai_settings.ROLES
    }
    return {
        "installed": True,
        "items": [ai_settings.as_dict(config) for config in configs],
        "active": active,
        # Said plainly, because a run cannot start without both and the screen should
        # explain that rather than the run failing later.
        "ready": all(active[role] is not None for role in ai_settings.ROLES),
    }


@router.post("/providers", status_code=status.HTTP_201_CREATED, dependencies=[TableRequired])
def create_provider(
    payload: ProviderCreate, principal: PlatformAdmin, db: DbSession
) -> dict[str, Any]:
    try:
        config = ai_settings.create(
            db,
            label=payload.label,
            provider=payload.provider,
            role=payload.role,
            api_key=payload.api_key,
            model=payload.model,
            base_url=payload.base_url,
            timeout_seconds=payload.timeout_seconds,
            activate=payload.activate,
            user_id=principal.user_id,
        )
    except ai_settings.AiSettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="ai_provider_configs",
        entity_id=config.id,
        entity_label=config.label,
        # The key itself is never logged, only that one was set.
        summary=f"Added {config.provider} configuration {config.label!r} for {config.role}",
        context={"provider": config.provider, "role": config.role, "model": config.model},
    )
    db.commit()
    return ai_settings.as_dict(config)


@router.patch("/providers/{config_id}", dependencies=[TableRequired])
def update_provider(
    config_id: uuid.UUID, payload: ProviderUpdate, principal: PlatformAdmin, db: DbSession
) -> dict[str, Any]:
    config = _get(db, config_id)
    try:
        ai_settings.update(
            db,
            config,
            label=payload.label,
            model=payload.model,
            base_url=payload.base_url,
            timeout_seconds=payload.timeout_seconds,
            api_key=payload.api_key,
        )
    except ai_settings.AiSettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="ai_provider_configs",
        entity_id=config.id,
        entity_label=config.label,
        summary=(
            f"Updated configuration {config.label!r}"
            + (" and replaced its API key" if payload.api_key else "")
        ),
    )
    db.commit()
    return ai_settings.as_dict(config)


@router.post("/providers/{config_id}/activate", dependencies=[TableRequired])
def activate_provider(
    config_id: uuid.UUID, principal: PlatformAdmin, db: DbSession
) -> dict[str, Any]:
    """Make this the one used for its role. The previous one is deactivated."""
    config = _get(db, config_id)
    previous = ai_settings.active_config(db, config.role)
    ai_settings.activate_config(db, config)

    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="ai_provider_configs",
        entity_id=config.id,
        entity_label=config.label,
        summary=(
            f"Activated {config.provider} for {config.role}"
            + (f", replacing {previous.label!r}" if previous and previous.id != config.id else "")
        ),
        context={"role": config.role, "provider": config.provider, "model": config.model},
    )
    db.commit()
    return ai_settings.as_dict(config)


@router.post("/providers/{config_id}/check", dependencies=[TableRequired])
def check_provider(config_id: uuid.UUID, principal: PlatformAdmin, db: DbSession) -> dict[str, Any]:
    """Make one real, tiny call to confirm the credential works.

    Worth the cost of one request: the alternative is discovering a dead key an hour
    into a sweep, having already paid for the searches it did.
    """
    config = _get(db, config_id)
    ok, detail = True, "Credential accepted."
    try:
        client = providers._from_config(config)
        if config.role == "reading":
            result = client.complete(  # type: ignore[union-attr]
                "Reply with JSON only.",
                'Return exactly {"ok": true}',
                max_tokens=32,
            )
            ok = result.data is not None or bool(result.text)
            detail = f"Answered in {result.latency_ms} ms using {result.model}."
        else:
            run = client.search(  # type: ignore[union-attr]
                "API 610 centrifugal pump datasheet", max_results=1
            )
            ok = True
            detail = f"Returned {len(run.results)} result(s) in {run.latency_ms} ms."
    except Exception as exc:  # noqa: BLE001 - the point is to report any failure
        ok = False
        detail = f"{type(exc).__name__}: {exc}"[:400]

    ai_settings.record_check(db, config, ok=ok, detail=detail)
    db.commit()
    log.info("ai_settings.checked", label=config.label, ok=ok)
    return {"ok": ok, "detail": detail, **ai_settings.as_dict(config)}


@router.delete("/providers/{config_id}", response_model=Message, dependencies=[TableRequired])
def delete_provider(config_id: uuid.UUID, principal: PlatformAdmin, db: DbSession) -> Message:
    config = _get(db, config_id)
    was_active = config.is_active
    label, role = config.label, config.role
    ai_settings.delete(db, config)

    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="ai_provider_configs",
        entity_id=config_id,
        entity_label=label,
        summary=f"Deleted configuration {label!r}"
        + (f" - {role} now has no active provider" if was_active else ""),
    )
    db.commit()
    return Message(
        detail=(
            f"Deleted {label!r}. Nothing is active for {role} now, so AI search will not "
            "run until another is activated."
            if was_active
            else f"Deleted {label!r}."
        )
    )
