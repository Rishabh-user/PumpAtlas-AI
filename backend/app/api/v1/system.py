"""Health, readiness, metadata and metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from app.ai.openrouter import OpenRouterClient
from app.ai.parallel_search import ParallelSearchClient
from app.core.config import settings
from app.core.countries import PUMP_SUPPLY_COUNTRIES, as_options
from app.core.deps import DbSession, require
from app.models import enums
from app.schemas.specs import ALL_TRACKED_FIELDS, SPEC_FIELDS
from app.services import ai_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness. Deliberately dependency-free so it never fails on a DB blip.

    Reports the allowed browser origins too. A blocked cross-origin call surfaces
    in the browser as "TypeError: Failed to fetch" with no response to inspect —
    identical to the API being down — so the one fact that separates the two
    belongs somewhere a developer can read without shell access to the server.
    """
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "cors_origins": settings.cors_origins,
    }


@router.get("/ready")
def ready(db: DbSession, response: Response) -> dict:
    """Readiness. Reports every dependency; degraded if the database is unreachable."""
    checks: dict[str, dict] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["postgres"] = {"status": "ok", "required": True}
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        checks["postgres"] = {"status": "error", "required": True, "detail": str(exc)[:200]}

    try:
        import redis

        redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
        checks["redis"] = {"status": "ok", "required": True}
    except Exception as exc:  # noqa: BLE001
        # Not required when there is no queue to serve: with `CELERY_TASK_ALWAYS_EAGER`,
        # or with no worker, discovery runs in the API process instead. Reporting the
        # whole service degraded for a dependency the deployment has chosen not to use
        # makes the endpoint useless as a deployment gate.
        checks["redis"] = {
            "status": "error",
            "required": not settings.CELERY_TASK_ALWAYS_EAGER,
            "detail": str(exc)[:200],
            "note": (
                None
                if settings.CELERY_TASK_ALWAYS_EAGER
                else "Without Redis, background jobs run in the API process and do not "
                "survive a restart."
            ),
        }

    # A weak secret is only a failure where it matters. In development the default is
    # the expected value; in production it means forgeable tokens and provider
    # credentials encrypted under a published string.
    checks["secret_key"] = {
        "status": "weak" if settings.secret_key_is_weak else "ok",
        "required": settings.is_production,
        "detail": (
            "Set SECRET_KEY to at least 32 random characters: `openssl rand -hex 32`. "
            "It signs tokens and derives the key for stored AI credentials."
            if settings.secret_key_is_weak
            else None
        ),
    }

    # The AI checks read the active configuration, not the environment. Reporting
    # "not_configured" while a run is happily using Anthropic from the database is the
    # same class of lie as a progress badge naming the wrong provider.
    for role in ("search", "reading"):
        try:
            active = ai_settings.active_config(db, role) if ai_settings.is_installed(db) else None
        except Exception:  # noqa: BLE001 - readiness must report, not raise
            active = None
        if active is not None:
            checks[f"ai_{role}"] = {
                "status": "configured",
                "required": False,
                "provider": active.provider,
                "model": active.model,
                "source": "database",
            }
        else:
            env_client = ParallelSearchClient() if role == "search" else OpenRouterClient()
            checks[f"ai_{role}"] = {
                "status": "configured" if env_client.configured else "not_configured",
                "required": False,
                "provider": (
                    settings.SEARCH_PROVIDER if role == "search" else settings.EXTRACTION_PROVIDER
                ),
                "model": None if role == "search" else settings.OPENROUTER_MODEL,
                "source": "environment fallback - nothing active at /ai-settings",
            }

    checks["object_storage"] = {
        "status": "s3" if settings.use_s3 else "local",
        "required": False,
        "bucket": settings.S3_BUCKET if settings.use_s3 else settings.LOCAL_STORAGE_DIR,
    }

    unhealthy = [
        name for name, check in checks.items() if check.get("required") and check["status"] != "ok"
    ]
    if unhealthy:
        response.status_code = 503
    return {
        "status": "degraded" if unhealthy else "ready",
        "failing": unhealthy,
        "checks": checks,
    }


@router.get("/meta/countries")
def countries() -> dict:
    """Every country, for a picker that stores what the schema actually accepts.

    A two-character text box invites "Uk", "usa" and "germany", none of which are alpha-2
    codes, and the extraction pipeline already has to repair those when a model returns
    them. `pump_supply` marks the countries that manufacture or service Oil & Gas pumps,
    so a form can put the likely answers first without keeping a second list.
    """
    return {
        "countries": as_options(),
        "pump_supply": list(PUMP_SUPPLY_COUNTRIES),
    }


@router.get("/meta/vocabularies")
def vocabularies() -> dict:
    """Every controlled vocabulary in the platform, for form and filter rendering."""
    return {
        name.removesuffix("Name").lower() if name.endswith("Name") else _snake(name): [
            member.value for member in enum_cls
        ]
        for name, enum_cls in vars(enums).items()
        if isinstance(enum_cls, type)
        and issubclass(enum_cls, enums.StrEnum)
        and enum_cls is not enums.StrEnum
    }


def _snake(name: str) -> str:
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


@router.get("/meta/fields", dependencies=[Depends(require("search", "read"))])
def tracked_fields() -> dict:
    """The intelligence fields the platform tracks, grouped by spec table."""
    return {
        "groups": SPEC_FIELDS,
        "field_counts": {group: len(fields) for group, fields in SPEC_FIELDS.items()},
        "total_tracked_fields": len(ALL_TRACKED_FIELDS),
        "all_fields": ALL_TRACKED_FIELDS,
    }


@router.get("/metrics")
def metrics() -> Response:
    """Prometheus exposition. Scrape target for the observability stack."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
