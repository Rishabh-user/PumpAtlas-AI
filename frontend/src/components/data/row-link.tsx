"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

import { LoadingOverlay } from "@/components/data/loading-overlay";
import { isPlainLeftClick } from "@/lib/nav";

/**
 * A link out of a list row, with the wait made visible.
 *
 * Opening a vendor is not one query: the detail page fetches the profile, the version
 * history and the contact details, each against a database roughly 300ms away. Until
 * they all return the browser shows the list it was already showing, so the click reads
 * as having missed — the same complaint pagination had, in the place people click most.
 *
 * It stays a real anchor, so middle-click and "open in new tab" work as they always did;
 * only the plain left click is taken over, and only to put the overlay up.
 */
export function RowLink({
  href,
  label,
  className,
  title,
  children,
}: {
  href: string;
  /** What the overlay says, e.g. "Opening Amarinth…". */
  label?: string;
  className?: string;
  title?: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <>
      {pending ? <LoadingOverlay label={label ?? "Loading…"} /> : null}
      <a
        href={href}
        title={title}
        className={className}
        onClick={(event) => {
          if (pending) {
            event.preventDefault();
            return;
          }
          if (!isPlainLeftClick(event)) return;
          event.preventDefault();
          startTransition(() => router.push(href));
        }}
      >
        {children}
      </a>
    </>
  );
}
