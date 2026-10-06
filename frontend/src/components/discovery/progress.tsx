"use client";

import { useEffect, useState } from "react";
import {
  Check,
  CircleDashed,
  Loader2,
  MinusCircle,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { DiscoveryKindConfig } from "@/components/discovery/kinds";
import type { DiscoveryJob, DiscoveryRun, DiscoveryStage } from "@/types/api";

/**
 * Which AI is working, right now.
 *
 * The two providers do different jobs and fail for different reasons — Parallel AI can
 * be rate-limited, Gemma can time out on a long page — so the progress is per stage and
 * per provider rather than one indeterminate spinner. A stage that ruled pages out says
 * so, because "4 pages found, 1 supplier" is a result, not a malfunction.
 */

/**
 * Provider names as the API reports them, in the words a person recognises.
 *
 * Searching can be done by Parallel AI, OpenAI or Claude, and reading a page by Gemma,
 * OpenAI or Claude — the stage carries whichever is configured, so every one needs a
 * label here. An unmapped name falls through to the raw value rather than being hidden,
 * because a badge that silently disappears is harder to notice than an ugly one.
 */
const PROVIDER_LABEL: Record<string, string> = {
  parallel: "Parallel AI",
  gemma: "Gemma",
  openrouter: "Gemma",
  openai: "OpenAI",
  anthropic: "Claude",
};

/**
 * How long the run has been going, ticking once a second.
 *
 * Worth its own timer rather than deriving it from the poll: the poll backs off to
 * fifteen seconds on a long run, and a clock that jumps in fifteen-second steps reads
 * as a stall on something that takes over an hour.
 */
function useElapsed(startedAt: string | null, running: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);

  if (!startedAt) return null;
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.round((now - started) / 1000));
}

function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/**
 * Overall progress, and only where the denominator is honest.
 *
 * A single search knows how many pages it found, so pages-read over pages-found is a
 * real fraction. A sweep does not: it discovers pages as it goes, so that ratio would
 * sit near 100% all run and lurch backwards each time a new search returned. For a
 * sweep the bounded thing is the searches themselves, so that is what the bar tracks
 * and the page count is shown as a plain total beside it.
 */
function RunSummary({
  run,
  kind,
}: {
  run: DiscoveryRun;
  kind: { noun: string; nounPlural: string };
}) {
  const elapsed = useElapsed(run.started_at, run.is_running);
  const search = run.stages.find((stage) => stage.key === "search");

  const tracking = run.sweep
    ? {
        done: search?.done ?? 0,
        total: search?.total ?? run.segment_count,
        unit: "searches",
      }
    : { done: run.pages_screened, total: run.pages_found, unit: "pages read" };
  const pct =
    tracking.total > 0
      ? Math.min(100, Math.round((tracking.done / tracking.total) * 100))
      : run.is_running
        ? 0
        : 100;

  return (
    <div className="space-y-1.5 border-b border-border px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="figure text-foreground">
          {tracking.done}/{tracking.total || "?"}
        </span>
        <span className="text-2xs text-muted-foreground">{tracking.unit}</span>
        <span className="figure text-muted-foreground">{pct}%</span>
        {elapsed !== null ? (
          <span className="text-2xs text-muted-foreground/70">
            {duration(elapsed)} elapsed
          </span>
        ) : null}
      </div>

      <Progress
        value={pct}
        className="h-1"
        aria-label={`${tracking.unit} complete`}
        indicatorClassName={run.is_running ? "bg-primary" : "bg-conf-verified"}
      />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs text-muted-foreground">
        {run.sweep ? (
          <span>
            <span className="figure text-foreground">{run.pages_found}</span>{" "}
            pages found
            {run.pages_screened !== run.pages_found ? (
              <>
                ,{" "}
                <span className="figure text-foreground">
                  {run.pages_screened}
                </span>{" "}
                read
              </>
            ) : null}
          </span>
        ) : null}
        <span>
          <span className="figure text-foreground">{run.candidate_count}</span>{" "}
          {run.candidate_count === 1 ? kind.noun : kind.nounPlural} found
        </span>
        {/* Only meaningful when the run is writing as it goes; otherwise "0 stored"
            looks like a failure rather than a run that is waiting to be picked from. */}
        {run.auto_store ? (
          <span className={run.stored_count ? "text-conf-verified" : undefined}>
            <span className="figure">{run.stored_count}</span> stored
          </span>
        ) : null}
        {run.pages_failed ? (
          <span className="text-destructive">
            <span className="figure">{run.pages_failed}</span> failed
          </span>
        ) : null}
      </div>
    </div>
  );
}

function StageIcon({ status }: { status: DiscoveryStage["status"] }) {
  if (status === "running") {
    return <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />;
  }
  if (status === "done") {
    return (
      <Check className="size-3.5 shrink-0 text-conf-verified" strokeWidth={3} />
    );
  }
  if (status === "failed") {
    return <TriangleAlert className="size-3.5 shrink-0 text-destructive" />;
  }
  if (status === "skipped") {
    return (
      <MinusCircle className="size-3.5 shrink-0 text-muted-foreground/60" />
    );
  }
  return (
    <CircleDashed className="size-3.5 shrink-0 text-muted-foreground/50" />
  );
}

function StageRow({ stage }: { stage: DiscoveryStage }) {
  const pct =
    stage.total && stage.total > 0
      ? Math.min(100, Math.round((stage.done / stage.total) * 100))
      : stage.status === "done"
        ? 100
        : 0;

  return (
    <li className="flex items-start gap-2.5 px-3 py-2">
      <span className="mt-0.5">
        <StageIcon status={stage.status} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={cn(
              "text-xs font-medium",
              stage.status === "pending"
                ? "text-muted-foreground"
                : "text-foreground",
            )}
          >
            {stage.label}
          </span>
          {stage.provider ? (
            <Badge variant={stage.status === "running" ? "default" : "outline"}>
              {PROVIDER_LABEL[stage.provider] ?? stage.provider}
            </Badge>
          ) : null}
          {stage.total && stage.total > 0 ? (
            <span className="figure text-muted-foreground">
              {stage.done}/{stage.total}
            </span>
          ) : null}
        </div>
        {stage.detail ? (
          <p
            className={cn(
              "mt-0.5 text-2xs leading-snug",
              stage.status === "failed"
                ? "text-destructive"
                : "text-muted-foreground",
            )}
          >
            {stage.detail}
          </p>
        ) : null}
        {stage.status === "running" || stage.status === "done" ? (
          <Progress
            value={pct}
            className="mt-1.5 h-0.5"
            indicatorClassName={
              stage.status === "done" ? "bg-conf-verified" : "bg-primary"
            }
          />
        ) : null}
      </div>
    </li>
  );
}

function JobLine({ job }: { job: DiscoveryJob }) {
  return (
    <li className="flex items-center gap-2 text-[0.625rem] text-muted-foreground">
      <span
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          job.status === "succeeded"
            ? "bg-conf-verified"
            : job.status === "failed"
              ? "bg-destructive"
              : "bg-sev-medium",
        )}
      />
      <span className="w-20 shrink-0 truncate">
        {PROVIDER_LABEL[job.provider ?? ""] ?? job.provider ?? "—"}
      </span>
      <span className="min-w-0 flex-1 truncate font-mono">
        {job.model ?? job.prompt_name}
      </span>
      {job.latency_ms !== null ? (
        <span className="figure shrink-0">
          {(job.latency_ms / 1000).toFixed(1)}s
        </span>
      ) : null}
      {job.error ? (
        <span className="min-w-0 flex-1 truncate text-destructive">
          {job.error}
        </span>
      ) : null}
    </li>
  );
}

export function DiscoveryProgress({
  run,
  kind,
}: {
  run: DiscoveryRun;
  kind: DiscoveryKindConfig;
}) {
  const stopped = run.cancel_requested && !run.is_running;

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <span className="label-xs text-foreground">
          {run.is_running
            ? "AI search in progress"
            : stopped
              ? "AI search stopped"
              : "AI search complete"}
        </span>
        {run.is_running ? (
          <Loader2 className="size-3 animate-spin text-primary" />
        ) : stopped ? (
          // A run somebody stopped on purpose is not a failure, and badging it as one
          // makes a deliberate action look like a malfunction.
          <Badge variant="warning">Stopped</Badge>
        ) : run.error_summary ? (
          <Badge variant="destructive">Failed</Badge>
        ) : (
          <Badge variant="success">
            {`${run.candidate_count} ${run.candidate_count === 1 ? kind.noun : kind.nounPlural}`}
          </Badge>
        )}
        {run.sweep ? (
          <Badge variant="outline" title={`${run.segment_count} web searches`}>
            sweep · {run.segment_count} searches
          </Badge>
        ) : null}
        {run.cancel_requested && run.is_running ? (
          <Badge variant="warning">stopping</Badge>
        ) : null}
        {run.transport === "in_process" ? (
          <Badge
            variant="outline"
            className="ml-auto"
            title="No Celery worker is running, so this run is executing inside the API process. It will not survive a restart."
          >
            in-process
          </Badge>
        ) : null}
      </div>

      <RunSummary run={run} kind={kind} />

      <ul className="divide-y divide-border">
        {run.stages.map((stage) => (
          <StageRow key={stage.key} stage={stage} />
        ))}
      </ul>

      {run.error_summary ? (
        <p
          className={cn(
            "border-t border-border px-3 py-2 text-2xs",
            stopped ? "text-muted-foreground" : "text-destructive",
          )}
        >
          {run.error_summary}
        </p>
      ) : null}

      {run.jobs.length ? (
        <details className="border-t border-border">
          <summary className="cursor-pointer px-3 py-2 text-2xs text-primary">
            {run.job_count ?? run.jobs.length} provider call
            {(run.job_count ?? run.jobs.length) === 1 ? "" : "s"}
            {/* A sweep makes hundreds; the API sends the recent ones plus every
                failure, so the count and the list legitimately disagree. */}
            {run.job_count > run.jobs.length
              ? ` · showing ${run.jobs.length}`
              : ""}
          </summary>
          <ul className="space-y-1 px-3 pb-2.5">
            {run.jobs.map((job, index) => (
              <JobLine key={`${job.provider}-${index}`} job={job} />
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
