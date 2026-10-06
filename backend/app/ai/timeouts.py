"""One timeout shape for every provider call.

``httpx.Client(timeout=120)`` looks like a two-minute ceiling and is not one. It sets
each *phase* to 120 seconds - connect, read, write, pool - and the read clock restarts on
every byte received. A provider that trickles output, or holds a connection open while it
runs a server-side tool, can therefore keep a request alive far longer than the number
suggests. A vendor sweep sat on a single unfinished search call for 63 minutes with a
"120 second" timeout configured.

`bounded` keeps the per-phase values honest and short where they should be short: a
connection that has not been established in ten seconds is not going to be, and waiting
for a connection from the pool is a local queue, not a remote one. The read budget stays
as configured, because a reading model genuinely takes a minute on a long page.

This does not bound total wall clock - only the caller can, by not retrying forever - so
the number of retries is the other half of the ceiling and is deliberately small.
"""

from __future__ import annotations

import httpx

#: A TCP connection either happens quickly or is not going to.
CONNECT_SECONDS = 10.0

#: Waiting for a free connection from the local pool. Long waits here mean the pool is
#: too small, which is a configuration problem rather than something to sit through.
POOL_SECONDS = 10.0


def bounded(read_seconds: float | int) -> httpx.Timeout:
    """The timeout to give an `httpx.Client` for a provider call."""
    read = float(read_seconds)
    return httpx.Timeout(
        connect=CONNECT_SECONDS,
        read=read,
        # Writing a request body is local work; it should never need the read budget.
        write=min(read, 30.0),
        pool=POOL_SECONDS,
    )
