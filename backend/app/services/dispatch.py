"""Run background work through Celery when a broker is reachable, in-process when not.

Discovery takes minutes: a Parallel AI search plus one Gemma call per captured page. It
cannot run inside the request, and the UI needs to poll a durable run record while it
happens.

Celery is the right home for that, and in production it is what runs. But a local
checkout has no Redis, and `task.delay()` against an unreachable broker raises — which
would make the feature look broken rather than unconfigured. So the dispatcher probes the
broker once per process and falls back to a daemon thread with its own session.

The fallback is genuinely weaker and the run record says which path was used: work in a
thread dies with the API process, does not retry, and does not spread across workers.
Start a worker for anything beyond local use.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import get_logger

log = get_logger(__name__)

_broker_state: bool | None = None
_probe_lock = threading.Lock()


def broker_available(*, force_recheck: bool = False) -> bool:
    """True when the Celery broker answers. Cached, because probing costs a connection."""
    global _broker_state
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return True
    with _probe_lock:
        if _broker_state is not None and not force_recheck:
            return _broker_state
        try:
            from app.workers.celery_app import celery_app

            connection = celery_app.connection()
            try:
                connection.ensure_connection(max_retries=0, timeout=2)
                _broker_state = True
            finally:
                connection.release()
        except Exception as exc:
            log.info("dispatch.broker_unavailable", error=str(exc)[:200])
            _broker_state = False
        return _broker_state


def run_in_thread(
    work: Callable[..., Any],
    *,
    tenant_id: uuid.UUID | None,
    is_platform_admin: bool = False,
    name: str = "background",
    **kwargs: Any,
) -> None:
    """Run ``work(db, **kwargs)`` on a daemon thread with its own tenant-bound session."""

    def _target() -> None:
        try:
            with tenant_session(tenant_id, is_platform_admin) as db:
                work(db, **kwargs)
        except Exception:
            log.exception("dispatch.thread_failed", job=name)

    thread = threading.Thread(target=_target, name=f"pumpatlas-{name}", daemon=True)
    thread.start()


def dispatch(
    *,
    celery_task: Any,
    celery_args: tuple[Any, ...],
    fallback: Callable[..., Any],
    fallback_kwargs: dict[str, Any],
    tenant_id: uuid.UUID | None,
    name: str,
) -> dict[str, Any]:
    """Send work to Celery, or run it in-process. Returns how it was dispatched."""
    if broker_available():
        try:
            task = celery_task.delay(*celery_args)
            return {"transport": "celery", "task_id": task.id}
        except Exception as exc:
            # A broker that answered the probe but rejected the publish: fall through
            # rather than lose the run.
            log.warning("dispatch.publish_failed", job=name, error=str(exc)[:200])

    run_in_thread(
        fallback,
        tenant_id=tenant_id,
        # No tenant means platform-level work - a run started by platform staff, whose
        # rows are shared master data. Binding it as an ordinary session left row level
        # security hiding the job from its own worker: `db.get(ImportBatch, ...)` came
        # back None, the runner returned "missing", and the run sat at `queued` forever
        # while the screen showed a spinner. Thirty minutes, no searches, no error.
        is_platform_admin=tenant_id is None,
        name=name,
        **fallback_kwargs,
    )
    return {"transport": "in_process", "task_id": None}
