"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { clientFetch } from "@/lib/api-client";
import { ApiError } from "@/lib/api-shared";
import type { DiscoveryRun } from "@/types/api";

/**
 * How long to wait *after* one poll returns before asking again, and the ceiling that
 * wait grows to on a long run.
 *
 * The gap is measured between responses, not between requests: the run detail is a
 * real query against a hosted database, and a fixed interval shorter than the response
 * time queues requests faster than they drain. That exhausted the connection pool and
 * surfaced in the browser as "failed to fetch" — the poll, not the search, was broken.
 */
const POLL_MS = 3000;
const POLL_MAX_MS = 15000;

/** After this long, a run is a background job and does not need second-by-second news. */
const POLL_BACKOFF_AFTER_MS = 2 * 60 * 1000;

/**
 * Watch a discovery run until it stops.
 *
 * Shared because there are now two screens that start a run and wait for it — the AI
 * search panel on `/pumps` and `/vendors`, and the chat, which extracts full specs from
 * the pages an answer turned up. The waiting is the part with the sharp edges (backoff,
 * one request in flight, a session that expires mid-run), so it lives in one place
 * rather than being reimplemented per screen and drifting.
 */
export function useRunWatcher(path: string) {
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Held in a ref so the poll effect does not restart on every tick.
  const runIdRef = useRef<string | null>(null);

  const poll = useCallback(
    async (runId: string) => {
      try {
        const next = await clientFetch<DiscoveryRun>(`${path}/${runId}`);
        setRun(next);
        setError(null);
        return next.is_running;
      } catch (caught) {
        // A sweep outlives an access token, and once the session is gone every further
        // poll returns the same 401. Stop and say so: retrying cannot fix it, and the
        // run itself is unaffected — it keeps going server-side.
        if (caught instanceof ApiError && caught.isAuthError) {
          setError(
            "Your session expired while the search was running. The search itself is still going — sign in again and reopen this panel to see the results.",
          );
          return false;
        }
        setError(
          caught instanceof Error ? caught.message : "Lost track of the run",
        );
        // A single failed poll is not a dead run: the network hiccups, and the request
        // is slow enough to time out under load. Keep watching.
        return true;
      }
    },
    [path],
  );

  /** Start watching a run that was just created (or re-fetched). */
  const watch = useCallback((next: DiscoveryRun) => {
    runIdRef.current = next.id;
    setRun(next);
  }, []);

  /** Forget the run, so the screen can offer to start another one. */
  const reset = useCallback(() => {
    runIdRef.current = null;
    setRun(null);
    setError(null);
  }, []);

  // Both providers are slow — a Parallel search is a few seconds, a reading model on a
  // full page can be over a minute — so the run is watched rather than awaited.
  //
  // Each poll schedules the next one only once it has returned, so however slow the
  // response is there is never more than one in flight. A long run also backs off:
  // after a couple of minutes nobody is reading the page second by second, and a
  // 23-segment sweep runs for over an hour.
  useEffect(() => {
    if (!run?.is_running) return;
    runIdRef.current = run.id;

    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();

    const tick = async () => {
      const id = runIdRef.current;
      if (stopped || !id) return;
      const stillRunning = await poll(id);
      if (stopped || !stillRunning) return;
      const elapsed = Date.now() - startedAt;
      timer = setTimeout(
        tick,
        elapsed > POLL_BACKOFF_AFTER_MS ? POLL_MAX_MS : POLL_MS,
      );
    };

    timer = setTimeout(tick, POLL_MS);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [run?.is_running, run?.id, poll]);

  return { run, watch, reset, poll, error, setError };
}
