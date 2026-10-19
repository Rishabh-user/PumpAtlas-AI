import { cn } from "@/lib/utils";

/**
 * How much of each specification group a record holds, as six segments.
 *
 * The list showed one percentage against 437 tracked fields. A pump with a full
 * datasheet read as "6.4%" and sat indistinguishable from a row nobody had touched,
 * because 60 commercial, 52 delivery and 55 operational fields stay empty until
 * somebody quotes the thing — and no datasheet will ever fill them.
 *
 * Six segments say which part is known. A record with a strong technical bar and five
 * empty ones is well documented and unquoted; one with six empty bars is untouched.
 * The single percentage cannot tell those apart, and they call for different work.
 */

/** Canonical order, matching the panels on the profile page. */
const GROUPS: Array<[key: string, short: string, label: string]> = [
  ["technical", "T", "Technical"],
  ["commercial", "C", "Commercial"],
  ["dimensional", "W", "Weights & dimensions"],
  ["delivery", "D", "Delivery"],
  ["operational", "O", "Operational track record"],
  ["administrative", "A", "Administrative & compliance"],
];

export type SpecCoverage = Record<string, { recorded: number; tracked: number }>;

/** Fill is scaled against a realistic ceiling, not against every tracked field.
 *
 * A third of a group is a thoroughly documented one — a datasheet answers 16 of 144
 * technical fields. Scaling to 144 would render every real record as a sliver and
 * defeat the point of showing it at all. */
const FULL_AT = 0.33;

export function SpecCoverageBar({
  coverage,
  className,
}: {
  coverage: SpecCoverage | null | undefined;
  className?: string;
}) {
  if (!coverage) return <span className="text-muted-foreground">—</span>;

  const parts = GROUPS.map(([key, short, label]) => {
    const entry = coverage[key];
    const recorded = entry?.recorded ?? 0;
    const tracked = entry?.tracked ?? 0;
    const share = tracked > 0 ? recorded / tracked : 0;
    return { key, short, label, recorded, tracked, share };
  });

  const title = parts
    .map((part) => `${part.label} ${part.recorded}/${part.tracked}`)
    .join("\n");

  return (
    <span
      className={cn("inline-flex items-end gap-px align-middle", className)}
      title={title}
      aria-label={title.replace(/\n/g, ", ")}
    >
      {parts.map((part) => {
        const filled = Math.min(1, part.share / FULL_AT);
        return (
          <span
            key={part.key}
            className="relative block h-3.5 w-1.5 overflow-hidden rounded-[1px] bg-muted"
          >
            {part.recorded > 0 ? (
              <span
                className={cn(
                  "absolute inset-x-0 bottom-0 block rounded-[1px]",
                  filled >= 0.66
                    ? "bg-conf-verified"
                    : filled >= 0.33
                      ? "bg-primary"
                      : "bg-sev-medium",
                )}
                // A recorded group never renders as nothing: one field out of 144 is
                // still the difference between "started" and "untouched".
                style={{ height: `${Math.max(18, filled * 100)}%` }}
              />
            ) : null}
          </span>
        );
      })}
    </span>
  );
}

/** The six letters, for a table header that has to explain the bars above. */
export function SpecCoverageLegend({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-px", className)}>
      {GROUPS.map(([key, short, label]) => (
        <span
          key={key}
          title={label}
          className="block w-1.5 text-center text-[0.5rem] leading-none text-muted-foreground"
        >
          {short}
        </span>
      ))}
    </span>
  );
}
