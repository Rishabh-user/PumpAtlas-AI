"""Celery application: background ingestion, extraction, enrichment and indexing.

Queues are separated by cost profile so a long PDF extraction never blocks a
five-second reindex:

* ``ingest``  - fetching and parsing (IO bound, high concurrency)
* ``ai``      - OpenRouter and Parallel AI calls (slow, rate limited)
* ``index``   - search index and score maintenance (fast, cheap)
* ``default`` - everything else
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL, json_logs=settings.is_production)

if settings.CELERY_TASK_ALWAYS_EAGER and settings.is_production:
    raise RuntimeError(
        "CELERY_TASK_ALWAYS_EAGER must not be enabled in production: every background "
        "job would run inside the web request that triggered it."
    )

celery_app = Celery(
    "pumpatlas",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Eager mode executes tasks in the caller instead of publishing them, so no broker
    # is contacted at all. This is what lets the platform run without Redis locally.
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=settings.CELERY_TASK_ALWAYS_EAGER,
    # Nothing in the platform reads a Celery result: routers return the task id for
    # reference only, and job status is tracked in the `ai_jobs` table, which is the
    # durable record. Storing results made every dispatch touch the result backend as
    # well as the broker, which doubled the failure surface and the latency. A task can
    # still opt back in with @celery_app.task(ignore_result=False) when debugging.
    task_ignore_result=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    # A worker that dies mid-extraction must not silently drop the source.
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=60 * 60 * 24 * 7,
    task_soft_time_limit=60 * 25,
    task_time_limit=60 * 30,
    # Fail fast when the broker is unreachable. The defaults retry the result backend
    # 20 times at one second apiece, so a request that dispatches a job would hang for
    # 20 seconds before erroring - in production as much as in development.
    broker_connection_timeout=3,
    broker_transport_options={
        "max_retries": 1,
        "socket_connect_timeout": 2,
        "socket_timeout": 5,
    },
    # Publishing happens inside a web request, so one quick retry then give up. The
    # default policy is three attempts, which stacked with the connect timeouts into an
    # eight-second hang on an endpoint that only wanted to queue a job.
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },
    result_backend_transport_options={
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "retry_policy": {"max_retries": 2},
    },
    result_backend_max_retries=2,
    # A worker, unlike a web request, should wait for Redis to come up rather than die.
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    task_routes={
        "pumpatlas.ingest_url": {"queue": "ingest"},
        "pumpatlas.run_crawl_schedule": {"queue": "ingest"},
        "pumpatlas.web_search": {"queue": "ingest"},
        "pumpatlas.extract_source": {"queue": "ai"},
        "pumpatlas.enrich_pump_model": {"queue": "ai"},
        "pumpatlas.ai_quality_check": {"queue": "ai"},
        "pumpatlas.summarise_vendor": {"queue": "ai"},
        "pumpatlas.reindex_pump_model": {"queue": "index"},
        "pumpatlas.recompute_scores": {"queue": "index"},
    },
    beat_schedule={
        "run-due-crawl-schedules": {
            "task": "pumpatlas.dispatch_due_crawls",
            "schedule": crontab(minute="*/15"),
        },
        "nightly-reindex": {
            "task": "pumpatlas.nightly_maintenance",
            "schedule": crontab(hour=2, minute=30),
        },
    },
)
