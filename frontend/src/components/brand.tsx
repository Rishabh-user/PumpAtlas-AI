import { cn } from "@/lib/utils";

/**
 * The mark is a volute — the spiral casing that turns a centrifugal impeller's velocity
 * into pressure. It is the one shape every pump in this database has in common.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={cn("size-5", className)}
      aria-hidden="true"
    >
      <path
        d="M12 4.6a7.4 7.4 0 1 0 7.4 7.4H12V4.6Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="square"
      />
      <circle cx="12" cy="12" r="2.1" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "text-sm font-semibold tracking-tight text-foreground",
        className,
      )}
    >
      Pump<span className="text-primary">Atlas</span>
    </span>
  );
}

export function WordmarkLarge() {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark className="size-7 text-primary" />
      <div>
        <p className="text-base font-semibold tracking-tight text-foreground">
          Pump<span className="text-primary">Atlas</span> AI
        </p>
        <p className="label-xs mt-px">Oil &amp; Gas pump intelligence</p>
      </div>
    </div>
  );
}

export function ByTargeticon({ className }: { className?: string }) {
  return (
    <p className={cn("text-2xs text-muted-foreground", className)}>
      by <span className="font-medium text-foreground/70">Targeticon</span>
    </p>
  );
}
