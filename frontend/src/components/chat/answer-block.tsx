"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AnswerProse } from "@/components/chat/answer-prose";
import { RecordCard, WebCard } from "@/components/chat/record-card";
import { useWebEnrichment } from "@/components/chat/use-web-enrichment";
import { ErrorState } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import type { ChatAnswer } from "@/types/api";

/**
 * One answer: the prose, and every source behind it as a card.
 *
 * Held records and cited pages share one grid, because to the person reading,
 * both are "what the answer was built on" — splitting them into a card list and
 * a bullet list made the web half look like an afterthought, which it is not
 * when the catalogue holds nothing on the question.
 *
 * They do not share a *palette*, and the distinction is load-bearing. A record's
 * marker is primary and it carries its recorded-field count; a page's marker is
 * neutral, it carries a "web page" badge, and its figures are a *proposal* with a
 * Store button rather than something already on file. A page that reads like a
 * held record is the one mistake this product cannot afford — so no figure ever
 * appears on a web card unless the reading model could support it with a
 * verbatim quote, which the field's tooltip shows.
 *
 * The cited pages are read in the background, so a web card can show a
 * specification instead of a link. That is the discovery pipeline — fetch,
 * extract each field with the sentence that supports it — running without its
 * progress panel, because a progress bar and a page of diagnostics between the
 * question and the next question is not what anyone came here for. What it
 * produces is a proposal on the card, with a Store button; nothing reaches the
 * record until that is pressed.
 *
 * Clicking a `[R1]` or `[W1]` in the prose scrolls to its card, which is the
 * whole reason the markers are buttons.
 */
export function AnswerBlock({
  answer,
  question,
  enrich = false,
}: {
  answer: ChatAnswer;
  question: string;
  /** Read the cited pages for their specifications. Set on the newest answer
   *  only: re-reading pages an earlier turn already read costs a fetch and a
   *  model call per page and tells nobody anything new. */
  enrich?: boolean;
}) {
  const [openMarker, setOpenMarker] = useState<string | null>(null);
  const markerRefs = useRef<Record<string, HTMLElement | null>>({});

  const webUrls = useMemo(
    () => answer.web.map((source) => source.url),
    [answer.web],
  );
  const enrichment = useWebEnrichment(question, webUrls, enrich && !answer.error);

  useEffect(() => {
    if (!openMarker) return;
    const timer = window.setTimeout(() => {
      markerRefs.current[openMarker]?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }, 60);
    return () => window.clearTimeout(timer);
  }, [openMarker]);

  if (answer.error) return <ErrorState message={answer.error} />;

  const hasSources = answer.records.length > 0 || answer.web.length > 0;

  return (
    <div className="min-w-0 space-y-2">
      <AnswerProse text={answer.answer ?? ""} onMarker={setOpenMarker} />

      {/*
        Nothing retrieved, nothing to say about retrieval. A greeting is written
        rather than searched, and the strip used to answer it with "0 of 0 held
        records" and no model beside it - a tally of a search that never ran,
        which reads like a failure rather than a hello.
      */}
      {hasSources || answer.model ? (
        <div className="flex flex-wrap items-center gap-2 text-2xs text-muted-foreground">
          {answer.model ? (
            <Badge variant="outline" className="text-2xs">
              {answer.model}
            </Badge>
          ) : null}
          {/* Kept even at zero: "0 of 15 held records" is the useful half of a
              search that ran and matched nothing. */}
          <span>
            <span className="figure text-foreground">{answer.records.length}</span> of{" "}
            {answer.record_total} held records
          </span>
          {answer.web.length ? (
            <span>
              <span className="figure text-foreground">{answer.web.length}</span> web
              page{answer.web.length === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>
      ) : null}

      {hasSources ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {answer.records.map((record) => (
            <div
              key={record.pump_model_id}
              ref={(node) => {
                markerRefs.current[record.marker] = node;
              }}
            >
              <RecordCard record={record} highlighted={openMarker === record.marker} />
            </div>
          ))}
          {answer.web.map((source) => (
            <div
              key={source.url}
              ref={(node) => {
                markerRefs.current[source.marker] = node;
              }}
              className={
                openMarker === source.marker
                  ? "rounded-lg ring-2 ring-primary/30"
                  : undefined
              }
            >
              <WebCard
                source={source}
                candidate={enrichment.candidateFor(source.url)}
                reading={enrichment.reading}
                ruledOut={enrichment.ruledOut(source.url)}
                stored={
                  enrichment.candidateFor(source.url)
                    ? enrichment.storedFor(
                        enrichment.candidateFor(source.url)!.id,
                      )
                    : null
                }
                storing={
                  enrichment.storing ===
                  enrichment.candidateFor(source.url)?.id
                }
                onStore={enrichment.store}
              />
            </div>
          ))}
        </div>
      ) : null}

      {answer.web_error ? (
        <p className="text-2xs text-destructive">{answer.web_error}</p>
      ) : null}
      {enrichment.error ? (
        <p className="text-2xs text-destructive">{enrichment.error}</p>
      ) : null}
    </div>
  );
}
