"use client";

import { useState } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { fieldLabel, humanise } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { Scorecard, ScorecardCriterion } from "@/types/api";

/**
 * What a score is made of, and why it is that number.
 *
 * The cards reported a figure and a grade and nothing else, which is the wrong amount
 * of information for a number somebody has to defend in a tender review. A buyer
 * looking at "78.2 · B" cannot tell whether it rests on seven criteria or two, which
 * of them were even answerable, or what a different pump would have to do to beat it.
 *
 * The weighted mean is over *evaluated* criteria only, renormalised. That is the part
 * worth showing rather than describing: 78.2 here comes from two criteria carrying
 * 0.19 of the nominal weight between them, and the table makes that visible instead of
 * leaving a reader to wonder why five rows of zeros average to 78.
 */

const GRADE_BANDS = [
  ["A", "85 and above"],
  ["B", "70 – 84.9"],
  ["C", "55 – 69.9"],
  ["D", "40 – 54.9"],
  ["E", "below 40"],
] as const;

/** What each card is for, in the words of the decision it supports. */
const PURPOSE: Record<string, string> = {
  technical_fit:
    "How well this model meets the requirement profile's duty point and hard requirements. Standards, area classification, certifications and NACE are pass/fail gates — a mismatch disqualifies the candidate rather than merely scoring it low.",
  commercial_fit:
    "Price against budget, life-cycle cost, warranty and payment terms. These come from a quotation, not a datasheet, which is why the card is usually unscored until somebody has been asked for a price.",
  delivery_risk:
    "Lead time, on-time delivery history, supply-chain exposure and origin. Higher is better despite the name — it scores delivery confidence.",
  data_confidence:
    "How much the other three can be trusted. A well-ranked candidate with a data-confidence grade of E is a research task, not a recommendation.",
  overall:
    "The weighted composite. A card that could not be scored contributes no opinion and its weight is shared out among the rest, rather than being averaged in as a zero.",
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function ScorecardExplainer({
  card,
  open,
  onOpenChange,
}: {
  card: Scorecard;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const criteria = Object.entries(card.breakdown ?? {}) as Array<
    [string, ScorecardCriterion]
  >;
  const evaluated = criteria.filter(([, c]) => c.score !== null);
  const missing = criteria.filter(([, c]) => c.score === null);

  // The denominator the card actually divided by.
  const liveWeight = evaluated.reduce((sum, [, c]) => sum + c.weight, 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle className="flex items-baseline gap-2">
            {humanise(card.kind)}
            <span className="figure text-base text-foreground">
              {card.score === null ? "Not scored" : card.score.toFixed(1)}
            </span>
            {card.grade ? (
              <span className="figure text-xs text-muted-foreground">
                grade {card.grade}
              </span>
            ) : null}
          </SheetTitle>
          <SheetDescription>
            {PURPOSE[card.kind] ?? "How this score is worked out."}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 py-3">
          {card.disqualified ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/[0.06] px-3 py-2">
              <p className="text-xs font-medium text-destructive">
                Disqualified — the overall score is forced to zero
              </p>
              <p className="mt-0.5 text-2xs text-muted-foreground">
                {card.disqualification_reason}
              </p>
            </div>
          ) : null}

          {/* ---- the arithmetic, not a description of it ---- */}
          <section>
            <p className="label-xs text-foreground">How this number is reached</p>
            {card.score === null ? (
              <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
                Not one criterion could be evaluated, so there is no score — which is a
                different statement from a score of zero. A zero would say this was
                assessed and found wanting. Nothing here has been recorded yet, so the
                card takes no part in the overall figure and its weight is shared among
                the cards that could be scored.
              </p>
            ) : (
              <>
                <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
                  A weighted mean over the {evaluated.length} criteri
                  {evaluated.length === 1 ? "on" : "a"} that could be evaluated. The
                  weights are renormalised across those, so a field nobody has recorded
                  does not quietly drag the score toward zero — the absence is reported
                  instead.
                </p>
                <pre className="mt-1.5 overflow-x-auto rounded bg-muted/40 px-2.5 py-2 text-[0.625rem] leading-relaxed text-foreground/85">
                  {evaluated
                    .map(
                      ([name, c]) =>
                        `${(c.score ?? 0).toFixed(1).padStart(6)} × ${c.weight.toFixed(2)}   ${fieldLabel(name) || name}`,
                    )
                    .join("\n")}
                  {`\n${"".padStart(6, "─")}───────────\n`}
                  {`  sum ÷ ${liveWeight.toFixed(2)} = ${card.score.toFixed(1)}`}
                </pre>
              </>
            )}
          </section>

          {/* ---- what each criterion read ---- */}
          {evaluated.length ? (
            <section>
              <p className="label-xs text-foreground">
                Criteria that could be scored ({evaluated.length})
              </p>
              <table className="mt-1 w-full text-2xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="py-1 text-left font-normal">Criterion</th>
                    <th className="py-1 text-right font-normal">Value</th>
                    <th className="py-1 text-right font-normal">Target</th>
                    <th className="py-1 text-right font-normal">Weight</th>
                    <th className="py-1 text-right font-normal">Score</th>
                    <th className="py-1 text-right font-normal">Of the total</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluated.map(([name, c]) => {
                    const share = liveWeight > 0 ? c.weight / liveWeight : 0;
                    return (
                      <tr key={name} className="border-b border-border/50">
                        <td className="py-1 pr-2 text-foreground">
                          {fieldLabel(name) || name}
                          <span className="block text-[0.625rem] text-muted-foreground">
                            {c.reason}
                          </span>
                        </td>
                        <td className="figure py-1 text-right">
                          {formatValue(c.value)}
                        </td>
                        <td className="figure py-1 text-right text-muted-foreground">
                          {formatValue(c.target)}
                        </td>
                        <td className="figure py-1 text-right text-muted-foreground">
                          {c.weight.toFixed(2)}
                        </td>
                        <td className="figure py-1 text-right text-foreground">
                          {(c.score ?? 0).toFixed(1)}
                        </td>
                        <td className="figure py-1 text-right text-muted-foreground">
                          {((c.score ?? 0) * share).toFixed(1)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          ) : null}

          {/* ---- and what it could not read ---- */}
          {missing.length ? (
            <section>
              <p className="label-xs text-foreground">
                Not recorded ({missing.length})
              </p>
              <p className="mt-0.5 text-2xs text-muted-foreground">
                These carry {missing.reduce((s, [, c]) => s + c.weight, 0).toFixed(2)} of
                the nominal weight. Recording them is what would move this score.
              </p>
              <ul className="mt-1 space-y-0.5">
                {missing.map(([name, c]) => (
                  <li
                    key={name}
                    className="flex items-baseline justify-between gap-3 border-b border-border/40 py-1 last:border-0"
                  >
                    <span className="text-2xs text-foreground">
                      {fieldLabel(name) || name}
                      <span className="block text-[0.625rem] text-muted-foreground">
                        {c.reason}
                      </span>
                    </span>
                    <span className="figure shrink-0 text-2xs text-muted-foreground">
                      weight {c.weight.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section>
            <p className="label-xs text-foreground">Grade bands</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {GRADE_BANDS.map(([grade, band]) => (
                <span
                  key={grade}
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[0.625rem]",
                    card.grade === grade
                      ? "border-primary/50 bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground",
                  )}
                >
                  <span className="font-mono font-medium">{grade}</span> {band}
                </span>
              ))}
            </div>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** Wraps a card so clicking it opens the explanation. */
export function ExplainableScore({
  card,
  children,
}: {
  card: Scorecard;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="block h-full w-full rounded-lg text-left transition-colors hover:ring-1 hover:ring-primary/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
        title={`How ${humanise(card.kind).toLowerCase()} is worked out`}
      >
        {children}
      </button>
      <ScorecardExplainer card={card} open={open} onOpenChange={setOpen} />
    </>
  );
}
