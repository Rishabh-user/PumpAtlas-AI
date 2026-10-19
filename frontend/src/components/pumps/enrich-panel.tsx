"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Sparkles } from "lucide-react";

import { ErrorState } from "@/components/data/states";
import { DiscoveryProgress } from "@/components/discovery/progress";
import { RunChanges } from "@/components/pumps/run-changes";
import { PUMP_KIND } from "@/components/discovery/kinds";
import { useRunWatcher } from "@/components/discovery/use-run-watcher";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { DiscoveryRun } from "@/types/api";

/** Pages to read. Each one is a model call, so this stays small and explicit. */
/**
 * How many pages the run reads, which is what it costs.
 *
 * Each page is one model call on top of the single web search, so "Deep" costs three
 * times "Quick". The control used to read "4 pages / 8 pages / 12 pages" — an
 * implementation detail presented as a preference, with nothing to say that the
 * right-hand option was the expensive one.
 */
const PAGE_CHOICES = [
  { pages: 4, label: "Quick" },
  { pages: 8, label: "Standard" },
  { pages: 12, label: "Deep" },
] as const;

interface StartResult {
  run_id: string;
  pump_model_id: string;
  queries: string[];
  transport: string | null;
  auto_apply: boolean;
  /** Which question was asked — a datasheet for this model, or what the vendor sells. */
  strategy: "datasheet" | "product_range";
}

/**
 * Whether this record was named by the resolver rather than read off a page.
 *
 * "Bornerman unspecified line (unspecified variant)" is a row that exists so a vendor
 * had somewhere to hang; there is no product designation in it to search for. Mirrors
 * `promotion.is_placeholder_designation`, which is what the backend decides on — this
 * only changes the wording, never the behaviour.
 */
/** What this record names, as the API classified it. */
export type ModelKind = "product" | "scope_entry" | "placeholder" | "type_code";

/**
 * Why a record cannot be filled from the web, in the words a buyer needs.
 *
 * Only a product has a datasheet. The panel used to sniff the model code for
 * "unspecified" and treat everything else as a product, so on 65 approved-suppliers
 * lines and 13 bare API type codes — 78 of 160 records — it offered to go and find a
 * datasheet for a procurement category. Each click spent a web search and a model call
 * per page to come back with nothing.
 */
const NOT_A_PRODUCT: Record<string, { title: string; body: string }> = {
  scope_entry: {
    title: "This is an approval, not a product",
    body:
      "It records that the vendor may supply this category on this project, which is " +
      "a line from an approved-suppliers list. There is no such pump and no datasheet " +
      "to find. It belongs on the vendor as an approval — migration 003 adds the table " +
      "that holds it.",
  },
  type_code: {
    title: "This is a pump type, not a model",
    body:
      "An API 610 configuration code describes an arrangement that hundreds of " +
      "manufacturers build. There is no single datasheet for it. The record needs " +
      "merging into the model it was extracted from, or removing.",
  },
};

/**
 * Ask the web for this model's datasheet.
 *
 * A model discovered from a product page is a designation and a pump type: the page
 * named the product and said what it is for, and nothing about what it costs, how long
 * it takes to deliver, what it weighs or how it performs. Across this database that
 * shows as technical specifications on 64 of 84 models and commercial specifications on
 * none — which is why a profile reads "Not recorded" against every panel while the
 * record is badged AI extracted.
 *
 * The run names this record as its target, so a datasheet that writes the designation
 * differently — "HZC-200" for the model recorded as "HZC" — fills this record rather
 * than creating a second one beside it and leaving this one as empty as before.
 */
export function PumpEnrichPanel({
  pumpModelId,
  vendorName,
  modelCode,
  kind = "product",
}: {
  pumpModelId: string;
  vendorName: string;
  modelCode: string;
  kind?: ModelKind;
}) {
  const router = useRouter();
  const placeholder = kind === "placeholder";
  const [pages, setPages] = useState<number>(8);
  const [starting, setStarting] = useState(false);
  const [started, setStarted] = useState<StartResult | null>(null);
  // Noted before the request leaves, so the "what changed" query cannot miss a value
  // written in the first moments of the run.
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);
  const { run, watch, error, setError } = useRunWatcher(PUMP_KIND.path);

  // The server page holds the specifications, so the way to show what the run wrote is
  // to re-render it — once, when the run stops. In an effect rather than in the render
  // body, where setting state re-renders immediately and loops.
  const runId = run?.id ?? null;
  const isRunning = run?.is_running ?? false;
  useEffect(() => {
    if (!runId || isRunning || finished) return;
    setFinished(true);
    router.refresh();
  }, [runId, isRunning, finished, router]);

  async function start() {
    setStartedAt(new Date(Date.now() - 5_000).toISOString());
    setStarting(true);
    setError(null);
    setFinished(false);
    try {
      const result = await clientFetch<StartResult>(
        `/pump-models/${pumpModelId}/enrich?max_results=${pages}`,
        { method: "POST" },
      );
      setStarted(result);
      watch(
        await clientFetch<DiscoveryRun>(`${PUMP_KIND.path}/${result.run_id}`),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not start reading the web",
      );
    } finally {
      setStarting(false);
    }
  }

  // No button where no datasheet exists. Saying why beats offering a search that
  // cannot succeed and charging for it.
  const blocked = NOT_A_PRODUCT[kind];
  if (blocked) {
    return (
      <div className="rounded-lg border border-border bg-card p-3">
        <p className="text-xs font-medium text-foreground">{blocked.title}</p>
        <p className="mt-0.5 max-w-3xl text-2xs leading-relaxed text-muted-foreground">
          {blocked.body}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <Sparkles className="size-3.5 text-primary" />
            {placeholder
              ? `Find out what ${vendorName} actually sells`
              : "Fill this model in from the web"}
          </p>
          {placeholder ? (
            <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
              This record has no product designation — it was created so{" "}
              {vendorName} had somewhere to hang when a page named the company
              and no product. There is no datasheet to look for, so the search
              asks which pump models {vendorName} makes for Oil &amp; Gas
              instead. What it finds becomes models of its own; this row can
              then be removed.
            </p>
          ) : (
            <p className="mt-0.5 max-w-3xl text-2xs leading-relaxed text-muted-foreground">
              {/* What it actually returns. Measured over ten runs: six gained
                * technical specifications and none gained weights, lead time or
                * price — a manufacturer publishes duty curves, not quotations. The
                * old wording promised all three and made a working feature look
                * broken. */}
              Hunts for the {vendorName} {modelCode} datasheet — duty point,
              materials, seal plan and configuration — and writes only what it can
              quote. Values land on this record, not on a new one. It will not find
              price, lead time or weights: those come from a quotation.
            </p>
          )}
        </div>
        {run?.is_running ? null : (
          <div className="flex flex-wrap items-center gap-1.5">
            <div className="flex overflow-hidden rounded border border-border">
              {PAGE_CHOICES.map((choice) => (
                <button
                  key={choice.pages}
                  type="button"
                  onClick={() => setPages(choice.pages)}
                  title={`Reads ${choice.pages} pages — ${choice.pages} model calls, plus one web search`}
                  className={cn(
                    "px-2 py-1 text-2xs transition-colors",
                    pages === choice.pages
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {choice.label}
                  <span className="ml-1 font-mono opacity-70">
                    {choice.pages}p
                  </span>
                </button>
              ))}
            </div>
            <Button size="sm" disabled={starting} onClick={() => void start()}>
              {starting ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {starting
                ? "Starting…"
                : run
                  ? "Run again"
                  : placeholder
                    ? "Find their models"
                    : "Find datasheet"}
            </Button>
          </div>
        )}
      </div>

      {error ? <ErrorState message={error} /> : null}

      {started && !run ? (
        <p className="text-2xs text-muted-foreground">
          Started ({started.transport}). Asking:{" "}
          {started.queries.slice(0, 2).join("; ")}…
        </p>
      ) : null}

      {run ? <DiscoveryProgress run={run} kind={PUMP_KIND} /> : null}

      {/* What it wrote, not just that it finished. The run used to report "4 pump
        * models found, 4 stored" and leave the page identical, because the fields it
        * wrote were not among the fifteen each panel shows. */}
      {run && !run.is_running && startedAt && !placeholder ? (
        <RunChanges pumpModelId={pumpModelId} since={startedAt} />
      ) : null}

      {run && !run.is_running ? (
        <p className="text-2xs leading-relaxed text-muted-foreground">
          {started?.strategy === "product_range" || placeholder ? (
            <>
              Run finished. Anything it found is a model of its own under{" "}
              {vendorName} — look at the vendor&rsquo;s product lines, not at
              this row. Nothing found means the pages it read named no product,
              which is the same reason this placeholder exists.
            </>
          ) : (
            <>
              Run finished — the panels above show whatever it could quote.
              Nothing new means the pages it read stated nothing this record
              does not already hold, or stated it in a form with no figure to
              quote.
            </>
          )}
        </p>
      ) : null}
    </div>
  );
}
