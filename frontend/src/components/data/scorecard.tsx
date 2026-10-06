import { cn } from "@/lib/utils";

const EM_DASH = "—";

function gradeText(grade: string | null | undefined): string {
  switch (grade) {
    case "A":
      return "text-grade-a";
    case "B":
      return "text-grade-b";
    case "C":
      return "text-grade-c";
    case "D":
      return "text-grade-d";
    default:
      return "text-grade-e";
  }
}

export function scoreText(score: number | null | undefined): string {
  if (score === null || score === undefined) return "text-muted-foreground";
  if (score >= 85) return "text-grade-a";
  if (score >= 70) return "text-grade-b";
  if (score >= 55) return "text-grade-c";
  if (score >= 40) return "text-grade-d";
  return "text-grade-e";
}

function scoreBar(score: number): string {
  if (score >= 85) return "bg-grade-a";
  if (score >= 70) return "bg-grade-b";
  if (score >= 55) return "bg-grade-c";
  if (score >= 40) return "bg-grade-d";
  return "bg-grade-e";
}

/**
 * A score shown with what it does not know.
 *
 * The missing-field count sits next to the number on purpose: a high score resting on
 * thin data is the single most misleading thing this product could put in front of a
 * buyer, and burying that in a detail view is how it would happen.
 */
export function ScoreCard({
  label,
  score,
  grade,
  missing,
}: {
  label: string;
  score: number | null;
  grade?: string | null;
  missing?: number;
}) {
  const value = score ?? 0;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label-xs truncate">{label}</span>
        {grade ? (
          <span className={cn("font-mono text-xs font-bold", gradeText(grade))}>
            {grade}
          </span>
        ) : null}
      </div>
      <div
        className={cn(
          "mt-1 font-mono text-xl font-medium tabular-nums",
          scoreText(score),
        )}
      >
        {score === null ? EM_DASH : value.toFixed(1)}
      </div>
      <div className="mt-2 h-0.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", scoreBar(value))}
          style={{ width: String(Math.max(0, Math.min(100, value))) + "%" }}
        />
      </div>
      {missing !== undefined && missing > 0 ? (
        <p className="mt-1.5 text-2xs text-sev-medium">
          {missing} field{missing === 1 ? "" : "s"} not recorded
        </p>
      ) : null}
    </div>
  );
}
