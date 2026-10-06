"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ExternalLink, History, Loader2, Sparkles } from "lucide-react";

import { ErrorState } from "@/components/data/states";
import { DiscoveryProgress } from "@/components/discovery/progress";
import { VENDOR_KIND } from "@/components/discovery/kinds";
import { useRunWatcher } from "@/components/discovery/use-run-watcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import { fieldLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { DiscoveryRun, VendorVersion } from "@/types/api";

/** Pages to read. Each one is a model call, so this stays small and explicit. */
const PAGE_CHOICES = [4, 8, 12] as const;

interface StartResult {
  run_id: string;
  vendor_id: string;
  queries: string[];
  transport: string | null;
  auto_apply: boolean;
}

/**
 * Ask the web again what it knows about this supplier.
 *
 * A vendor discovered while storing a pump model is a name and nothing else: the row was
 * created so the model had a manufacturer, and no page about the company itself was ever
 * read. This asks the questions a procurement file needs — company profile and
 * locations, API and ISO certifications, offshore references, annual report — reads each
 * page it finds, and applies what it can quote.
 *
 * Every value written carries a verbatim quote and the page it came from, and each run
 * that changes something records a new version of the record, so "what did we know last
 * month" stays answerable.
 */
export function EnrichPanel({
  vendorId,
  vendorName,
  versions,
}: {
  vendorId: string;
  vendorName: string;
  versions: VendorVersion[];
}) {
  const router = useRouter();
  const [pages, setPages] = useState<number>(8);
  const [starting, setStarting] = useState(false);
  const [started, setStarted] = useState<StartResult | null>(null);
  const [finished, setFinished] = useState(false);
  const { run, watch, error, setError } = useRunWatcher(VENDOR_KIND.path);

  // The server page holds the vendor's fields and its version list, so the way to show
  // what the run changed is to re-render it — once, when the run stops. In an effect
  // rather than in the render body, where setting state re-renders immediately and
  // loops.
  const runId = run?.id ?? null;
  const isRunning = run?.is_running ?? false;
  useEffect(() => {
    if (!runId || isRunning || finished) return;
    setFinished(true);
    router.refresh();
  }, [runId, isRunning, finished, router]);

  async function start() {
    setStarting(true);
    setError(null);
    setFinished(false);
    try {
      const result = await clientFetch<StartResult>(
        `/vendors/${vendorId}/enrich?max_results=${pages}`,
        { method: "POST" },
      );
      setStarted(result);
      watch(
        await clientFetch<DiscoveryRun>(`${VENDOR_KIND.path}/${result.run_id}`),
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

  const latest = versions[0];

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <Sparkles className="size-3.5 text-primary" />
            Update this record from the web
          </p>
          <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
            Reads {vendorName}&rsquo;s own pages for the things a procurement
            file needs — legal entity, headquarters, certifications, offshore
            references, financials — and writes only what it can quote. A run
            that changes something records a new version.
          </p>
        </div>
        {run?.is_running ? null : (
          <div className="flex flex-wrap items-center gap-1.5">
            <div className="flex overflow-hidden rounded border border-border">
              {PAGE_CHOICES.map((choice) => (
                <button
                  key={choice}
                  type="button"
                  onClick={() => setPages(choice)}
                  className={cn(
                    "px-2 py-1 font-mono text-2xs transition-colors",
                    pages === choice
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {choice} pages
                </button>
              ))}
            </div>
            <Button size="sm" disabled={starting} onClick={() => void start()}>
              {starting ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {starting ? "Starting…" : run ? "Run again" : "Run AI search"}
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

      {run ? <DiscoveryProgress run={run} kind={VENDOR_KIND} /> : null}

      {run && !run.is_running ? (
        <p className="text-2xs leading-relaxed text-muted-foreground">
          {latest && isRecent(latest.created_at) ? (
            <>
              <span className="text-conf-verified">
                Version {latest.version} recorded
              </span>{" "}
              — {latest.change_count} field
              {latest.change_count === 1 ? "" : "s"} changed. The panels above
              now show them.
            </>
          ) : (
            "Nothing new to record: the pages it read confirmed what is already held, or stated nothing it could quote."
          )}
        </p>
      ) : null}

      {versions.length ? (
        <details className="border-t border-border pt-2">
          <summary className="flex cursor-pointer items-center gap-1.5 text-2xs text-primary">
            <History className="size-3" />
            {versions.length} version{versions.length === 1 ? "" : "s"}
          </summary>
          <ol className="mt-1.5 space-y-1.5">
            {versions.map((version) => (
              <li key={version.version} className="text-2xs">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline">v{version.version}</Badge>
                  <span className="text-muted-foreground">
                    {new Date(version.created_at).toLocaleString("en-GB")}
                  </span>
                  <span className="figure text-muted-foreground">
                    {version.change_count} change
                    {version.change_count === 1 ? "" : "s"}
                  </span>
                </div>
                {version.changes.length ? (
                  <dl className="mt-0.5 space-y-0.5 pl-2">
                    {version.changes.slice(0, 8).map((change) => (
                      <div key={change.field} className="flex gap-1.5">
                        <dt className="text-muted-foreground">
                          {fieldLabel(change.field)}
                        </dt>
                        <dd className="min-w-0 flex-1 truncate text-foreground/85">
                          {render(change.to)}
                          {change.from === null || change.from === undefined ? (
                            <span className="ml-1 text-muted-foreground/70">
                              (was empty)
                            </span>
                          ) : null}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

function render(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Within the last two minutes, so a run's own version is distinguishable from history. */
function isRecent(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() < 2 * 60 * 1000;
}
