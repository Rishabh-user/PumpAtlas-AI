"use client";

import { Ban, ExternalLink, Quote } from "lucide-react";

import { ConfidenceChip } from "@/components/data/confidence";
import { EmptyState } from "@/components/data/states";
import { ReviewButton } from "@/components/discovery/candidate-modal";
import type { DiscoveryKindConfig } from "@/components/discovery/kinds";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  fieldLabel,
  humanise,
  labelFor,
  pumpTypeCode,
  standardLabel,
  vendorTierLabel,
} from "@/lib/labels";
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
  // Enum-shaped values read better as the domain says them.
  return /^[a-z0-9_]+$/.test(text) ? labelFor(field.field_name, text) : text;
}

/** Low confidence is the reviewer's cue to check the quote before accepting. */
function confidenceTone(value: number | null): string {
  if (value === null) return "text-muted-foreground";
  if (value >= 0.85) return "text-conf-verified";
  if (value >= 0.6) return "text-primary";
  return "text-sev-medium";
}

function Candidate({
  candidate,
  kind,
  checked,
  onToggle,
  onReview,
}: {
  candidate: DiscoveryCandidate;
  kind: DiscoveryKindConfig;
  checked: boolean;
  onToggle: () => void;
  onReview: () => void;
}) {
  const stored = candidate.stored_id !== null;
  const rejected = candidate.decision === "rejected";
  const blocked = !stored && candidate.blocked_reason !== null;
  const decided = stored || rejected;

  return (
    <li
      className={cn(
        "px-3 py-2.5 transition-colors",
        checked && !decided ? "bg-primary/[0.06]" : null,
        decided ? "opacity-60" : null,
      )}
    >
      <div className="flex items-start gap-2.5">
        <Checkbox
          className="mt-1"
          checked={checked}
          // A blocked candidate would fail on submit, so it cannot be picked. The reason
          // is shown below rather than left for the reviewer to discover after clicking.
          disabled={decided || blocked}
          onCheckedChange={onToggle}
          aria-label={`Select ${candidate.title ?? "candidate"}`}
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "text-xs font-medium text-foreground",
                candidate.model_code ? "font-mono" : null,
              )}
            >
              {candidate.title ?? "Not identified"}
            </span>
            {candidate.subtitle ? (
              <span className="text-2xs text-muted-foreground">
                {candidate.subtitle}
              </span>
            ) : null}
            {candidate.pump_type ? (
              <Badge variant="outline">
                {pumpTypeCode(candidate.pump_type)}
              </Badge>
            ) : null}
            {candidate.applicable_standard ? (
              <Badge variant="outline">
                {standardLabel(candidate.applicable_standard)}
              </Badge>
            ) : null}
            {candidate.vendor_tier ? (
              <Badge variant="outline">
                {vendorTierLabel(candidate.vendor_tier)}
              </Badge>
            ) : null}
            <ConfidenceChip level="ai_extracted" />
            {candidate.overall_confidence !== null ? (
              <span
                className={cn(
                  "figure",
                  confidenceTone(candidate.overall_confidence),
                )}
              >
                {(candidate.overall_confidence * 100).toFixed(0)}%
              </span>
            ) : null}
            <span className="figure text-muted-foreground">
              {candidate.field_count} field
              {candidate.field_count === 1 ? "" : "s"}
            </span>

            {stored ? <Badge variant="success">Stored</Badge> : null}
            {rejected ? <Badge variant="outline">Discarded</Badge> : null}
            {!decided && candidate.matches_existing_id ? (
              <Badge
                variant="warning"
                title={`Will enrich the existing record "${candidate.matches_existing_label}" rather than create a new one`}
              >
                Updates {candidate.matches_existing_label}
              </Badge>
            ) : null}
          </div>

          {blocked ? (
            <p className="mt-1 flex items-start gap-1.5 text-2xs leading-relaxed text-sev-medium">
              <Ban className="mt-px size-3 shrink-0" />
              {candidate.blocked_reason}
            </p>
          ) : null}

          {/* An API 610 type code is the configuration a pump is built in, not its name.
            * Saying so here means the reviewer is not surprised by a record under a
            * different designation afterwards. */}
          {!blocked && candidate.stored_as ? (
            <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
              Stored as{" "}
              <span className="font-mono text-foreground">{candidate.stored_as}</span> —
              the type code is kept as the pump&apos;s configuration, not its name.
            </p>
          ) : null}

          {candidate.relevance_reason ? (
            <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
              {candidate.relevance_reason}
            </p>
          ) : null}

          {candidate.oil_gas_evidence ? (
            <blockquote className="mt-1.5 flex gap-1.5 border-l-2 border-primary/40 pl-2 text-2xs italic leading-relaxed text-muted-foreground">
              <Quote className="mt-0.5 size-2.5 shrink-0 text-primary/60" />
              {candidate.oil_gas_evidence}
            </blockquote>
          ) : null}

          {candidate.source_url ? (
            <a
              href={candidate.source_url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1.5 flex items-center gap-1 truncate font-mono text-[0.625rem] text-primary hover:underline"
            >
              <ExternalLink className="size-2.5 shrink-0" />
              {candidate.source_url}
            </a>
          ) : null}

          <div className="mt-1.5">
            <ReviewButton onClick={onReview} />
          </div>

          {candidate.fields.length ? (
            <details className="mt-1.5">
              <summary className="cursor-pointer text-2xs text-primary">
                {candidate.fields.length} field
                {candidate.fields.length === 1 ? "" : "s"} that would be stored
              </summary>
              <dl className="mt-1 divide-y divide-border/60">
                {candidate.fields.map((field) => (
                  <div key={field.field_name} className="py-1">
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
                            title="Model confidence for this field"
                          >
                            {(field.confidence * 100).toFixed(0)}%
                          </span>
                        ) : null}
                      </dd>
                    </div>
                    {field.evidence ? (
                      <p className="mt-0.5 truncate text-[0.625rem] italic text-muted-foreground/70">
                        “{field.evidence}”
                      </p>
                    ) : null}
                  </div>
                ))}
              </dl>
            </details>
          ) : null}

          {candidate.unresolved.length ? (
            <p className="mt-1 text-[0.625rem] text-sev-medium">
              Mentioned but not stated clearly:{" "}
              {candidate.unresolved.map((name) => humanise(name)).join(", ")}
            </p>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export function CandidateList({
  candidates,
  kind,
  selected,
  onToggle,
  onReview,
}: {
  candidates: DiscoveryCandidate[];
  kind: DiscoveryKindConfig;
  selected: string[];
  onToggle: (id: string) => void;
  /** Open one candidate in full, where the evidence is readable and approvable. */
  onReview: (candidate: DiscoveryCandidate) => void;
}) {
  if (!candidates.length) {
    return <EmptyState title={kind.emptyTitle} hint={kind.emptyHint} />;
  }

  return (
    <ul className="divide-y divide-border">
      {candidates.map((candidate) => (
        <Candidate
          key={candidate.id}
          candidate={candidate}
          kind={kind}
          checked={selected.includes(candidate.id)}
          onToggle={() => onToggle(candidate.id)}
          onReview={() => onReview(candidate)}
        />
      ))}
    </ul>
  );
}
