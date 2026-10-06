"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  Ban,
  Check,
  Database,
  ExternalLink,
  Loader2,
  Quote,
  X,
} from "lucide-react";

import { ConfidenceChip } from "@/components/data/confidence";
import type { DiscoveryKindConfig } from "@/components/discovery/kinds";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fieldLabel, humanise, labelFor } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { CandidateField, DiscoveryCandidate } from "@/types/api";

const EM_DASH = "—";

function renderValue(field: CandidateField): string {
  const { value } = field;
  if (value === null || value === undefined || value === "") return EM_DASH;
  if (Array.isArray(value)) return value.length ? value.join(", ") : EM_DASH;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString("en-GB");
  const text = String(value);
  return /^[a-z0-9_]+$/.test(text) ? labelFor(field.field_name, text) : text;
}

function confidenceTone(value: number | null): string {
  if (value === null) return "text-muted-foreground";
  if (value >= 0.85) return "text-conf-verified";
  if (value >= 0.6) return "text-primary";
  return "text-sev-medium";
}

/**
 * One candidate, in full, with the decision attached.
 *
 * The list can only show a summary, and a summary is not enough to approve on: the thing
 * that makes a stored field trustworthy is the verbatim quote behind it, and a quote is
 * unreadable at list density. So the decision lives here, next to the evidence, rather
 * than behind a checkbox that says "3 selected".
 *
 * Approving from here is the same call the list's Store button makes, which is the same
 * promotion path the /review queue uses. There is one way into the record.
 */
export function CandidateModal({
  candidate,
  kind,
  open,
  onOpenChange,
  onApprove,
  onReject,
  busy,
}: {
  candidate: DiscoveryCandidate | null;
  kind: DiscoveryKindConfig;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  if (!candidate) return null;

  const stored = candidate.stored_id !== null;
  const rejected = candidate.decision === "rejected";
  const blocked = !stored && candidate.blocked_reason !== null;
  const decided = stored || rejected;
  const quoted = candidate.fields.filter((field) => field.evidence).length;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(42rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          <div className="flex items-start gap-2 border-b border-border px-4 py-3">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title
                className={cn(
                  "text-sm font-medium text-foreground",
                  candidate.model_code ? "font-mono" : null,
                )}
              >
                {candidate.title ?? "Not identified"}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="mt-0.5 text-2xs text-muted-foreground">
                {candidate.subtitle ?? kind.noun}
                {candidate.hq_country ? ` · ${candidate.hq_country}` : ""}
              </DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close className="rounded-sm p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <X className="size-4" />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <ConfidenceChip level="ai_extracted" />
              {candidate.overall_confidence !== null ? (
                <span
                  className={cn(
                    "figure",
                    confidenceTone(candidate.overall_confidence),
                  )}
                >
                  {(candidate.overall_confidence * 100).toFixed(0)}% overall
                </span>
              ) : null}
              <span className="figure text-muted-foreground">
                {candidate.field_count} field
                {candidate.field_count === 1 ? "" : "s"}
              </span>
              <span className="figure text-muted-foreground">
                {quoted} quoted
              </span>
              {stored ? <Badge variant="success">Stored</Badge> : null}
              {rejected ? <Badge variant="outline">Discarded</Badge> : null}
              {!decided && candidate.matches_existing_id ? (
                <Badge variant="warning">
                  Enriches {candidate.matches_existing_label}
                </Badge>
              ) : null}
            </div>

            {blocked ? (
              <p className="flex items-start gap-1.5 rounded-md border border-sev-medium/40 bg-sev-medium/[0.06] px-2.5 py-2 text-2xs leading-relaxed text-sev-medium">
                <Ban className="mt-px size-3 shrink-0" />
                {candidate.blocked_reason}
              </p>
            ) : null}

            {candidate.relevance_reason ? (
              <p className="text-2xs leading-relaxed text-muted-foreground">
                {candidate.relevance_reason}
              </p>
            ) : null}

            {candidate.oil_gas_evidence ? (
              <blockquote className="flex gap-1.5 border-l-2 border-primary/40 pl-2 text-2xs italic leading-relaxed text-muted-foreground">
                <Quote className="mt-0.5 size-2.5 shrink-0 text-primary/60" />
                {candidate.oil_gas_evidence}
              </blockquote>
            ) : null}

            {candidate.source_url ? (
              <a
                href={candidate.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="flex items-center gap-1 truncate font-mono text-[0.625rem] text-primary hover:underline"
              >
                <ExternalLink className="size-2.5 shrink-0" />
                {candidate.source_url}
              </a>
            ) : null}

            {/* Every field that would be written, with the quote it rests on. This is
                the whole basis for approving, so it is not behind a disclosure. */}
            <div className="overflow-hidden rounded-md border border-border">
              <p className="border-b border-border bg-background/50 px-2.5 py-1.5 label-xs text-foreground">
                {candidate.fields.length} field
                {candidate.fields.length === 1 ? "" : "s"} that would be stored
              </p>
              <dl className="divide-y divide-border/60">
                {candidate.fields.map((field) => (
                  <div key={field.field_name} className="px-2.5 py-1.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-2xs text-muted-foreground">
                        {fieldLabel(field.field_name)}
                      </dt>
                      <dd className="figure min-w-0 flex-1 text-right text-foreground">
                        {renderValue(field)}
                        {field.confidence !== null ? (
                          <span
                            className={cn(
                              "ml-1.5",
                              confidenceTone(field.confidence),
                            )}
                          >
                            {(field.confidence * 100).toFixed(0)}%
                          </span>
                        ) : null}
                      </dd>
                    </div>
                    {field.evidence ? (
                      <p className="mt-0.5 text-[0.625rem] italic leading-relaxed text-muted-foreground/80">
                        “{field.evidence}”
                      </p>
                    ) : (
                      <p className="mt-0.5 text-[0.625rem] text-sev-medium">
                        No quote — this field will be refused on store.
                      </p>
                    )}
                  </div>
                ))}
              </dl>
            </div>

            {candidate.unresolved.length ? (
              <p className="text-2xs text-sev-medium">
                Mentioned but not stated clearly:{" "}
                {candidate.unresolved.map((name) => humanise(name)).join(", ")}
              </p>
            ) : null}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5">
            <p className="text-2xs text-muted-foreground">
              {decided
                ? stored
                  ? "Already in the record."
                  : "Discarded; it stays listed on the run."
                : "Approving writes it with provenance for every quoted field."}
            </p>
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                variant="ghost"
                onClick={onReject}
                disabled={busy || decided}
              >
                <X />
                Discard
              </Button>
              <Button
                size="sm"
                onClick={onApprove}
                disabled={busy || decided || blocked}
                title={blocked ? candidate.blocked_reason ?? undefined : undefined}
              >
                {busy ? <Loader2 className="animate-spin" /> : <Check />}
                Approve
              </Button>
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** The button the list uses to open this. Kept here so the two stay in step. */
export function ReviewButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1 text-2xs text-primary hover:underline"
    >
      <Database className="size-3" />
      Review and approve
    </button>
  );
}
