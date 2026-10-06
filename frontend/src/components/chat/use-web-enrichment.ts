"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { discoveryKind } from "@/components/discovery/kinds";
import { useRunWatcher } from "@/components/discovery/use-run-watcher";
import { clientFetch } from "@/lib/api-client";
import type {
  ChatCaptureResult,
  DiscoveryCandidate,
  DiscoveryRun,
  DiscoverySelectResponse,
  StoredRecord,
} from "@/types/api";

/**
 * Read the pages an answer cited, so a web result can show a specification.
 *
 * A search provider hands back a title and a link — often nothing else; the one
 * in use here returns no page text at all. So a cited page can say "Flowserve
 * ECPJ" and nothing about its duty point, which makes it useless next to a held
 * record that shows flow, head, materials and design pressure.
 *
 * Getting those fields means fetching the page and reading it, and that is the
 * ordinary discovery pipeline — the same one `/pumps` and `/vendors` use. This
 * hook runs it in the background and hands each cited URL whatever candidate the
 * run produced for it, so the card fills in where the page supported it.
 *
 * **It reads; it never writes.** Every field arrives with the sentence that
 * supports it, and nothing reaches the record until `store` is called for that
 * candidate — which is a button on the card, not something that happens because
 * a question was asked.
 */

const KIND = discoveryKind("pump");

/** Trim a URL to what identifies the page, so a tracking parameter cannot stop a
 *  candidate matching the card it belongs to. The provider appends
 *  `?utm_source=openai`; the pipeline stores the URL it actually fetched. */
function urlKey(url: string | null | undefined): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    return `${parsed.hostname.replace(/^www\./, "")}${parsed.pathname}`.replace(
      /\/$/,
      "",
    );
  } catch {
    return url.trim();
  }
}

export interface WebEnrichment {
  /** Extracted candidate for a cited URL, once its page has been read. */
  candidateFor: (url: string) => DiscoveryCandidate | null;
  /** True while the pages are being fetched and read. */
  reading: boolean;
  /** The run finished and this URL produced no candidate. */
  ruledOut: (url: string) => boolean;
  /** Records written from this answer, by candidate id. */
  storedFor: (candidateId: string) => StoredRecord | null;
  storing: string | null;
  error: string | null;
  store: (candidate: DiscoveryCandidate) => Promise<void>;
}

export function useWebEnrichment(
  question: string,
  urls: string[],
  enabled: boolean,
): WebEnrichment {
  const { run, watch, poll, error, setError } = useRunWatcher(KIND.path);
  const [storing, setStoring] = useState<string | null>(null);
  const [stored, setStored] = useState<Record<string, StoredRecord>>({});
  const started = useRef(false);

  // The page list is rebuilt on every render by `.map`, so depend on its content
  // rather than its identity or the run restarts forever.
  const urlsKey = urls.join("|");

  useEffect(() => {
    if (!enabled || started.current || !urls.length) return;
    started.current = true;

    void (async () => {
      try {
        const capture = await clientFetch<ChatCaptureResult>("/chat/capture", {
          method: "POST",
          body: {
            // The question labels the run, so it is recognisable in Imports
            // rather than being an opaque id.
            question: question.slice(0, 160),
            kind: KIND.slug,
            max_results: urls.length,
            urls,
          },
        });
        watch(await clientFetch<DiscoveryRun>(`${KIND.path}/${capture.run_id}`));
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : "Could not read those pages",
        );
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, urlsKey]);

  const byUrl = useMemo(() => {
    const map = new Map<string, DiscoveryCandidate>();
    for (const candidate of run?.candidates ?? []) {
      const key = urlKey(candidate.source_url);
      if (key && !map.has(key)) map.set(key, candidate);
    }
    return map;
  }, [run]);

  const candidateFor = useCallback(
    (url: string) => byUrl.get(urlKey(url)) ?? null,
    [byUrl],
  );

  const reading = Boolean(enabled && urls.length && (!run || run.is_running));

  const ruledOut = useCallback(
    (url: string) => !reading && Boolean(run) && !byUrl.has(urlKey(url)),
    [byUrl, reading, run],
  );

  const storedFor = useCallback(
    (candidateId: string) => stored[candidateId] ?? null,
    [stored],
  );

  const store = useCallback(
    async (candidate: DiscoveryCandidate) => {
      if (!run) return;
      setStoring(candidate.id);
      setError(null);
      try {
        const response = await clientFetch<DiscoverySelectResponse>(
          `${KIND.path}/${run.id}/select`,
          { method: "POST", body: { store: [{ candidate_id: candidate.id }] } },
        );
        const written = response.stored[0];
        if (written) {
          setStored((current) => ({ ...current, [candidate.id]: written }));
        } else {
          const why = Object.values(response.failed)[0];
          setError(why ?? "That candidate could not be stored.");
        }
        // Refresh the run so the candidate's own decision is up to date.
        await poll(run.id);
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : "Could not store that record",
        );
      } finally {
        setStoring(null);
      }
    },
    [poll, run, setError],
  );

  return {
    candidateFor,
    reading,
    ruledOut,
    storedFor,
    storing,
    error,
    store,
  };
}
