import Link from "next/link";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ReviewQueueFacets, VendorMatch } from "@/types/api";

/**
 * The review queue's filters.
 *
 * Plain links rather than a client-side control: the state lives in the URL, so a
 * filtered queue can be bookmarked and handed to a colleague ("the 29 that would create
 * a new vendor"), the back button behaves, and the server does the filtering — which it
 * must, because filtering only the fetched page would silently disagree with both the
 * pagination and the totals.
 */

/** No filters at all — what "Clear filters" goes back to. */
export const CLEARED: ReviewFilterState = {
  vendorMatch: [],
  fields: null,
  entityType: [],
  decision: "pending",
};

export interface ReviewFilterState {
  vendorMatch: VendorMatch[];
  fields: "with" | "without" | null;
  entityType: string[];
  decision: string;
}

const VENDOR_LABELS: Record<VendorMatch, string> = {
  matched: "Matches an existing vendor",
  new: "Will create a new vendor",
  missing: "Needs a vendor first",
};

const DECISIONS = [
  { value: "pending", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "escalated", label: "Escalated" },
  { value: "all", label: "All" },
] as const;

/** What the extraction contract calls a type, in the words the screen uses. */
const ENTITY_LABELS: Record<string, string> = {
  pump_model: "Pump models",
  vendors: "Vendors",
};

function entityLabel(value: string) {
  return (
    ENTITY_LABELS[value] ??
    value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

/** Build a `/review` href for a filter state, dropping defaults and the page number. */
export function reviewHref(
  state: ReviewFilterState,
  overrides: Partial<ReviewFilterState> & { page?: number } = {},
) {
  const next = { ...state, ...overrides };
  return {
    pathname: "/review",
    query: {
      ...(next.vendorMatch.length && next.vendorMatch.length < 3
        ? { vendor_match: next.vendorMatch }
        : {}),
      ...(next.fields ? { fields: next.fields } : {}),
      ...(next.entityType.length ? { entity_type: next.entityType } : {}),
      ...(next.decision !== "pending" ? { decision: next.decision } : {}),
      // Any filter change resets to page one: page 4 of a narrower result set is
      // usually empty, which reads as "the filter found nothing".
      ...(overrides.page && overrides.page > 1 ? { page: overrides.page } : {}),
    },
  };
}

function Chip({
  href,
  active,
  children,
  count,
}: {
  href: ReturnType<typeof reviewHref>;
  active: boolean;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <Button
      variant={active ? "default" : "outline"}
      size="sm"
      asChild
      aria-pressed={active}
    >
      <Link href={href}>
        {children}
        {count !== undefined ? (
          <span
            className={cn(
              "figure ml-0.5",
              active ? "text-primary-foreground/70" : "text-muted-foreground",
            )}
          >
            {count}
          </span>
        ) : null}
      </Link>
    </Button>
  );
}

export function ReviewFilters({
  state,
  facets,
}: {
  state: ReviewFilterState;
  facets: ReviewQueueFacets | null;
}) {
  const filtered =
    state.vendorMatch.length > 0 ||
    state.fields !== null ||
    state.entityType.length > 0 ||
    state.decision !== "pending";
  const entityTypes = Object.keys(facets?.entity_type ?? {}).sort();

  // Toggling a chip adds or removes that one state, so several can be combined.
  const toggleVendor = (value: VendorMatch): VendorMatch[] =>
    state.vendorMatch.includes(value)
      ? state.vendorMatch.filter((entry) => entry !== value)
      : [...state.vendorMatch, value];

  return (
    <div className="space-y-2.5 rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="label-xs mr-0.5 w-14 shrink-0">Vendor</span>
        {(Object.keys(VENDOR_LABELS) as VendorMatch[]).map((value) => (
          <Chip
            key={value}
            href={reviewHref(state, { vendorMatch: toggleVendor(value) })}
            active={state.vendorMatch.includes(value)}
            count={facets?.vendor_match[value]}
          >
            {VENDOR_LABELS[value]}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="label-xs mr-0.5 w-14 shrink-0">Extracted</span>
        <Chip
          href={reviewHref(state, {
            fields: state.fields === "with" ? null : "with",
          })}
          active={state.fields === "with"}
          count={facets?.fields.with_fields}
        >
          Has fields
        </Chip>
        <Chip
          href={reviewHref(state, {
            fields: state.fields === "without" ? null : "without",
          })}
          active={state.fields === "without"}
          count={facets?.fields.without_fields}
        >
          Nothing extracted
        </Chip>
      </div>

      {/* Driven by the facets rather than hardcoded, so a new extraction type appears
          here on its own instead of being silently unfilterable. */}
      {entityTypes.length > 1 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="label-xs mr-0.5 w-14 shrink-0">Type</span>
          {entityTypes.map((value) => (
            <Chip
              key={value}
              href={reviewHref(state, {
                entityType: state.entityType.includes(value)
                  ? state.entityType.filter((entry) => entry !== value)
                  : [...state.entityType, value],
              })}
              active={state.entityType.includes(value)}
              count={facets?.entity_type[value]}
            >
              {entityLabel(value)}
            </Chip>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="label-xs mr-0.5 w-14 shrink-0">Decision</span>
        {DECISIONS.map((option) => (
          <Chip
            key={option.value}
            href={reviewHref(state, { decision: option.value })}
            active={state.decision === option.value}
          >
            {option.label}
          </Chip>
        ))}
        {filtered ? (
          <Button variant="ghost" size="sm" asChild className="ml-auto">
            <Link href={reviewHref(CLEARED)}>Clear filters</Link>
          </Button>
        ) : null}
      </div>
    </div>
  );
}
