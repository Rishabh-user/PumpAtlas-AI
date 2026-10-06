"use client";

import type { ReactElement } from "react";

import { cn } from "@/lib/utils";

/**
 * The answer's prose, with its citation markers as things you can click.
 *
 * This replaces rendering the answer as flat pre-wrapped text. That was there for
 * a good reason — running model output through a markdown renderer invites it to
 * emit markup the `[R1]` markers then get lost inside — and the reason is handled
 * rather than ignored: the markers are matched in the *same pass* as the inline
 * emphasis, so a marker is recognised before any styling can swallow it.
 *
 * Nothing is ever set as HTML. This text is a model's prose about pages fetched
 * from the open web, so `dangerouslySetInnerHTML` would hand any of those pages a
 * script tag on this origin. Everything below builds React elements.
 *
 * The markdown subset is deliberately small — headings, ordered and unordered
 * items, nested sub-points, bold, inline code. A full parser would add surface
 * this screen has no use for, and would still need the marker handling below.
 */

/** Markers and inline emphasis in one pass. The capturing group keeps the
 *  delimiters when splitting. */
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[RW]\d{1,2}\])/g;

type ProseItem = { text: string; children: string[] };
type OpenList = { ordered: boolean; items: ProseItem[] };

function renderInline(text: string, onMarker: (marker: string) => void) {
  return text.split(INLINE).map((part, index) => {
    if (!part) return null;

    if (/^\[[RW]\d{1,2}\]$/.test(part)) {
      const marker = part.slice(1, -1);
      const isRecord = marker.startsWith("R");
      return (
        <button
          key={index}
          type="button"
          onClick={() => onMarker(marker)}
          title={
            isRecord
              ? "A record this platform holds — open it to see what is actually recorded"
              : "A page the answer read — open it to check the claim against its source"
          }
          className={cn(
            "mx-0.5 inline-flex items-center rounded border px-1 align-baseline",
            "font-mono text-[0.625rem] leading-none transition-colors",
            isRecord
              ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
              : "border-border bg-muted text-muted-foreground hover:text-foreground",
          )}
        >
          {marker}
        </button>
      );
    }

    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-medium text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }

    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={index} className="rounded bg-muted px-1 font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    }

    return <span key={index}>{part}</span>;
  });
}

export function AnswerProse({
  text,
  onMarker,
}: {
  text: string;
  /** Called with "R1" / "W1" when a marker is clicked. */
  onMarker: (marker: string) => void;
}) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactElement[] = [];
  let list: OpenList | null = null;

  const flush = () => {
    const finished = list;
    if (!finished) return;
    const Tag = finished.ordered ? "ol" : "ul";
    nodes.push(
      <Tag
        key={`list-${nodes.length}`}
        className={cn(
          "my-1.5 space-y-1 pl-4",
          finished.ordered ? "list-decimal" : "list-disc",
        )}
      >
        {finished.items.map((item, index) => (
          <li key={index} className="leading-relaxed">
            {renderInline(item.text, onMarker)}
            {item.children.length > 0 ? (
              <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-muted-foreground">
                {item.children.map((child, childIndex) => (
                  <li key={childIndex}>{renderInline(child, onMarker)}</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </Tag>,
    );
    list = null;
  };

  const push = (ordered: boolean, value: string) => {
    if (!list || list.ordered !== ordered) {
      flush();
      list = { ordered, items: [] };
    }
    list.items.push({ text: value, children: [] });
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    // A blank line does *not* close a list. The model separates numbered items
    // with one, and closing on it restarts the numbering at every item — eight
    // suppliers each rendering as "1.". What ends a list is a line that is not a
    // list item, and those flush on their own way in.
    if (!line.trim()) continue;

    const indented = /^\s+\S/.test(raw);
    // `flush` and `push` reassign `list` from inside closures, which the
    // compiler's flow analysis cannot follow — without the cast it concludes
    // `list` is still the `null` it was initialised to and narrows it away.
    const open = list as OpenList | null;
    const current = open ? open.items[open.items.length - 1] : undefined;

    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      nodes.push(
        <p key={`h-${nodes.length}`} className="mt-2 font-medium text-foreground">
          {renderInline(heading[1] ?? "", onMarker)}
        </p>,
      );
      continue;
    }

    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    // An indented bullet belongs to the item above it, not to a new list. The
    // model writes "1. Sulzer" then an indented "- Type: …" beneath it.
    if (bullet && indented && current) {
      current.children.push(bullet[1] ?? "");
      continue;
    }

    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      push(true, ordered[1] ?? "");
      continue;
    }
    if (bullet) {
      push(false, bullet[1] ?? "");
      continue;
    }

    // A wrapped line belonging to whatever came last.
    if (current && indented) {
      if (current.children.length > 0) {
        current.children[current.children.length - 1] += ` ${line.trim()}`;
      } else {
        current.text += ` ${line.trim()}`;
      }
      continue;
    }

    flush();
    nodes.push(
      <p key={`p-${nodes.length}`} className="my-1.5 leading-relaxed">
        {renderInline(line, onMarker)}
      </p>,
    );
  }
  flush();

  return <div className="text-xs text-foreground">{nodes}</div>;
}
