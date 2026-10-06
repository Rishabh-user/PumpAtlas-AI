"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { LoadingOverlay } from "@/components/data/loading-overlay";
import { Button } from "@/components/ui/button";
import { isPlainLeftClick } from "@/lib/nav";

/**
 * Previous / next across a paged result set, with a pending state.
 *
 * Extracted because `/pumps` and `/review` each carried their own copy and `/vendors`
 * carried none, so 75 vendors showed the first 25 with no way to reach the rest.
 *
 * It is a client component for one reason: these pages are server-rendered against a
 * database roughly 300ms away per query, so a page change is a visible pause. A plain
 * `<Link>` gives no sign that anything is happening, and the honest reading of a table
 * that has not changed is that the click missed. `useTransition` around `router.push`
 * makes the wait visible — which is all that was wrong, since the navigation itself
 * always worked.
 *
 * The buttons stay real anchors so middle-click and "open in new tab" behave; the click
 * handler only takes over the ordinary left-click path.
 */
export function Pager({
  total,
  offset,
  limit,
  prevHref,
  nextHref,
  noun = "records",
}: {
  total: number;
  offset: number;
  limit: number;
  /** Null on the first page. */
  prevHref: string | null;
  /** Null on the last page. */
  nextHref: string | null;
  /** Plural noun for the screen-reader label, e.g. "vendors". */
  noun?: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  // Which page was clicked, so the overlay can say where it is going rather than just
  // that something is happening.
  const [target, setTarget] = useState<number | null>(null);

  if (total <= limit) return null;

  const shown = Math.min(offset + limit, total);
  const currentPage = Math.floor(offset / limit) + 1;
  const lastPage = Math.ceil(total / limit);

  const go = (href: string, page: number) => {
    setTarget(page);
    startTransition(() => router.push(href));
  };

  return (
    <>
      {pending ? (
        <LoadingOverlay label={`Loading page ${target ?? currentPage}…`} />
      ) : null}
      <nav
        aria-label={`${noun} pagination`}
        aria-busy={pending}
        className="flex items-center justify-between text-2xs text-muted-foreground"
      >
        <span className="font-mono">
          {offset + 1}&ndash;{shown} of {total.toLocaleString("en-GB")}
        </span>
        <div className="flex items-center gap-1.5">
          <span className="mr-1 font-mono">
            Page {currentPage} of {lastPage}
          </span>
          <Step
            href={prevHref}
            label="Previous"
            page={currentPage - 1}
            pending={pending}
            onGo={go}
          />
          <Step
            href={nextHref}
            label="Next"
            page={currentPage + 1}
            pending={pending}
            onGo={go}
          />
        </div>
      </nav>
    </>
  );
}

function Step({
  href,
  label,
  page,
  pending,
  onGo,
}: {
  href: string | null;
  label: string;
  page: number;
  pending: boolean;
  onGo: (href: string, page: number) => void;
}) {
  if (href === null) {
    return (
      <Button variant="outline" size="sm" disabled>
        {label}
      </Button>
    );
  }
  return (
    <Button variant="outline" size="sm" disabled={pending} asChild>
      {/* A real href, so middle-click and "open in new tab" still work. The handler
          takes over only the plain left-click, and only to make the wait visible. */}
      <a
        href={href}
        onClick={(event) => {
          // `disabled` on an `asChild` Button styles the wrapper and leaves the anchor
          // clickable, so the guard has to be here or a second click during the wait
          // starts another navigation while the button looks dead.
          if (pending) {
            event.preventDefault();
            return;
          }
          if (!isPlainLeftClick(event)) return;
          event.preventDefault();
          onGo(href, page);
        }}
      >
        {label}
      </a>
    </Button>
  );
}
