"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, Play, Sparkles, Square, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { clientFetch } from "@/lib/api-client";

/**
 * Fill the gaps in records you already have, one at a time, while you watch.
 *
 * The operation the AI search panel is repeatedly mistaken for, and its opposite. That
 * panel *discovers* subjects the database has never heard of, which is why it asks for
 * a type, a duty and a country — they narrow what to go looking for. This asks nothing,
 * because the subject of each search is already on the list and what it is missing is
 * already known.
 *
 * Driven from the browser rather than by a bulk endpoint on purpose: each record is a
 * separate run with its own provenance and its own new version, so stopping half way
 * leaves fifteen finished records rather than one abandoned transaction. There is no
 * Redis behind this, so a server-side loop would die on the next API restart anyway —
 * one that runs while you watch it is at least honest about what it is.
 *
 * Generic over what is being filled: vendors and pump models want the same loop and
 * disagree only about which records qualify, what counts as a gap, and which endpoint
 * does the reading.
 */

export interface FillGapsTarget<T> {
  id(item: T): string;
  label(item: T): string;
  /** Which fields or groups this record is missing and the web might answer. */
  gaps(item: T): string[];
  /** Why a record cannot be enriched at all, or null when it can. */
  blocked?(item: T): string | null;
  /** `POST` here to start a run for one record. */
  enrichPath(item: T): string;
  /** `GET` here to watch that run. */
  watchPath(runId: string): string;
  /** `GET` here to re-read the record once the run has settled. */
  refetchPath(item: T): string;
}

interface Outcome {
  id: string;
  label: string;
  state: "running" | "done" | "failed";
  gained: string[];
  error?: string;
}

export function FillGaps<T>({
  items,
  target,
  noun,
  nounPlural,
  description,
}: {
  items: T[];
  target: FillGapsTarget<T>;
  noun: string;
  nounPlural: string;
  description: string;
}) {
  const router = useRouter();

  const blocked = items.filter((item) => target.blocked?.(item));
  const candidates = items.filter(
    (item) => !target.blocked?.(item) && target.gaps(item).length > 0,
  );

  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  // A ref, not state: the loop reads it between records, and state would be stale.
  const stop = useRef(false);

  async function runOne(item: T): Promise<Outcome> {
    const id = target.id(item);
    const label = target.label(item);
    const before = target.gaps(item);
    try {
      const started = await clientFetch<{ run_id: string }>(
        target.enrichPath(item),
        { method: "POST" },
      );
      for (let tick = 0; tick < 240; tick += 1) {
        if (stop.current) break;
        await new Promise((resolve) => setTimeout(resolve, 2500));
        const run = await clientFetch<{ is_running: boolean }>(
          target.watchPath(started.run_id),
        );
        if (!run.is_running) break;
      }
      const fresh = await clientFetch<T>(target.refetchPath(item));
      const after = target.gaps(fresh);
      return {
        id,
        label,
        state: "done",
        gained: before.filter((gap) => !after.includes(gap)),
      };
    } catch (caught) {
      return {
        id,
        label,
        state: "failed",
        gained: [],
        error: caught instanceof Error ? caught.message : "failed",
      };
    }
  }

  async function run() {
    stop.current = false;
    setRunning(true);
    setOutcomes([]);
    for (const item of candidates) {
      if (stop.current) break;
      const id = target.id(item);
      setOutcomes((prev) => [
        ...prev,
        { id, label: target.label(item), state: "running", gained: [] },
      ]);
      const outcome = await runOne(item);
      setOutcomes((prev) =>
        prev.map((entry) => (entry.id === outcome.id ? outcome : entry)),
      );
    }
    setRunning(false);
    router.refresh();
  }

  const finished = outcomes.filter((entry) => entry.state !== "running");
  const filled = finished.filter((entry) => entry.gained.length).length;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline">
          <Sparkles />
          Fill gaps from the web
        </Button>
      </SheetTrigger>
      <SheetContent className="flex w-full flex-col gap-0 sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Fill gaps from the web</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>

        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
          <Badge variant="outline">
            {candidates.length} of {items.length} on this page can be filled
          </Badge>
          {blocked.length ? (
            <Badge
              variant="secondary"
              title="These name a category, a type or nothing at all, so there is no datasheet to find"
            >
              {blocked.length} not searchable
            </Badge>
          ) : null}
          {finished.length ? (
            <Badge variant="success">
              {filled} of {finished.length} gained something
            </Badge>
          ) : null}
          <div className="ml-auto flex items-center gap-1.5">
            {running ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  stop.current = true;
                }}
              >
                <Square />
                Stop after this one
              </Button>
            ) : (
              <Button
                size="sm"
                disabled={!candidates.length}
                onClick={() => void run()}
              >
                <Play />
                {outcomes.length ? "Run again" : `Start (${candidates.length})`}
              </Button>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {!outcomes.length ? (
            <div className="space-y-2">
              <p className="text-2xs leading-relaxed text-muted-foreground">
                {candidates.length === 0
                  ? `Nothing on this page needs filling — every ${noun} here already holds what a datasheet can answer.`
                  : `Each record is about ninety seconds — one web search and a reading-model call per page. ${candidates.length} ${
                      candidates.length === 1 ? noun : nounPlural
                    } is roughly ${Math.max(
                      1,
                      Math.round((candidates.length * 90) / 60),
                    )} minute${
                      Math.max(1, Math.round((candidates.length * 90) / 60)) === 1
                        ? ""
                        : "s"
                    }. It runs while this panel is open; stopping keeps everything already written.`}
              </p>
              {blocked.length ? (
                <p className="text-2xs leading-relaxed text-muted-foreground">
                  {blocked.length}{" "}
                  {blocked.length === 1 ? noun : nounPlural} on this page{" "}
                  {blocked.length === 1 ? "is" : "are"} skipped — there is no product
                  behind {blocked.length === 1 ? "it" : "them"} to find a datasheet
                  for.
                </p>
              ) : null}
            </div>
          ) : (
            <ul className="space-y-1">
              {outcomes.map((outcome) => (
                <li
                  key={outcome.id}
                  className="flex items-start gap-2 border-b border-border/60 py-1.5 last:border-0"
                >
                  <span className="mt-0.5">
                    {outcome.state === "running" ? (
                      <Loader2 className="size-3 animate-spin text-primary" />
                    ) : outcome.state === "failed" ? (
                      <X className="size-3 text-destructive" />
                    ) : (
                      <Check className="size-3 text-conf-verified" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs text-foreground">
                      {outcome.label}
                    </span>
                    <span className="block text-2xs text-muted-foreground">
                      {outcome.state === "running"
                        ? "reading the web…"
                        : outcome.state === "failed"
                          ? outcome.error
                          : outcome.gained.length
                            ? `gained ${outcome.gained.join(", ")} — unverified`
                            : "nothing the pages stated was new"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
