import type { ReactNode } from "react";
import { CircleAlert, CircleCheck, Inbox } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  hint,
  action,
  className,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center px-6 py-12 text-center",
        className,
      )}
    >
      <Inbox className="size-5 text-muted-foreground/60" />
      <p className="mt-3 text-xs font-medium text-foreground">{title}</p>
      {hint ? (
        <p className="mt-1 max-w-sm text-2xs leading-relaxed text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  message,
  className,
}: {
  message: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2.5 rounded-lg border border-destructive/30 bg-destructive/[0.07] px-3 py-2.5",
        className,
      )}
    >
      <CircleAlert className="mt-px size-4 shrink-0 text-destructive" />
      <div className="min-w-0">
        <p className="text-xs font-medium text-destructive">
          Could not load this view
        </p>
        <p className="mt-0.5 break-words text-2xs leading-relaxed text-muted-foreground">
          {message}
        </p>
      </div>
    </div>
  );
}

export function SuccessNote({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-1.5 text-2xs text-conf-verified">
      <CircleCheck className="size-3.5 shrink-0" />
      {children}
    </p>
  );
}

/** Field list row. Label left, value right, hairline between. */
/**
 * A label and its value.
 *
 * `stacked` puts the value on its own line beneath the label, left aligned. That is
 * the right shape for a value that is really a list - "Petrochemical processing,
 * Chemical processing, Refinery offsites, Drainage" - which squeezed into a
 * right-aligned column reads as a ragged block of text with no obvious left edge.
 * The caller decides, because only the caller has the value before it is formatted.
 */
export function FieldRow({
  label,
  children,
  className,
  stacked = false,
}: {
  label: string;
  children: ReactNode;
  className?: string;
  stacked?: boolean;
}) {
  if (stacked) {
    return (
      <div
        className={cn(
          "border-b border-border/60 py-1.5 last:border-0",
          className,
        )}
      >
        <span className="block text-2xs text-muted-foreground">{label}</span>
        <span className="figure mt-0.5 block text-foreground [overflow-wrap:anywhere]">
          {children}
        </span>
      </div>
    );
  }
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-4 border-b border-border/60 py-1.5 last:border-0",
        className,
      )}
    >
      {/* The label keeps a floor so a long value cannot squeeze it to a stack of
          single letters, which is what "Service application" became. */}
      <span className="min-w-[5.5rem] shrink text-2xs text-muted-foreground">
        {label}
      </span>
      {/* `shrink-0` here was the bug. A value like "Petrochemical processing,
          Chemical processing, Refinery offsites, Drainage" refused to shrink, so it
          kept its full single-line width, crushed the label beside it and ran out of
          the card entirely - which is why "Mo" from the Commercial panel appeared
          inside the Technical one. It shrinks and wraps now. */}
      <span className="figure min-w-0 text-right text-foreground [overflow-wrap:anywhere]">
        {children}
      </span>
    </div>
  );
}

export function TableSkeleton({
  rows = 6,
  cols = 6,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="divide-y divide-border">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex items-center gap-3 px-3 py-2.5">
          {Array.from({ length: cols }, (_, col) => (
            <Skeleton
              key={col}
              className="h-2.5"
              style={{
                width:
                  col === 0 ? "22%" : String(Math.round(78 / (cols - 1))) + "%",
              }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
