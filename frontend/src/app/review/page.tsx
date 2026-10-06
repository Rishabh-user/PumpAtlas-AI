import { redirect } from "next/navigation";

import { ReviewQueue } from "@/components/review-queue";
import {
  ReviewFilters,
  reviewHref,
  type ReviewFilterState,
} from "@/components/review/review-filters";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Pager } from "@/components/data/pager";
import { ErrorState } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { hrefToString } from "@/lib/href";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { loadShellContext } from "@/lib/session";
import type {
  Page,
  ReviewQueueFacets,
  ReviewQueueItem,
  VendorMatch,
} from "@/types/api";

export const metadata = { title: "AI review" };

const PAGE_SIZE = 25;
const VENDOR_STATES: VendorMatch[] = ["matched", "new", "missing"];
const DECISIONS = ["pending", "accepted", "rejected", "escalated", "all"];

/** A repeatable search param arrives as a string, an array, or not at all. */
function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{
    vendor_match?: string | string[];
    fields?: string;
    entity_type?: string | string[];
    decision?: string;
    page?: string;
  }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  const params = await searchParams;
  // Unrecognised values are dropped rather than passed on: a hand-edited URL should
  // narrow nothing instead of returning a 422 the reviewer cannot act on.
  const state: ReviewFilterState = {
    vendorMatch: asList(params.vendor_match).filter(
      (value): value is VendorMatch =>
        VENDOR_STATES.includes(value as VendorMatch),
    ),
    fields:
      params.fields === "with" || params.fields === "without"
        ? params.fields
        : null,
    // Left open: the entity types come from the extraction contract, so the server is
    // the authority on which exist. An unknown one simply matches nothing.
    entityType: asList(params.entity_type).filter(Boolean),
    decision: DECISIONS.includes(params.decision ?? "")
      ? (params.decision as string)
      : "pending",
  };

  const currentPage = Math.max(1, Number(params.page ?? "1") || 1);
  const offset = (currentPage - 1) * PAGE_SIZE;

  let queue: Page<ReviewQueueItem> | null = null;
  let facets: ReviewQueueFacets | null = null;
  let error: string | null = null;
  try {
    // Together, not one after the other: each is a round trip to a hosted database, and
    // the facet counts are decoration — they should not add to how long the page takes.
    const [queueResult, facetResult] = await Promise.all([
      apiFetch<Page<ReviewQueueItem>>("/ai/review-queue", {
        query: {
          limit: PAGE_SIZE,
          offset,
          decision: state.decision,
          ...(state.vendorMatch.length && state.vendorMatch.length < 3
            ? { vendor_match: state.vendorMatch }
            : {}),
          ...(state.fields
            ? { has_fields: state.fields === "with" ? "true" : "false" }
            : {}),
          ...(state.entityType.length ? { entity_type: state.entityType } : {}),
        },
        revalidate: false,
      }),
      apiFetch<ReviewQueueFacets>("/ai/review-queue/facets", {
        query: { decision: state.decision },
        revalidate: false,
      }).catch(() => null),
    ]);
    queue = queueResult;
    facets = facetResult;
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  const shown = queue ? queue.offset + queue.items.length : 0;
  const filtered =
    state.vendorMatch.length > 0 ||
    state.fields !== null ||
    state.entityType.length > 0 ||
    state.decision !== "pending";

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="AI review"
        lede="Candidate records extracted by Gemma, each with the verbatim quote that supports every field. Nothing reaches the system of record until it is accepted here."
        meta={
          queue ? (
            <Badge variant={queue.total > 0 ? "warning" : "success"}>
              {queue.total.toLocaleString("en-GB")}
              {filtered ? " match the filter" : " awaiting a decision"}
            </Badge>
          ) : null
        }
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        <ReviewFilters state={state} facets={facets} />

        {/* The queue renders its own empty state: it holds the decision confirmation
            in local state, so it must not unmount when the last card is decided. */}
        <ReviewQueue
          key={`${state.decision}|${state.vendorMatch.join(",")}|${state.entityType.join(",")}|${state.fields}|${currentPage}`}
          initial={queue}
          filtered={filtered}
        />

        {queue ? (
          <Pager
            total={queue.total}
            offset={queue.offset}
            limit={PAGE_SIZE}
            prevHref={
              currentPage > 1
                ? hrefToString(reviewHref(state, { page: currentPage - 1 }))
                : null
            }
            nextHref={
              shown < queue.total
                ? hrefToString(reviewHref(state, { page: currentPage + 1 }))
                : null
            }
            noun="candidates"
          />
        ) : null}
      </div>
    </AppShell>
  );
}
