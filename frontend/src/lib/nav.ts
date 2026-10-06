import type { MouseEvent } from "react";

/**
 * Whether a click is the ordinary "go there" click, or something the browser should keep.
 *
 * A middle click, or one with ctrl/cmd/shift/alt held, means "open in a new tab" or "new
 * window" — taking those over would break a habit people rely on in a list they are
 * comparing rows from. Only the plain left click is intercepted, and only to show that
 * the wait has started.
 *
 * A plain module with no "use client": both the pager and the row link need it, and an
 * export from a client module is a client reference that a server component cannot call.
 */
export function isPlainLeftClick(event: MouseEvent<HTMLElement>): boolean {
  return !(
    event.defaultPrevented ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    event.button !== 0
  );
}
