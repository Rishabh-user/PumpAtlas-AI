"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, RotateCcw, Undo2 } from "lucide-react";

import { clientFetch } from "@/lib/api-client";
import { dateOnly, editableValue, fieldValue } from "@/lib/format";
import { fieldLabel, humanise } from "@/lib/labels";
import { ConfidenceChip } from "@/components/data/confidence";
import { EmptyState, ErrorState, SuccessNote } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { Page, ReviewQueueItem } from "@/types/api";

type Decision = "accepted" | "accepted_with_edits" | "rejected" | "escalated";

/** Every action a card can start. "reset" returns a decided candidate to the queue. */
type Action = Decision | "reset";

/**
 * Decisions that wrote a record. These candidates are finished: the API refuses both a
 * second decision ("Already promoted to pump_model ...") and a reset ("Promoted
 * candidates cannot be reset; correct the record"), so the card must not offer either.
 */
const PROMOTING_DECISIONS = new Set(["accepted", "accepted_with_edits"]);

/** How a finished candidate's decision reads on the card. */
const DECISION_LABEL: Record<string, string> = {
  accepted: "Accepted",
  accepted_with_edits: "Accepted with corrections",
  rejected: "Rejected",
  escalated: "Escalated",
};

/**
 * Where a promoted candidate's record lives, or null when it cannot be linked.
 *
 * `target_type` is the spec table when promotion wrote a spec version, and `target_id`
 * is then that version's row id — not a pump model id — so linking it would 404. Only
 * the two record types are followed.
 */
function targetHref(item: ReviewQueueItem): string | null {
  if (!item.target_id) return null;
  if (item.target_type === "vendors") return `/vendors/${item.target_id}`;
  if (item.target_type === "pump_model") return `/pumps/${item.target_id}`;
  return null;
}

/**
 * What is in flight, so the spinner appears on the button that was actually pressed.
 *
 * A single "busy" flag only dimmed every button on the page, which is the one thing a
 * person cannot read: accepting writes a vendor, a pump, a model, a spec version and a
 * provenance row per field against a hosted database, so the click takes seconds and
 * looked like nothing had happened.
 */
type Pending = { id: string; decision: Action };

/** Stands in for a card id when the action covers the whole selection. */
const BULK = "__bulk__";

/** Present tense, because the label is read while the work is happening. */
const PENDING_LABEL: Record<Action, string> = {
  accepted: "Promoting…",
  accepted_with_edits: "Promoting…",
  rejected: "Rejecting…",
  escalated: "Escalating…",
  reset: "Returning…",
};

export function ReviewQueue({
  initial,
  filtered = false,
}: {
  initial: Page<ReviewQueueItem> | null;
  /** Whether a filter is narrowing the queue, which changes what "empty" means. */
  filtered?: boolean;
}) {
  const router = useRouter();
  const [items, setItems] = useState(initial?.items ?? []);
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The decision returns before the page data does: `router.refresh()` re-runs the
  // server component, which re-reads the queue and the pending-count badge. Holding a
  // transition over it keeps a loader on screen until the numbers actually agree.
  const [refreshing, startRefresh] = useTransition();

  const busy = pending !== null || refreshing;
  const bulkPending = pending?.id === BULK ? pending.decision : null;

  function remove(id: string) {
    setItems((current) => current.filter((item) => item.id !== id));
    setSelected((current) => current.filter((value) => value !== id));
  }

  async function decide(
    item: ReviewQueueItem,
    decision: Decision,
    edits: Record<string, unknown> = {},
  ) {
    setPending({ id: item.id, decision });
    setError(null);
    setMessage(null);
    try {
      const response = await clientFetch<{
        status: string;
        pump_model_id?: string;
      }>(`/ai/review-queue/${item.id}/decide`, {
        method: "POST",
        body: { decision, edits, notes: null },
      });
      remove(item.id);
      setMessage(
        response.pump_model_id
          ? `Promoted into pump model ${response.pump_model_id.slice(0, 8)}.`
          : `Candidate ${decision.replace("_", " ")}.`,
      );
      startRefresh(() => router.refresh());
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not record the decision",
      );
    } finally {
      setPending(null);
    }
  }

  /**
   * Put a decided candidate back in the queue.
   *
   * Offered only for rejected and escalated ones: a promoted candidate already wrote a
   * record, and the API refuses to reset it because undoing that is a correction to the
   * record, not to the queue.
   */
  async function returnToQueue(item: ReviewQueueItem) {
    setPending({ id: item.id, decision: "reset" });
    setError(null);
    setMessage(null);
    try {
      await clientFetch(`/ai/review-queue/${item.id}/reset`, {
        method: "POST",
      });
      remove(item.id);
      setMessage("Candidate returned to the review queue.");
      startRefresh(() => router.refresh());
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not return the candidate to the queue",
      );
    } finally {
      setPending(null);
    }
  }

  async function bulk(decision: "accepted" | "rejected") {
    if (!selected.length) return;
    // Keyed to the sentinel rather than a card: a bulk call covers many of them.
    setPending({ id: BULK, decision });
    setError(null);
    setMessage(null);
    try {
      const response = await clientFetch<{
        processed: string[];
        skipped: string[];
        errors: Record<string, string>;
      }>("/ai/review-queue/bulk", {
        method: "POST",
        body: { entity_ids: selected, decision },
      });
      for (const id of response.processed) remove(id);
      const failures = Object.keys(response.errors).length;
      setMessage(
        `${response.processed.length} ${decision}, ${response.skipped.length} skipped` +
          (failures ? `, ${failures} could not be promoted` : ""),
      );
      startRefresh(() => router.refresh());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Bulk action failed");
    } finally {
      setPending(null);
    }
  }

  // Rendered here rather than by the page, so deciding the *last* candidate does not
  // unmount this component and take its confirmation with it — "Promoted into pump
  // model 73b07b45" is the only place the new record's id is shown.
  const empty = !items.length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">
          {/* Not "pending": the queue can be filtered by decision now, so this
              list is whatever the filter selected. */}
          {items.length} shown {initial ? `of ${initial.total}` : ""}
        </span>
        {selected.length ? (
          <>
            <span className="text-sm text-primary">
              {selected.length} selected
            </span>
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void bulk("accepted")}
            >
              {bulkPending === "accepted" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {bulkPending === "accepted"
                ? `Promoting ${selected.length}…`
                : "Accept selected"}
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={() => void bulk("rejected")}
            >
              {bulkPending === "rejected" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {bulkPending === "rejected"
                ? `Rejecting ${selected.length}…`
                : "Reject selected"}
            </Button>
          </>
        ) : null}
        {/* The decision has landed but the queue total has not caught up yet. */}
        {refreshing && !pending ? (
          <span className="flex items-center gap-1.5 text-2xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin text-primary" />
            Updating the queue…
          </span>
        ) : null}
        {message ? <SuccessNote>{message}</SuccessNote> : null}
        {error ? (
          <span className="text-xs text-destructive">{error}</span>
        ) : null}
      </div>

      {empty ? (
        <Card className="overflow-hidden">
          <EmptyState
            title={
              filtered
                ? "No candidates match these filters"
                : "Nothing awaiting review"
            }
            hint={
              filtered
                ? "Widen the filters to see the rest of the queue."
                : "Extractions appear here as sources are ingested."
            }
            action={
              filtered ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href="/review">Clear filters</Link>
                </Button>
              ) : null
            }
          />
        </Card>
      ) : null}

      <div className="space-y-4">
        {items.map((item) => (
          <CandidateCard
            key={item.id}
            item={item}
            busy={busy}
            pendingDecision={pending?.id === item.id ? pending.decision : null}
            // A bulk call names no single card, so the busy treatment follows the
            // selection instead — otherwise two candidates are being written with
            // nothing on either of them to say so.
            inBulk={bulkPending !== null && selected.includes(item.id)}
            onReturnToQueue={returnToQueue}
            selected={selected.includes(item.id)}
            onSelect={() =>
              setSelected((current) =>
                current.includes(item.id)
                  ? current.filter((value) => value !== item.id)
                  : [...current, item.id],
              )
            }
            onDecide={decide}
          />
        ))}
      </div>
    </div>
  );
}

function CandidateCard({
  item,
  busy,
  pendingDecision,
  inBulk,
  selected,
  onSelect,
  onDecide,
  onReturnToQueue,
}: {
  item: ReviewQueueItem;
  busy: boolean;
  /** The action in flight for *this* candidate, or null. */
  pendingDecision: Action | null;
  /** This candidate is part of a bulk action that is in flight. */
  inBulk: boolean;
  selected: boolean;
  onSelect: () => void;
  onDecide: (
    item: ReviewQueueItem,
    decision: Decision,
    edits?: Record<string, unknown>,
  ) => Promise<void>;
  onReturnToQueue: (item: ReviewQueueItem) => Promise<void>;
}) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const fields = Object.entries(item.payload.fields ?? {});
  const confidence = item.overall_confidence;

  /**
   * Record a correction only when it differs from what Gemma extracted.
   *
   * The boxes are pre-filled so a reviewer can adjust a value instead of retyping it,
   * which means most of them hold an unchanged extracted value. Those must not be sent:
   * the API treats every field in `edits` as human-entered — it replaces the verbatim
   * source quote with "Value entered by reviewer during AI review" and flips the whole
   * record's origin from AI extraction to manual. Submitting the pre-filled values would
   * quietly erase the evidence trail on every accept.
   */
  function setEdit(field: string, value: string, original: string) {
    setEdits((current) => {
      const next = { ...current };
      if (value === original) delete next[field];
      else next[field] = value;
      return next;
    });
  }

  const hasEdits = Object.keys(edits).length > 0;
  const promoting =
    pendingDecision === "accepted" || pendingDecision === "accepted_with_edits";

  const acting = pendingDecision !== null || inBulk;
  // A candidate that has already been judged. The queue can now be filtered by
  // decision, so these appear on screen where previously only pending ones did.
  const decided = item.review_decision !== "pending";
  const promoted = PROMOTING_DECISIONS.has(item.review_decision);
  const href = targetHref(item);
  const corrections = Object.keys(item.reviewer_edits ?? {});

  return (
    <Card
      // The card being decided is outlined and faded while the write is in flight, so
      // it is obvious which candidate the spinner belongs to when several are listed.
      aria-busy={acting}
      className={cn(
        "overflow-hidden transition-opacity",
        acting && "border-primary/40 opacity-70",
      )}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {humanise(item.entity_type)} · {item.field_count} fields
          {acting ? (
            <Loader2 className="size-3.5 animate-spin text-primary" />
          ) : null}
        </CardTitle>
        <div className="flex items-center gap-2.5">
          <ConfidenceChip level={item.confidence_level} />
          {confidence !== null ? (
            <span
              className={`figure ${
                confidence >= 0.85
                  ? "text-conf-verified"
                  : confidence >= 0.6
                    ? "text-primary"
                    : "text-destructive"
              }`}
            >
              {(confidence * 100).toFixed(0)}%
            </span>
          ) : null}
          {decided ? (
            <Badge variant={promoted ? "success" : "outline"}>
              {DECISION_LABEL[item.review_decision] ??
                humanise(item.review_decision)}
            </Badge>
          ) : (
            <label className="flex cursor-pointer items-center gap-1.5 text-2xs text-muted-foreground">
              <Checkbox checked={selected} onCheckedChange={onSelect} />
              Select
            </label>
          )}
        </div>
      </CardHeader>
      <div className="grid gap-4 border-b border-border px-4 py-3 sm:grid-cols-3">
        <div>
          <span className="label-xs">Subject</span>
          <p className="mt-0.5 text-sm text-foreground">
            {item.suggested_vendor ?? "Vendor not identified"}
          </p>
          <p className="text-xs text-muted-foreground/70">
            {item.suggested_model_code ?? "Model not identified"}
          </p>
          {/* Read from the API's own verdict rather than re-derived here, so a card
              can never carry a badge that contradicts the filter that selected it. */}
          {item.vendor_match === "matched" ? (
            <Badge variant="success">Matches an existing vendor</Badge>
          ) : item.vendor_match === "new" ? (
            <Badge variant="warning">Will create a new vendor</Badge>
          ) : (
            <Badge variant="destructive">
              Needs a vendor before it can be promoted
            </Badge>
          )}
        </div>
        <div className="sm:col-span-2">
          <span className="label-xs">Source</span>
          <p className="mt-0.5 truncate text-sm text-foreground">
            {item.source_title ?? item.source_url ?? "Unknown source"}
          </p>
          <p className="text-xs text-muted-foreground/70">
            {humanise(item.source_type)} &middot; captured{" "}
            {dateOnly(item.source_captured_at)}
          </p>
          {item.source_url ? (
            <a
              href={item.source_url}
              target="_blank"
              rel="noreferrer noopener"
              className="truncate text-xs text-primary hover:underline"
            >
              {item.source_url}
            </a>
          ) : null}
        </div>
      </div>

      <div className="max-h-96 overflow-y-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Field</TableHead>
              <TableHead>Extracted value</TableHead>
              <TableHead className="w-20 text-right">Confidence</TableHead>
              <TableHead>Evidence from the source</TableHead>
              <TableHead className="w-56">
                {decided ? "Reviewer's correction" : "Correct it"}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fields.map(([field, value]) => {
              const fieldConfidence = item.field_confidences[field];
              const evidence = item.evidence_spans[field]?.quote;
              const original = editableValue(value);
              const current = edits[field] ?? original;
              const changed = field in edits;
              return (
                <TableRow key={field}>
                  <TableCell className="text-xs text-muted-foreground">
                    {fieldLabel(field)}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums text-foreground">
                    {fieldValue(field, value)}
                  </TableCell>
                  <TableCell
                    className={`text-right text-xs tabular-nums ${
                      fieldConfidence === undefined
                        ? "text-muted-foreground/70"
                        : fieldConfidence >= 0.85
                          ? "text-conf-verified"
                          : fieldConfidence >= 0.6
                            ? "text-primary"
                            : "text-destructive"
                    }`}
                  >
                    {fieldConfidence === undefined
                      ? "\u2014"
                      : `${(fieldConfidence * 100).toFixed(0)}%`}
                  </TableCell>
                  <TableCell className="max-w-sm text-xs italic text-muted-foreground/70">
                    {evidence ? `"${evidence}"` : "No quote supplied"}
                  </TableCell>
                  <TableCell>
                    {decided ? (
                      // Nothing to correct any more; what a reviewer *did* change is
                      // the useful thing to show in its place.
                      <span
                        className={cn(
                          "text-xs",
                          field in (item.reviewer_edits ?? {})
                            ? "text-primary"
                            : "text-muted-foreground/50",
                        )}
                      >
                        {field in (item.reviewer_edits ?? {})
                          ? editableValue(item.reviewer_edits[field])
                          : "\u2014"}
                      </span>
                    ) : (
                      <div className="flex items-center gap-1">
                        <Input
                          value={current}
                          onChange={(event) =>
                            setEdit(field, event.target.value, original)
                          }
                          placeholder={original ? undefined : "add a value"}
                          aria-label={`Correct ${fieldLabel(field)}`}
                          className={cn(
                            "h-7 w-full min-w-24",
                            changed && "border-primary text-primary",
                          )}
                        />
                        {/* Only offered once something actually differs, and it restores
                          the extracted value rather than merely clearing the box. */}
                        {changed ? (
                          <button
                            type="button"
                            onClick={() => setEdit(field, original, original)}
                            title="Restore the extracted value"
                            aria-label={`Undo the correction to ${fieldLabel(field)}`}
                            className="text-muted-foreground transition-colors hover:text-foreground"
                          >
                            <Undo2 className="size-3.5" />
                          </button>
                        ) : null}
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
        {decided ? (
          <>
            {/* No Accept/Reject here. The API refuses a second decision — "Already
                promoted to pump_model ..." — so offering the buttons only produces an
                error the reviewer can do nothing about. */}
            {promoted ? (
              <p className="text-xs text-muted-foreground">
                Promoted to{" "}
                {href ? (
                  <Link href={href} className="text-primary hover:underline">
                    {humanise(item.target_type ?? "record")}{" "}
                    {item.target_id?.slice(0, 8)}
                  </Link>
                ) : (
                  <span className="text-foreground">
                    {humanise(item.target_type ?? "record")}{" "}
                    {item.target_id?.slice(0, 8) ?? ""}
                  </span>
                )}
                {corrections.length
                  ? ` · ${corrections.length} field${corrections.length === 1 ? "" : "s"} corrected by the reviewer`
                  : " · every value as extracted"}
              </p>
            ) : (
              <>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => void onReturnToQueue(item)}
                >
                  {pendingDecision === "reset" ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <RotateCcw />
                  )}
                  {pendingDecision === "reset"
                    ? PENDING_LABEL.reset
                    : "Return to queue"}
                </Button>
                <p className="text-xs text-muted-foreground/70">
                  Nothing was written for this candidate. Returning it makes it
                  reviewable again.
                </p>
              </>
            )}
            {item.review_notes ? (
              <p className="ml-auto text-xs italic text-muted-foreground/70">
                &ldquo;{item.review_notes}&rdquo;
              </p>
            ) : null}
          </>
        ) : (
          <>
            <Button
              disabled={busy}
              onClick={() =>
                void onDecide(
                  item,
                  hasEdits ? "accepted_with_edits" : "accepted",
                  edits,
                )
              }
            >
              {promoting ? <Loader2 className="animate-spin" /> : null}
              {promoting
                ? PENDING_LABEL.accepted
                : hasEdits
                  ? "Accept with my corrections"
                  : "Accept and promote"}
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => void onDecide(item, "rejected")}
            >
              {pendingDecision === "rejected" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {pendingDecision === "rejected"
                ? PENDING_LABEL.rejected
                : "Reject"}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => void onDecide(item, "escalated")}
            >
              {pendingDecision === "escalated" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {pendingDecision === "escalated"
                ? PENDING_LABEL.escalated
                : "Escalate"}
            </Button>
            <p className="ml-auto text-xs text-muted-foreground/70">
              {promoting
                ? "Writing the vendor, the model, its specification version and a provenance row for every field."
                : "Accepting writes provenance rows naming this source, the model and each evidence quote."}
            </p>
          </>
        )}
      </div>
    </Card>
  );
}
