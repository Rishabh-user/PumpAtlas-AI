"""A run that has stopped working must stop claiming it is working.

A 60-country sweep sat at "0/60 searches, 0% , 1h 2m elapsed" with one provider call
unfinished. Nothing about the screen distinguished that from a slow first search, and
nothing would have until the next API restart, because the only reaper ran at startup.

Two causes, both pinned here: a timeout that was not the ceiling it looked like, and a
row that only ever got corrected by a restart.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from app.ai import timeouts
from app.api.v1 import discovery_routes
from app.services import discovery


class TestATimeoutIsActuallyABound:
    """`httpx.Client(timeout=120)` is four separate 120s clocks, and read restarts.

    A provider that trickles bytes, or holds the connection while it runs a server-side
    web search, keeps the request alive far past the number configured.
    """

    def test_connecting_is_given_seconds_not_minutes(self):
        assert timeouts.bounded(120).connect == timeouts.CONNECT_SECONDS
        assert timeouts.CONNECT_SECONDS <= 15

    def test_the_read_budget_is_what_was_configured(self):
        """A reading model genuinely takes a minute on a long page."""
        assert timeouts.bounded(120).read == 120.0

    def test_writing_never_gets_the_read_budget(self):
        """Sending a request body is local work."""
        assert timeouts.bounded(600).write <= 30.0

    def test_waiting_for_the_local_pool_is_bounded_too(self):
        """A long wait here means the pool is too small - a config problem, not a delay."""
        assert timeouts.bounded(120).pool == timeouts.POOL_SECONDS

    def test_a_short_configured_timeout_is_not_inflated(self):
        assert timeouts.bounded(5).write == 5.0

    def test_it_returns_the_shape_httpx_wants(self):
        assert isinstance(timeouts.bounded(30), httpx.Timeout)

    @pytest.mark.parametrize(
        "module",
        ["anthropic_client", "openai_search", "openrouter", "parallel_search"],
    )
    def test_every_provider_client_uses_it(self, module):
        """One of them left un-bounded is the one that hangs."""
        source = (
            __import__(f"app.ai.{module}", fromlist=["x"]).__loader__.get_source(f"app.ai.{module}")
            or ""
        )
        assert "timeouts.bounded(self.timeout)" in source
        assert "httpx.Client(timeout=self.timeout)" not in source


class TestAStalledRunIsDeclaredDead:
    def test_the_ceiling_is_far_above_anything_legitimate(self):
        """The slowest page read observed was 94 seconds."""
        assert discovery.STALLED_JOB_SECONDS >= 10 * 60

    def test_the_poll_checks_for_stalls(self):
        """Which is when somebody is actually waiting for the answer."""
        source = inspect.getsource(discovery_routes)
        assert "discovery.reap_stalled_runs(db)" in source

    def test_a_celery_run_is_left_alone(self):
        """A worker outlives the API, so a job running there is telling the truth."""
        source = inspect.getsource(discovery.reap_stalled_runs)
        assert 'config.get("transport") not in (None, "in_process")' in source

    def test_a_run_between_calls_is_not_reaped(self):
        """Finished last call, next one not started yet - that is a working run."""
        source = inspect.getsource(discovery.reap_stalled_runs)
        assert "latest.finished_at is not None" in source

    def test_a_run_with_no_job_yet_is_judged_by_its_own_start(self):
        """Otherwise a run that stalls before its first call can never be reaped."""
        source = inspect.getsource(discovery.reap_stalled_runs)
        assert "else batch.started_at" in source

    def test_the_stalled_job_is_closed_too(self):
        """A job left "running" shows a provider call that will never finish."""
        source = inspect.getsource(discovery.reap_stalled_runs)
        assert "AiJobStatus.FAILED" in source

    def test_the_restart_reaper_closes_its_job_as_well(self):
        """It marked the batch failed and left the call it died inside running."""
        source = inspect.getsource(discovery.reap_interrupted_runs)
        assert "AiJobStatus.RUNNING" in source
        assert "Interrupted by an API restart" in source

    def test_the_summary_says_what_to_do_about_it(self):
        source = inspect.getsource(discovery.reap_stalled_runs)
        assert "Celery worker" in source
        assert "still listed" in source
