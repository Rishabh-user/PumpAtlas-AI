"""A ceiling on the requests that cost money or guess passwords.

Nothing bounded this. Two API keys are issued to another application, and
`POST /chat/ask` with `use_web: true` runs a web search and reads pages — real provider
spend on every call. A loop at the far end, or one leaked key, was an unbounded bill with
no ceiling and no alert. `POST /vendors/{id}/enrich` is the same shape: one request starts
a run that reads a dozen pages.

Deliberately small. The limits live in memory, so they are **per process**: two instances
allow twice the stated rate, and a restart forgets everything. That is worth saying out
loud rather than implying a guarantee this cannot make. What it does reliably is stop a
runaway client — a retry loop, a misconfigured cron, a script with no sleep — which is the
failure that actually empties a provider account. A hard cross-instance guarantee needs
the Redis this deployment does not yet run; when it does, this module is where that goes.

Keyed on the caller, not the address: an API key is the thing being rate limited, and
several users behind one office address should not share a budget. Only an unauthenticated
caller is keyed by address, which is what makes the login limit work at all.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: window -> caller -> times of the calls still inside it.
_hits: dict[str, dict[str, deque[float]]] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class Limit:
    """How many calls, over how long."""

    calls: int
    seconds: int

    @property
    def human(self) -> str:
        if self.seconds % 3600 == 0:
            return f"{self.calls} per {self.seconds // 3600}h"
        if self.seconds % 60 == 0:
            return f"{self.calls} per {self.seconds // 60}m"
        return f"{self.calls} per {self.seconds}s"


#: What each guarded endpoint allows. Generous enough that a person never meets them and
#: tight enough that a runaway client does.
LIMITS: dict[str, Limit] = {
    # Every page a model reads costs. Twenty questions an hour is far beyond how fast
    # anybody reads an answer, and far below what a retry loop would spend overnight.
    "ai_ask": Limit(calls=20, seconds=3600),
    # Each run reads several pages and starts a discovery job. Ten an hour was set
    # when enrichment was a thing you did to one record you were looking at. Filling
    # the gaps across a list is the same action repeated deliberately, by a person
    # watching it happen, and ten would stop them four minutes in. A run takes about
    # ninety seconds, so a person cannot exceed forty in an hour however hard they
    # try - this still catches the failure the limit is for, which is a loop with no
    # person behind it spending the night reading pages.
    "ai_enrich": Limit(calls=120, seconds=3600),
    # The account lock already stops credential stuffing against one account. This stops
    # one caller working through many accounts.
    "login": Limit(calls=10, seconds=300),
}


def caller_key(request: Request) -> str:
    """Who to count this against.

    The principal where there is one - an API key is the thing being limited, and two
    users behind one office address should not share a budget. Falling back to the
    address only for an unauthenticated caller, which is the login case.
    """
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        if getattr(principal, "api_key_id", None):
            return f"key:{principal.api_key_id}"
        if getattr(principal, "user_id", None):
            return f"user:{principal.user_id}"
    # `X-Forwarded-For` is set by the platform's proxy; its first entry is the client.
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return f"ip:{forwarded or (request.client.host if request.client else 'unknown')}"


def _check(window: str, key: str, limit: Limit) -> tuple[bool, int]:
    """Record a call and say whether it was allowed, with seconds until it would be."""
    now = time.monotonic()
    with _lock:
        seen = _hits.setdefault(window, {}).setdefault(key, deque())
        cutoff = now - limit.seconds
        while seen and seen[0] < cutoff:
            seen.popleft()
        if len(seen) >= limit.calls:
            return False, max(1, int(seen[0] + limit.seconds - now))
        seen.append(now)
        return True, 0


def limiter(window: str):
    """A dependency that enforces `LIMITS[window]`."""

    def guard(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = LIMITS[window]
        allowed, retry_after = _check(window, caller_key(request), limit)
        if allowed:
            return
        log.warning(
            "rate_limit.exceeded",
            window=window,
            caller=caller_key(request),
            limit=limit.human,
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limit reached for this operation ({limit.human}). "
            f"Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    return Depends(guard)


def reset() -> None:
    """Forget every counted call. For tests."""
    with _lock:
        _hits.clear()
