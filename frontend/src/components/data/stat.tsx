import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * A figure with its caption. Rendered as a strip of hairline-separated cells rather
 * than a row of cards — on a dark surface a row of boxes reads as clutter, and the
 * numbers are what the eye is looking for.
 */
export function StatStrip({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid divide-y divide-border overflow-hidden rounded-lg border border-border bg-card sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-5",
        "sm:[&>*:not(:first-child)]:border-l sm:[&>*]:border-border",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "good" | "warn" | "risk";
}) {
  const valueTone =
    tone === "risk"
      ? "text-sev-critical"
      : tone === "warn"
        ? "text-sev-medium"
        : tone === "good"
          ? "text-conf-verified"
          : "text-foreground";
  return (
    <div className="px-3.5 py-3">
      <p className="label-xs">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-2xl font-medium tabular-nums leading-none",
          valueTone,
        )}
      >
        {value}
      </p>
      {hint ? (
        <p className="mt-1.5 text-2xs leading-snug text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function StatStripSkeleton({ count = 5 }: { count?: number }) {
  return (
    <StatStrip>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="px-3.5 py-3">
          <Skeleton className="h-2.5 w-20" />
          <Skeleton className="mt-2 h-6 w-12" />
          <Skeleton className="mt-2 h-2 w-28" />
        </div>
      ))}
    </StatStrip>
  );
}
