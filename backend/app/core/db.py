"""SQLAlchemy engine / session plumbing.

Tenant isolation is enforced twice, on purpose:

1. **Database layer** - PostgreSQL row level security policies compare `tenant_id`
   against the `app.tenant_id` GUC (see ``db/rls.sql``).
2. **Application layer** - repository helpers always filter on the resolved tenant.

``tenant_session`` sets the GUC for the life of the transaction so both layers agree.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.sqlalchemy_url,
    # A managed database drops idle connections; pre-ping turns that into a transparent
    # reconnect instead of a failed request.
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS},
    echo=settings.DB_ECHO,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _set_statement_timeout(dbapi_conn, _record):  # pragma: no cover - needs live DB
    """Bound every query and every open transaction.

    Without these, one runaway extraction query can hold a connection from a small
    managed pool indefinitely and starve the whole API.
    """
    with dbapi_conn.cursor() as cur:
        # One statement: connection setup happens on every new pool member, and a TLS
        # handshake to a hosted database already costs about a second.
        cur.execute(
            f"SET statement_timeout = '{settings.DB_STATEMENT_TIMEOUT}';"
            " SET idle_in_transaction_session_timeout = '60s';"
        )


TENANT_CONTEXT_KEY = "pumpatlas_tenant_context"


# Both settings in one statement. Two separate round trips here cost 4 per request
# once the after_begin hook is counted, which is material against a remote database.
_SET_TENANT_GUC = text(
    "SELECT set_config('app.tenant_id', :tid, true),"
    "       set_config('app.is_platform_admin', :flag, true)"
)


def _apply_guc(connection, tenant_id: UUID | str | None, is_platform_admin: bool) -> None:
    connection.execute(
        _SET_TENANT_GUC,
        {
            "tid": str(tenant_id) if tenant_id else "",
            "flag": "on" if is_platform_admin else "off",
        },
    )


@event.listens_for(Session, "after_begin")
def _reapply_tenant_guc(session: Session, transaction, connection) -> None:
    """Re-bind the tenant on every new transaction of a session.

    ``set_config(..., true)`` is transaction-local, which is what makes it safe with a
    connection pool - it cannot leak into the next request. But it also means a
    ``commit()`` discards it, so a handler that commits and then reads again (the common
    create-then-refresh pattern) would run with no tenant and be denied by RLS.

    Re-applying it here keeps the setting transaction-scoped *and* survives commits.
    """
    context = session.info.get(TENANT_CONTEXT_KEY)
    if context is None:
        return
    tenant_id, is_platform_admin = context
    _apply_guc(connection, tenant_id, is_platform_admin)


def current_tenant_id(session: Session) -> UUID | str | None:
    """The tenant this session is bound to, or None for an unscoped platform admin.

    Needed by any service that *writes* a tenant-scoped row it derived rather than read:
    a scorecard computed for tenant A over a shared-master pump model belongs to A, and
    the source row's own ``tenant_id`` (NULL, for shared master) is the wrong answer.
    """
    context = session.info.get(TENANT_CONTEXT_KEY)
    return context[0] if context else None


def set_tenant_guc(
    session: Session, tenant_id: UUID | str | None, is_platform_admin: bool = False
) -> None:
    """Bind this session to a tenant for RLS purposes, for all its transactions."""
    session.info[TENANT_CONTEXT_KEY] = (tenant_id, is_platform_admin)
    # Apply immediately: a transaction may already be open, in which case the
    # after_begin hook has been and gone.
    _apply_guc(session, tenant_id, is_platform_admin)


@contextmanager
def tenant_session(
    tenant_id: UUID | str | None = None, is_platform_admin: bool = False
) -> Iterator[Session]:
    """Session context manager used by workers and scripts."""
    session = SessionLocal()
    try:
        set_tenant_guc(session, tenant_id, is_platform_admin)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover
        return False
