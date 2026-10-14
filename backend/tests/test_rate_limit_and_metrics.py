"""Two things the Compose deployment got for free and a platform deployment does not.

`infra/nginx.conf` restricted `/metrics` to private networks and could have rate-limited
anything. There is no nginx in front of a Render service: the API is the edge. So the
metrics endpoint went to the internet answering anybody, and nothing bounded the endpoints
that spend provider money per call — with two API keys already issued to another
application.

Nothing here makes a real request against the live database. The first version of this
file did, by signing in twenty-four times to watch the limiter bite, and it took
**fourteen and a half minutes** — each attempt a round trip to a database 300ms away plus
a bcrypt verification, against the deployed system. A test that hammers production to
prove an in-memory counter works is a bad trade twice over. The counter is tested where it
lives, and the wiring is tested by asking the router what it will run.
"""

from __future__ import annotations

import inspect

import pytest

from app.core import rate_limit
from app.core.config import settings


@pytest.fixture(autouse=True)
def _clean():
    rate_limit.reset()
    before = (settings.ENVIRONMENT, settings.METRICS_TOKEN, settings.RATE_LIMIT_ENABLED)
    yield
    settings.ENVIRONMENT, settings.METRICS_TOKEN, settings.RATE_LIMIT_ENABLED = before
    rate_limit.reset()


class _Request:
    """Just the parts of a request the limiter reads."""

    def __init__(self, principal=None, forwarded: str = "", host: str = "10.0.0.1"):
        self.state = type("S", (), {"principal": principal})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = type("C", (), {"host": host})()


def _guard_for(window: str):
    """The callable the route would run."""
    return rate_limit.limiter(window).dependency


class TestTheCounterItself:
    def test_it_allows_up_to_the_limit_then_refuses(self):
        limit = rate_limit.Limit(calls=3, seconds=60)
        verdicts = [rate_limit._check("probe", "caller", limit)[0] for _ in range(5)]
        assert verdicts == [True, True, True, False, False]

    def test_each_caller_has_its_own_budget(self):
        """Several users behind one office address must not share one."""
        limit = rate_limit.Limit(calls=1, seconds=60)
        assert rate_limit._check("probe", "a", limit)[0] is True
        assert rate_limit._check("probe", "b", limit)[0] is True
        assert rate_limit._check("probe", "a", limit)[0] is False

    def test_calls_that_have_aged_out_are_forgotten(self, monkeypatch):
        limit = rate_limit.Limit(calls=2, seconds=60)
        now = [1000.0]
        monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])

        assert rate_limit._check("probe", "k", limit)[0] is True
        assert rate_limit._check("probe", "k", limit)[0] is True
        assert rate_limit._check("probe", "k", limit)[0] is False

        now[0] += 61
        assert rate_limit._check("probe", "k", limit)[0] is True

    def test_it_says_how_long_to_wait(self, monkeypatch):
        limit = rate_limit.Limit(calls=1, seconds=60)
        now = [1000.0]
        monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
        rate_limit._check("probe", "k", limit)
        now[0] += 10
        allowed, retry_after = rate_limit._check("probe", "k", limit)
        assert allowed is False
        assert retry_after == 50

    def test_the_limits_are_stated_in_words_a_message_can_use(self):
        assert rate_limit.Limit(20, 3600).human == "20 per 1h"
        assert rate_limit.Limit(10, 300).human == "10 per 5m"
        assert rate_limit.Limit(3, 45).human == "3 per 45s"


class TestWhoGetsCounted:
    def test_an_api_key_is_counted_as_itself(self):
        principal = type("P", (), {"api_key_id": "abc", "user_id": None})()
        assert rate_limit.caller_key(_Request(principal)) == "key:abc"

    def test_a_signed_in_user_is_counted_as_themselves(self):
        principal = type("P", (), {"api_key_id": None, "user_id": "u1"})()
        assert rate_limit.caller_key(_Request(principal)) == "user:u1"

    def test_an_anonymous_caller_falls_back_to_the_address(self):
        """Which is what makes the login limit work at all."""
        assert rate_limit.caller_key(_Request(None, "203.0.113.9, 10.0.0.1")) == "ip:203.0.113.9"
        assert rate_limit.caller_key(_Request(None)) == "ip:10.0.0.1"


class TestTheGuardRaises:
    def test_it_refuses_with_429_and_a_retry_header(self):
        import fastapi

        guard = _guard_for("login")
        limit = rate_limit.LIMITS["login"]
        request = _Request(None, "198.51.100.7")
        for _ in range(limit.calls):
            guard(request)

        with pytest.raises(fastapi.HTTPException) as caught:
            guard(request)
        assert caught.value.status_code == 429
        assert limit.human in caught.value.detail
        assert int(caught.value.headers["Retry-After"]) > 0

    def test_it_can_be_turned_off(self):
        settings.RATE_LIMIT_ENABLED = False
        guard = _guard_for("login")
        request = _Request(None, "198.51.100.8")
        for _ in range(rate_limit.LIMITS["login"].calls + 5):
            guard(request)  # no raise


class TestTheRoutesActuallyCarryIt:
    """Testing the counter proves nothing if no endpoint runs it."""

    def _dependency_names(self, path_fragment: str) -> set[str]:
        from fastapi.routing import APIRoute

        from app.main import app

        def walk(router, prefix=""):
            for route in router.routes:
                if isinstance(route, APIRoute):
                    yield prefix + route.path, route
                elif hasattr(route, "original_router"):
                    yield from walk(route.original_router, prefix)
                elif hasattr(route, "routes"):
                    yield from walk(route, prefix)

        included = [r for r in app.routes if hasattr(r, "original_router")]
        names: set[str] = set()
        for router in included:
            for path, route in walk(router.original_router):
                if path_fragment in path:
                    names |= {str(d.call) for d in route.dependant.dependencies}
        return names

    @pytest.mark.parametrize(
        "fragment", ["/auth/login", "/chat/ask", "/vendors/{vendor_id}/enrich"]
    )
    def test_the_endpoint_runs_a_limiter(self, fragment):
        joined = " ".join(self._dependency_names(fragment))
        assert "rate_limit" in joined or "guard" in joined, fragment

    def test_every_window_named_by_a_route_is_defined(self):
        """A typo in the window name would raise KeyError on the first request."""
        from app.api.v1 import auth, chat_routes, pumps, vendors

        used = set()
        for module in (auth, chat_routes, pumps, vendors):
            source = inspect.getsource(module)
            for window in rate_limit.LIMITS:
                if f'limiter("{window}")' in source:
                    used.add(window)
        assert used, "no route references a limiter window"
        assert used <= set(rate_limit.LIMITS)


class TestMetricsAreNotPublic:
    """`/metrics` publishes every route name, its traffic and its latencies."""

    def test_production_without_a_token_disables_the_endpoint(self):
        import fastapi

        from app.api.v1.system import metrics

        settings.ENVIRONMENT = "production"
        settings.METRICS_TOKEN = ""
        with pytest.raises(fastapi.HTTPException) as caught:
            metrics(authorization=None)
        assert caught.value.status_code == 404

    def test_a_token_is_required_once_one_is_configured(self):
        import fastapi

        from app.api.v1.system import metrics

        settings.ENVIRONMENT = "production"
        settings.METRICS_TOKEN = "scrape-me"
        for header in (None, "Bearer wrong", "scrape-m"):
            with pytest.raises(fastapi.HTTPException) as caught:
                metrics(authorization=header)
            assert caught.value.status_code == 401

    def test_the_right_token_still_scrapes(self):
        from app.api.v1.system import metrics

        settings.ENVIRONMENT = "production"
        settings.METRICS_TOKEN = "scrape-me"
        response = metrics(authorization="Bearer scrape-me")
        assert response.status_code == 200
        assert b"python_gc_objects" in response.body

    def test_development_is_left_alone(self):
        """It is on a laptop; breaking local scraping buys nothing."""
        from app.api.v1.system import metrics

        settings.ENVIRONMENT = "development"
        settings.METRICS_TOKEN = ""
        assert metrics(authorization=None).status_code == 200

    def test_the_comparison_is_constant_time(self):
        """A token compared with == leaks its prefix to anyone willing to measure."""
        from app.api.v1 import system

        assert "secrets.compare_digest" in inspect.getsource(system.metrics)
