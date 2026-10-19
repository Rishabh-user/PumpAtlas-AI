"use client";

import { useEffect, useState } from "react";
import { ArrowRight, FileText } from "lucide-react";

import { clientFetch } from "@/lib/api-client";
import { fieldLabel, humanise } from "@/lib/labels";

/**
 * What a discovery run actually wrote.
 *
 * A run would finish, report "4 pump models found, 4 stored", and leave the page
 * looking identical — because the fields it wrote were not among the fifteen each
 * panel shows, so they landed behind the "all recorded fields" disclosure. One run on
 * this record set `lubrication_type`, `driver_type`, `material_class`,
 * `radial_bearing_type` and `seal_api_682_category`, and none of them appeared.
 *
 * Every write already records what it replaced, a verbatim quote and the page the
 * quote came from. Nothing asked for it until now.
 */

interface Change {
  entity_type: string;
  field_name: string;
  previous_value: string | null;
  value: string | null;
  origin: string;
  confidence_level: string;
  evidence_quote: string | null;
  source_title: string | null;
  source_url: string | null;
  recorded_at: string | null;
}

export function RunChanges({
  pumpModelId,
  since,
}: {
  pumpModelId: string;
  /** ISO timestamp of when the run started. */
  since: string;
}) {
  const [changes, setChanges] = useState<Change[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    clientFetch<Change[]>(
      `/pump-models/${pumpModelId}/changes?since=${encodeURIComponent(since)}`,
    )
      .then((rows) => {
        if (!cancelled) setChanges(rows);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [pumpModelId, since]);

  if (failed || !changes) return null;

  if (!changes.length) {
    return (
      <p className="text-2xs leading-relaxed text-muted-foreground">
        This run wrote nothing. The pages it read either stated nothing this record does
        not already hold, or stated it in a form with no figure to quote.
      </p>
    );
  }

  const written = changes.filter((c) => !c.previous_value);
  const replaced = changes.filter((c) => c.previous_value);

  return (
    <div className="space-y-2">
      <p className="text-2xs text-foreground">
        This run wrote <span className="font-medium">{changes.length}</span> value
        {changes.length === 1 ? "" : "s"}
        {replaced.length ? (
          <>
            {" "}
            — {written.length} new, {replaced.length} replacing an earlier value
          </>
        ) : null}
        . Each is stored as a new version; the previous one is kept.
      </p>

      <ul className="divide-y divide-border/60 rounded border border-border">
        {changes.map((change, index) => (
          <li key={`${change.field_name}-${index}`} className="px-2.5 py-1.5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-2xs text-muted-foreground">
                {fieldLabel(change.field_name) || change.field_name}
              </span>
              {change.previous_value ? (
                <>
                  <span className="figure text-2xs text-muted-foreground line-through">
                    {change.previous_value}
                  </span>
                  <ArrowRight className="size-2.5 text-muted-foreground" />
                </>
              ) : null}
              <span className="figure text-2xs text-foreground [overflow-wrap:anywhere]">
                {change.value}
              </span>
              <span className="ml-auto text-[0.625rem] text-muted-foreground">
                {humanise(change.entity_type.replace(/_specs$/, ""))}
              </span>
            </div>

            {/* The quote is the whole guarantee: a value with no evidence behind it is
              * refused at write time, so if it is on this list it can be checked. */}
            {change.evidence_quote ? (
              <p className="mt-0.5 border-l-2 border-border pl-2 text-[0.625rem] leading-relaxed text-muted-foreground">
                &ldquo;{change.evidence_quote}&rdquo;
              </p>
            ) : null}

            {change.source_url ? (
              <a
                href={change.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-0.5 inline-flex items-center gap-1 text-[0.625rem] text-primary hover:underline"
              >
                <FileText className="size-2.5" />
                {change.source_title ?? change.source_url}
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
