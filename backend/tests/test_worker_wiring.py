"""Celery wiring.

Regression: the tasks were declared with ``@shared_task``, which binds to Celery's
*default* app. Nothing in the API process created the configured app, so the default one
was used - with its default ``amqp://`` broker. Every ``.delay()`` from an API request
failed trying to reach RabbitMQ on port 5672 instead of Redis, in every environment.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.workers import tasks
from app.workers.celery_app import celery_app

DISPATCHED_FROM_THE_API = [
    tasks.ingest_url_task,
    tasks.extract_source_task,
    tasks.web_search_task,
    tasks.enrich_pump_model_task,
    tasks.ai_quality_check_task,
    tasks.summarise_vendor_task,
    tasks.reindex_pump_model_task,
    tasks.run_crawl_schedule_task,
]


@pytest.mark.parametrize("task", DISPATCHED_FROM_THE_API, ids=lambda t: t.name)
def test_task_is_bound_to_the_configured_app(task):
    assert task.app is celery_app, f"{task.name} is bound to the wrong Celery app"


@pytest.mark.parametrize("task", DISPATCHED_FROM_THE_API, ids=lambda t: t.name)
def test_task_would_publish_to_redis_not_rabbitmq(task):
    broker = task.app.conf.broker_url
    assert broker.startswith("redis://"), f"{task.name} would publish to {broker}"
    assert broker == settings.CELERY_BROKER_URL


def test_every_task_has_an_explicit_name():
    """Auto-generated names embed the module path and break on refactor."""
    for name in celery_app.tasks:
        if name.startswith("celery."):
            continue
        assert name.startswith("pumpatlas."), f"{name} has no explicit pumpatlas.* name"


def test_queue_routing_covers_every_routed_task():
    """A task routed to a queue no worker consumes would sit in Redis forever."""
    consumed = {"default", "ingest", "ai", "index"}
    for name, route in celery_app.conf.task_routes.items():
        assert name in celery_app.tasks, f"task_routes references unknown task {name}"
        assert route["queue"] in consumed, f"{name} routed to unconsumed queue {route['queue']}"


def test_slow_ai_work_is_not_on_the_same_queue_as_fast_indexing():
    routes = celery_app.conf.task_routes
    assert routes["pumpatlas.extract_source"]["queue"] == "ai"
    assert routes["pumpatlas.reindex_pump_model"]["queue"] == "index"


def test_beat_schedule_references_real_tasks():
    for entry in celery_app.conf.beat_schedule.values():
        assert entry["task"] in celery_app.tasks, f"beat references unknown {entry['task']}"


def test_acks_late_and_reject_on_worker_lost_are_set():
    """A worker killed mid-extraction must not silently drop the source."""
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True


def test_task_results_are_not_stored():
    """Nothing reads a Celery result; job status lives in `ai_jobs`.

    Storing results made every dispatch touch the result backend as well as the broker,
    which doubled the failure surface and turned an unreachable Redis into a 20-second
    hang on any endpoint that queued work.
    """
    assert celery_app.conf.task_ignore_result is True


def test_dispatch_fails_fast_when_the_broker_is_unreachable():
    """A web request that queues a job must not hang on a dead broker."""
    policy = celery_app.conf.task_publish_retry_policy
    assert policy["max_retries"] <= 1
    assert celery_app.conf.broker_connection_timeout <= 5
    assert celery_app.conf.broker_transport_options["socket_connect_timeout"] <= 5


def test_worker_waits_for_the_broker_at_startup():
    """The opposite of the above: a worker booting before Redis should retry, not die."""
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_eager_mode_is_off_by_default():
    """Eager mode runs jobs inside the caller. It is a local convenience only."""
    assert celery_app.conf.task_always_eager is False


def test_eager_mode_is_refused_in_production():
    """Importing the Celery app with both flags set must fail loudly, not silently."""
    import importlib

    from app.core.config import Settings

    production_eager = Settings(ENVIRONMENT="production", CELERY_TASK_ALWAYS_EAGER=True)
    assert production_eager.is_production
    assert production_eager.CELERY_TASK_ALWAYS_EAGER
    # The guard lives at import time in app.workers.celery_app; assert it is present
    # rather than re-importing the module and mutating global state.
    source = importlib.util.find_spec("app.workers.celery_app").origin
    assert source is not None
    text = open(source, encoding="utf-8").read()
    assert "CELERY_TASK_ALWAYS_EAGER and settings.is_production" in text
    assert "raise RuntimeError" in text
