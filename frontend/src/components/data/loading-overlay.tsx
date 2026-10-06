"use client";

import { Loader2 } from "lucide-react";

/**
 * A full-screen "working on it" while a navigation is in flight.
 *
 * These list pages are server-rendered against a database roughly 300ms away, so a page
 * change is a real pause with nothing on screen to explain it. An indicator tucked beside
 * the pager was easy to miss — the eye is on the table, which has not changed yet.
 *
 * Sitting above everything also has a useful side effect: it swallows clicks, so a second
 * impatient click cannot start a second navigation while the first is still running.
 *
 * `z-[60]` puts it over the sheets and dialogs, which sit at `z-50` — a navigation
 * started from inside one should still show its progress on top.
 */
export function LoadingOverlay({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-background/70 backdrop-blur-sm"
    >
      <div className="flex flex-col items-center gap-2.5 rounded-lg border border-border bg-card px-6 py-5 shadow-lg">
        <Loader2 className="size-6 animate-spin text-primary" />
        <span className="text-xs text-foreground">{label}</span>
      </div>
    </div>
  );
}
