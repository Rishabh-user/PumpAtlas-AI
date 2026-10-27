"""PumpAtlas AI - FastAPI application entry point."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from kombu.exceptions import OperationalError as KombuOperationalError
from prometheus_client import Counter, Histogram
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import check_database
from app.core.logging import configure_logging, get_logger, request_id_ctx

configure_logging(settings.LOG_LEVEL, json_logs=settings.is_production)
log = get_logger(__name__)

REQUEST_COUNT = Counter(
    "pumpatlas_http_requests_total",
    "HTTP requests handled",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "pumpatlas_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
)

DESCRIPTION = """
**Oil & Gas Pump Intelligence Platform** by Targeticon.

Multi-tenant product, vendor and procurement intelligence for industrial pumps.

* **PostgreSQL is the system of record.** Every value is a row, with a version history.
* **AI is an assistant layer.** OpenRouter-hosted Gemma extracts, normalises, classifies
  and quality-checks; Parallel AI orchestrates web discovery. Neither writes to the
  database directly.
* **Everything is traceable.** Each field carries provenance: the source, the evidence
  quote, the model, the confidence and who approved it - see
  `/pump-models/{id}/provenance`.

### Authentication
`POST /auth/login` returns a bearer token. Machine integrations use `X-API-Key`.
Platform staff may scope a request to a tenant with the `X-Tenant-Id` header.

### Tenant isolation
Enforced twice: PostgreSQL row level security keyed on the transaction's tenant GUC,
and application-level filtering. A query that forgets the filter still cannot cross a
tenant boundary.
"""


def _reap_interrupted_discovery() -> None:
    """An in-process discovery run cannot survive this restart, so stop it claiming to.

    Best-effort: a failure here must not stop the API from starting.
    """
    try:
        from app.core.db import tenant_session
        from app.services import discovery

        # Platform-admin scope: interrupted runs belong to every tenant, and this is a
        # process-lifecycle chore rather than a tenant action.
        with tenant_session(None, is_platform_admin=True) as db:
            discovery.reap_interrupted_runs(db)
    except Exception as exc:
        log.warning("startup.reap_failed", error=str(exc)[:200])


def _warn_on_schema_drift() -> None:
    """Say at boot which mapped tables the database does not have.

    An unapplied migration does not announce itself, and every layer above it handles
    the absence politely. `chat_conversations` and `chat_turns` were missing for weeks:
    `/chat/conversations` returned 500, the sidebar rendered the same "no conversations
    yet" it shows a new account, and `record_api_ask` caught its own exception so API
    questions went unlogged too. Three best-effort handlers, and nothing anywhere that
    said *the table is not there*. The schema was found by going looking.

    So the server says it once, on the way up, where a restart puts it in front of
    whoever is working. Best-effort: a database that cannot answer this is already
    reported by `check_database`, and a failure here must not stop the API starting.
    """
    try:
        from sqlalchemy import text

        from app.core.db import tenant_session
        from app.models import Base

        with tenant_session(None, is_platform_admin=True) as db:
            present = set(
                db.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                ).all()
            )
        missing = sorted(
            table.name
            for table in Base.metadata.sorted_tables
            if table.name not in present
        )
        if not missing:
            return
        log.error(
            "startup.schema_drift",
            missing_tables=missing,
            detail=(
                f"{len(missing)} mapped table(s) do not exist, so the features that "
                "use them fail quietly. Apply the matching file from db/migrations/ as "
                "the schema owner, then re-check with "
                "`python -m scripts.check_schema_drift`."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - a check must not stop the API starting
        log.warning("startup.schema_check_failed", error=str(exc)[:200])


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "startup",
        environment=settings.ENVIRONMENT,
        ai_enabled=settings.AI_ENABLED,
        storage="s3" if settings.use_s3 else "local",
    )
    if settings.wildcard_cors_in_production:
        # `cors_origins` dropped it rather than honour a credentialed wildcard, so
        # cross-origin calls now fail. Said once, loudly, because the symptom shows up
        # in a browser console and the cause is in an environment variable.
        log.error(
            "startup.cors_wildcard_refused",
            detail=(
                "CORS_ORIGINS is '*', which with credentials lets any site call this "
                "API as a signed-in user. It has been ignored and cross-origin calls "
                "will be refused. Set CORS_ORIGINS to the frontend's origin, e.g. "
                "https://pumpatlas-web.onrender.com"
            ),
        )
    if not check_database():
        # A missing database is a deployment problem, not a reason to crash-loop:
        # /ready reports it and the orchestrator can hold traffic back.
        log.error("startup.database_unreachable", url_host=settings.POSTGRES_HOST)
    else:
        _warn_on_schema_drift()
        _reap_interrupted_discovery()
    yield
    log.info("shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={"name": "Targeticon", "url": "https://targeticon.com"},
)

def custom_openapi() -> dict:
    """Advertise the API key as a credential, not as a stray header.

    The generated schema only ever declared `HTTPBearer`, so Swagger's Authorize dialog
    offered a bearer token - the browser session's own credential - and `X-API-Key`
    appeared as an unexplained header parameter on every operation. An integrator
    reading that page concludes they need a JWT. They do not: a key alone authenticates,
    and the tenant it belongs to is what scopes the answer.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["ApiKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": (
            "A key issued to one client. It carries that client's tenant for its whole "
            "life, so no X-Tenant-Id header is needed - send it only as platform staff "
            "narrowing yourself to one client's view."
        ),
    }
    # Either credential opens the door; neither requires the other.
    schema["security"] = [{"ApiKeyHeader": []}, {"HTTPBearer": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Correlation id, structured access log and Prometheus timing."""
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request_id_ctx.set(request_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        REQUEST_COUNT.labels(request.method, request.url.path, "500").inc()
        log.exception("request.unhandled", method=request.method, path=request.url.path)
        raise

    duration = time.perf_counter() - started
    # Label with the route template, not the raw path, so cardinality stays bounded.
    route = request.scope.get("route")
    path_label = getattr(route, "path", request.url.path)
    REQUEST_COUNT.labels(request.method, path_label, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, path_label).observe(duration)
    response.headers["X-Request-Id"] = request_id

    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Field-level validation errors, phrased for an API consumer."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Request validation failed",
            "errors": [
                {
                    "field": ".".join(str(part) for part in error["loc"][1:]),
                    "message": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors()
            ],
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError):
    """A constraint violation is a conflict, not a server error."""
    log.warning("db.integrity_error", detail=str(exc.orig)[:300])
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": (
                "The write conflicts with existing data - most often a duplicate "
                "vendor, pump model or spec version."
            ),
            "database_error": str(exc.orig)[:300],
        },
    )


@app.exception_handler(KombuOperationalError)
async def broker_handler(request: Request, exc: KombuOperationalError):
    """A dead Celery broker is a 503, not a 500.

    Endpoints that queue work would otherwise surface a stack trace. Synchronous
    endpoints - search, manual entry, comparison, audit - are unaffected and keep working.
    """
    log.error("celery.broker_unavailable", detail=str(exc)[:200])
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": (
                "Background job processing is unavailable: the task broker cannot be "
                "reached. Data already stored is unaffected, and synchronous endpoints "
                "continue to work. Set CELERY_TASK_ALWAYS_EAGER=true to run jobs inline "
                "for local development."
            )
        },
    )


@app.exception_handler(OperationalError)
async def operational_handler(request: Request, exc: OperationalError):
    log.error("db.operational_error", detail=str(exc.orig)[:300])
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The database is unavailable. Retry shortly."},
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "service": settings.PROJECT_NAME,
        "description": "Oil & Gas Pump Intelligence Platform",
        "version": "0.1.0",
        "docs": "/docs",
        "api": settings.API_V1_PREFIX,
    }
