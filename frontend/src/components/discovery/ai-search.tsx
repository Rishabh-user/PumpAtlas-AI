"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Database, Globe2, Loader2, Save, Square, X } from "lucide-react";

import { ErrorState, SuccessNote } from "@/components/data/states";
import { CandidateList } from "@/components/discovery/candidate-list";
import { CandidateModal } from "@/components/discovery/candidate-modal";
import {
  composeQuery,
  EMPTY_QUERY,
  QueryComposer,
  type ComposedQuery,
} from "@/components/discovery/query-composer";
import {
  discoveryKind,
  type DiscoveryKindSlug,
} from "@/components/discovery/kinds";
import { DiscoveryProgress } from "@/components/discovery/progress";
import { useRunWatcher } from "@/components/discovery/use-run-watcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { clientFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  DiscoveryCandidate,
  DiscoveryRun,
  DiscoveryScopes,
  DiscoverySelectResponse,
} from "@/types/api";

/**
 * Mirrors `DiscoveryStartRequest.max_results` in the backend schema.
 *
 * The cap is a cost and time guard, not an arbitrary limit: every page is one Gemma
 * call, observed between 5 and 94 seconds, so 25 pages is already a ten-to-twenty
 * minute run. Broader coverage comes from several searches with different terms, which
 * also gives Parallel AI a better objective each time.
 */
const MIN_PAGES = 1;
const MAX_PAGES = 25;

/**
 * Mirrors `MAX_SWEEP_PAGES` in `api/v1/discovery_routes.py`.
 *
 * A sweep runs one search per segment - 23 pump types, or 60 supply countries - so the
 * page count multiplies. The backend trims the per-segment count to keep the total under
 * this; the projection below shows the person what they are about to start.
 */
const MAX_SWEEP_PAGES = 150;

/**
 * The AI discovery panel, for vendors or for pump models.
 *
 * Both kinds expose the same API contract under a different prefix, so this component
 * is configured rather than duplicated — which is also what stops the two flows from
 * drifting apart as either one changes.
 */
export function AiSearch({ kind: slug }: { kind: DiscoveryKindSlug }) {
  // Resolved here, not passed in: the config carries a Lucide icon, and a React
  // component cannot cross a server-to-client boundary.
  const kind = discoveryKind(slug);
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [composed, setComposed] = useState<ComposedQuery>(EMPTY_QUERY);
  const [maxResults, setMaxResults] = useState("8");

  const [sweep, setSweep] = useState(false);
  // Which axis a sweep runs along. Vendors default to country, because sweeping pump
  // types returns the same global OEMs from every angle; the suppliers missing from the
  // record are regional.
  const [scope, setScope] = useState<"country" | "pump_type" | null>(null);
  const [reviewing, setReviewing] = useState<DiscoveryCandidate | null>(null);
  // Off by default: writing straight into the record without anyone looking is a
  // deliberate choice, not the default one.
  const [autoStore, setAutoStore] = useState(false);
  const [scopes, setScopes] = useState<DiscoveryScopes | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [storing, setStoring] = useState(false);
  const [result, setResult] = useState<DiscoverySelectResponse | null>(null);

  const { run, watch, poll, error, setError } = useRunWatcher(kind.path);

  // What this kind can sweep, and how many searches each axis means. Served by the API
  // rather than counted here, so adding a pump type or a supply country cannot leave the
  // projection lying about an hours-long run.
  useEffect(() => {
    if (!open || scopes !== null) return;
    clientFetch<DiscoveryScopes>(`${kind.path}/scopes`)
      .then((data) => {
        setScopes(data);
        setScope(
          (data.scopes.find((option) => option.is_default)?.scope ??
            data.scopes[0]?.scope ??
            null) as "country" | "pump_type" | null,
        );
      })
      .catch(() => setScopes(null));
  }, [open, scopes, kind.path]);

  const pages = Number(maxResults);
  const pagesInvalid =
    maxResults.trim() === "" ||
    !Number.isFinite(pages) ||
    !Number.isInteger(pages) ||
    pages < MIN_PAGES ||
    pages > MAX_PAGES;
  const query = composeQuery(composed, scopes, kind.noun);
  const countries = composed.countries;
  // Composed from vocabularies, so it is only invalid before the vocabularies load.
  const queryInvalid = !sweep && query.trim().length < 2;
  const activeScope = scopes?.scopes.find((option) => option.scope === scope);
  const sweepingCountries = scope === "country";
  // A country sweep can be narrowed to a chosen set; otherwise it is the whole axis.
  const segments = sweepingCountries && countries.length
    ? countries.length
    : (activeScope?.segment_count ?? 0);
  // What one segment is, in the user's words rather than the code's.
  const sweepWord = sweepingCountries ? "country" : "pump type";
  const maxSweepPages = scopes?.max_sweep_pages ?? MAX_SWEEP_PAGES;
  const projectedPages = segments
    ? Math.min(maxSweepPages, segments * Math.max(MIN_PAGES, pages || 0))
    : 0;
  const projectedMinutes = Math.round((projectedPages * 30) / 60);

  async function start() {
    setStarting(true);
    setError(null);
    setResult(null);
    setSelected([]);
    try {
      const started = await clientFetch<DiscoveryRun>(kind.path, {
        method: "POST",
        body: {
          sweep,
          sweep_scope: sweep ? scope : null,
          // Only meaningful for a country sweep; the API refuses them otherwise.
          countries: sweep && sweepingCountries ? countries : [],
          auto_store: autoStore,
          query: sweep ? null : query.trim(),
          // One country biases a single search. For a sweep the list above is the axis.
          country: sweep ? null : (countries[0] ?? null),
          // Clamped rather than defaulted: silently sending 8 when the box says 100
          // would be a different search than the one the person asked for.
          max_results: Math.min(
            MAX_PAGES,
            Math.max(MIN_PAGES, Math.round(pages)),
          ),
        },
      });
      watch(started);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not start the search",
      );
    } finally {
      setStarting(false);
    }
  }

  /** Approve or discard a single candidate from the modal. */
  async function decide(candidate: DiscoveryCandidate, approve: boolean) {
    if (!run) return;
    setStoring(true);
    setError(null);
    try {
      const response = await clientFetch<DiscoverySelectResponse>(
        `${kind.path}/${run.id}/select`,
        {
          method: "POST",
          body: approve
            ? { store: [{ candidate_id: candidate.id }] }
            : { reject: [candidate.id] },
        },
      );
      if (approve) setResult(response);
      setSelected((current) => current.filter((id) => id !== candidate.id));
      setReviewing(null);
      await poll(run.id);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not record that decision",
      );
    } finally {
      setStoring(false);
    }
  }

  async function store() {
    if (!run || !selected.length) return;
    setStoring(true);
    setError(null);
    try {
      const response = await clientFetch<DiscoverySelectResponse>(
        `${kind.path}/${run.id}/select`,
        {
          method: "POST",
          body: { store: selected.map((id) => ({ candidate_id: id })) },
        },
      );
      setResult(response);
      setSelected([]);
      await poll(run.id);
      // The table behind this sheet is a server component.
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not store the records",
      );
    } finally {
      setStoring(false);
    }
  }

  async function stop() {
    if (!run) return;
    try {
      // Cooperative: the runner notices between segments and between pages, so the
      // candidates it already found stay reviewable.
      watch(
        await clientFetch<DiscoveryRun>(`${kind.path}/${run.id}/cancel`, {
          method: "POST",
        }),
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not stop the run",
      );
    }
  }

  async function discard() {
    if (!run || !selected.length) return;
    setStoring(true);
    try {
      await clientFetch<DiscoverySelectResponse>(
        `${kind.path}/${run.id}/select`,
        {
          method: "POST",
          body: { reject: selected },
        },
      );
      setSelected([]);
      await poll(run.id);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not discard the candidates",
      );
    } finally {
      setStoring(false);
    }
  }

  const selectable = (run?.candidates ?? []).filter(
    (candidate) =>
      candidate.decision === "pending" &&
      !candidate.stored_id &&
      candidate.blocked_reason === null,
  );
  const allSelected =
    selectable.length > 0 && selected.length === selectable.length;
  const blockedCount = (run?.candidates ?? []).filter(
    (candidate) => !candidate.stored_id && candidate.blocked_reason !== null,
  ).length;

  const TriggerIcon = kind.icon;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button>
          <TriggerIcon />
          {kind.triggerLabel}
        </Button>
      </SheetTrigger>

      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{kind.title}</SheetTitle>
          <p className="mt-0.5 text-xs text-muted-foreground">{kind.blurb}</p>
        </SheetHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          {/* ---- the query ---- */}
          <div className="space-y-2.5 rounded-lg border border-border bg-card p-3">
            <QueryComposer
              value={composed}
              onChange={setComposed}
              scopes={scopes}
              noun={kind.noun}
              sweeping={sweep}
              sweepingCountries={sweepingCountries}
              maxCountries={scopes?.max_countries}
            />

            <div className="flex flex-wrap items-end gap-3">
              <div className="w-28 space-y-1.5">
                <Label htmlFor="discovery-pages">
                  Pages per search
                </Label>
                <Input
                  id="discovery-pages"
                  type="number"
                  min={MIN_PAGES}
                  max={MAX_PAGES}
                  step={1}
                  value={maxResults}
                  onChange={(event) => setMaxResults(event.target.value)}
                  // `max` on a number input only binds the spinner; a typed 100 still
                  // needs clamping before it can reach the API.
                  onBlur={() =>
                    setMaxResults((current) => {
                      const parsed = Math.round(Number(current));
                      if (!Number.isFinite(parsed)) return String(MIN_PAGES);
                      return String(
                        Math.min(MAX_PAGES, Math.max(MIN_PAGES, parsed)),
                      );
                    })
                  }
                  aria-invalid={pagesInvalid}
                  className={cn(
                    "font-mono",
                    pagesInvalid
                      ? "border-destructive focus-visible:border-destructive"
                      : null,
                  )}
                />
              </div>
              <p className="flex-1 text-2xs leading-relaxed text-muted-foreground">
                {MIN_PAGES}&ndash;{MAX_PAGES}. Each page is one reading-model
                call, so this is the cost dial; breadth comes from sweeping.
              </p>
            </div>

            <div className="space-y-1.5 rounded-md border border-border bg-background/50 p-2.5">
              <label
                htmlFor="discovery-sweep"
                className="flex cursor-pointer items-start gap-2"
              >
                <Checkbox
                  id="discovery-sweep"
                  className="mt-0.5"
                  checked={sweep}
                  onCheckedChange={(checked) => setSweep(checked === true)}
                />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                    <Globe2 className="size-3.5 text-primary" />
                    {/* Says what it will do, with the count. It used to read "Search a
                        whole axis, not one query" — "axis" is this codebase's word for
                        it, not anyone else's. */}
                    Search every {sweepWord}
                    {segments ? ` (${segments})` : ""}
                  </span>
                  <span className="mt-0.5 block text-2xs leading-relaxed text-muted-foreground">
                    One search per {sweepWord} instead of one for your query.
                    Broad, and slow.
                  </span>
                </span>
              </label>

              {/* Which axis. Only shown when the kind has more than one: a pump model is
                  identified by its duty, not its postcode, so pumps sweep types only. */}
              {sweep && (scopes?.scopes.length ?? 0) > 1 ? (
                <div className="flex flex-wrap items-center gap-1.5 pl-6">
                  {scopes?.scopes.map((option) => (
                    <button
                      key={option.scope}
                      type="button"
                      onClick={() => setScope(option.scope)}
                      className={cn(
                        "rounded border px-1.5 py-px text-2xs transition-colors",
                        scope === option.scope
                          ? "border-primary/60 bg-primary/10 text-primary"
                          : "border-border text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {option.scope === "country"
                        ? `Every country (${option.segment_count})`
                        : `Every pump type (${option.segment_count})`}
                    </button>
                  ))}
                </div>
              ) : null}

              {sweep && sweepingCountries ? (
                <p className="pl-6 text-2xs leading-relaxed text-muted-foreground">
                  {countries.length
                    ? `Limited to the ${countries.length} countries you chose.`
                    : `The ${activeScope?.segment_count ?? 0} countries that supply Oil & Gas pumps, biggest markets first — so stopping early still covers what matters.`}
                </p>
              ) : null}

              {sweep && segments ? (
                <p className="pl-6 text-2xs leading-relaxed text-sev-medium">
                  {segments} searches, up to{" "}
                  <span className="font-mono">{projectedPages}</span> pages,
                  roughly <span className="font-mono">{projectedMinutes}</span>{" "}
                  minutes. Stop it any time and keep what it found — but a
                  restart of the API ends it, unless a worker is running.
                </p>
              ) : null}
            </div>

            {pagesInvalid ? (
              <p role="alert" className="text-2xs text-destructive">
                Pages must be a whole number between {MIN_PAGES} and {MAX_PAGES}
                . Each page is one model call, so a bigger run mostly means a
                longer wait — run several searches with different terms instead.
              </p>
            ) : null}

            <label
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-md border p-2.5 transition-colors",
                autoStore
                  ? "border-destructive/40 bg-destructive/[0.06]"
                  : "border-border bg-background/50 hover:bg-accent/40",
              )}
            >
              <Checkbox
                checked={autoStore}
                onCheckedChange={(value) => setAutoStore(value === true)}
                className="mt-0.5"
              />
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                  <Database className="size-3.5 text-destructive" />
                  Store everything it finds, without asking
                </span>
                <span className="mt-0.5 block text-2xs leading-relaxed text-muted-foreground">
                  Each confident candidate is written as it is read, instead of
                  waiting for you to approve it.
                </span>
                <span className="mt-0.5 block text-2xs leading-relaxed text-destructive">
                  Fields still need a quote from their page — but nobody reviews
                  these before they land.
                </span>
              </span>
            </label>

            <div className="flex items-center gap-2">
              <Button
                onClick={() => void start()}
                disabled={
                  starting ||
                  run?.is_running === true ||
                  queryInvalid ||
                  pagesInvalid
                }
              >
                {starting || run?.is_running ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <TriggerIcon />
                )}
                {/* `starting` has to change the words, not just the icon. Creating the
                    run is a real request against a hosted database and takes about five
                    seconds; while it was in flight only a 14px glyph swapped and the
                    label still read "Run AI search", so the button looked dead and the
                    obvious response was to click it again. */}
                {starting
                  ? "Starting…"
                  : run?.is_running
                    ? "Searching…"
                    : run
                      ? "Search again"
                      : "Run AI search"}
              </Button>
              {run?.is_running ? (
                <Button
                  variant="outline"
                  onClick={() => void stop()}
                  disabled={run.cancel_requested}
                >
                  <Square />
                  {run.cancel_requested ? "Stopping…" : "Stop"}
                </Button>
              ) : null}
              <p className="text-2xs text-muted-foreground">
                {/* Says what is happening during the several seconds it takes to create
                    the run, rather than continuing to describe what a click would do. */}
                {starting
                  ? sweep
                    ? `Setting up ${segments || ""} searches…`
                    : "Setting up the search…"
                  : pagesInvalid
                    ? "Fix the page count to start."
                    : sweep
                      ? `${pages} page${pages === 1 ? "" : "s"} per ${sweepWord}.`
                      : `Roughly ${pages} page${pages === 1 ? "" : "s"}; a page can take a minute to read.`}
              </p>
            </div>
          </div>

          {error ? <ErrorState message={error} /> : null}

          {run ? <DiscoveryProgress run={run} kind={kind} /> : null}

          {/* ---- what was found ---- */}
          {run && run.candidates.length ? (
            <div className="overflow-hidden rounded-lg border border-border bg-card">
              <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
                <span className="label-xs text-foreground">
                  {kind.nounPlural} found ({run.candidates.length})
                </span>
                {run.stored_count ? (
                  <Badge variant="success">{run.stored_count} stored</Badge>
                ) : null}
                {blockedCount ? (
                  <Badge
                    variant="warning"
                    title="These pages named a category or no manufacturer, so there is nothing to store"
                  >
                    {blockedCount} not storable
                  </Badge>
                ) : null}
                {selectable.length ? (
                  <button
                    type="button"
                    onClick={() =>
                      setSelected(
                        allSelected
                          ? []
                          : selectable.map((candidate) => candidate.id),
                      )
                    }
                    className="ml-auto text-2xs text-primary hover:underline"
                  >
                    {allSelected
                      ? "Clear selection"
                      : `Select all ${selectable.length}`}
                  </button>
                ) : null}
              </div>

              <CandidateList
                candidates={run.candidates}
                kind={kind}
                onReview={setReviewing}
                selected={selected}
                onToggle={(id) =>
                  setSelected((current) =>
                    current.includes(id)
                      ? current.filter((value) => value !== id)
                      : [...current, id],
                  )
                }
              />
            </div>
          ) : null}

          {result ? (
            <div className="space-y-1.5 rounded-lg border border-border bg-card p-3">
              {result.stored.length ? (
                <SuccessNote>
                  Stored {result.stored.length}{" "}
                  {result.stored.length === 1 ? kind.noun : kind.nounPlural}{" "}
                  with full provenance.
                </SuccessNote>
              ) : null}
              {result.stored.map((stored) => (
                <div key={stored.candidate_id}>
                  <p className="text-2xs text-muted-foreground">
                    <span className="text-foreground">{stored.label}</span> —{" "}
                    {stored.fields_applied.length} field
                    {stored.fields_applied.length === 1 ? "" : "s"} written
                    {Object.keys(stored.fields_refused).length
                      ? `, ${Object.keys(stored.fields_refused).length} refused`
                      : ""}
                  </p>
                  {Object.entries(stored.fields_refused).map(([field, why]) => (
                    <p key={field} className="text-[0.625rem] text-sev-medium">
                      {field}: {why}
                    </p>
                  ))}
                </div>
              ))}
              {Object.entries(result.failed).map(([id, why]) => (
                <p key={id} className="text-2xs text-destructive">
                  {why}
                </p>
              ))}
            </div>
          ) : null}
        </div>

        {/* ---- the decision bar ---- */}
        {selected.length ? (
          <div className="flex items-center justify-between gap-3 border-t border-border bg-card px-4 py-2.5">
            <span className="text-xs font-medium text-primary">
              <span className="font-mono">{selected.length}</span> selected
            </span>
            <div className="flex items-center gap-1.5">
              <Button
                variant="ghost"
                onClick={() => void discard()}
                disabled={storing}
              >
                <X />
                Discard
              </Button>
              <Button onClick={() => void store()} disabled={storing}>
                {storing ? <Loader2 className="animate-spin" /> : <Save />}
                Store {selected.length}{" "}
                {selected.length === 1 ? kind.noun : kind.nounPlural}
              </Button>
            </div>
          </div>
        ) : null}
      </SheetContent>

      <CandidateModal
        candidate={reviewing}
        kind={kind}
        open={reviewing !== null}
        onOpenChange={(next) => {
          if (!next) setReviewing(null);
        }}
        onApprove={() => reviewing && void decide(reviewing, true)}
        onReject={() => reviewing && void decide(reviewing, false)}
        busy={storing}
      />
    </Sheet>
  );
}
