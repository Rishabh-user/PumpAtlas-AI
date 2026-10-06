import { redirect } from "next/navigation";

import { ConfidenceChip } from "@/components/data/confidence";
import { EmptyState, ErrorState } from "@/components/data/states";
import { AiSearch } from "@/components/discovery/ai-search";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Pager } from "@/components/data/pager";
import { RowLink } from "@/components/data/row-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { hrefToString } from "@/lib/href";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { money, num, ratioAsPct } from "@/lib/format";
import { pumpTypeCode, standardLabel } from "@/lib/labels";
import { loadShellContext } from "@/lib/session";
import type { SearchResponse } from "@/types/api";

const EM_DASH = "—";
const PAGE_SIZE = 25;

/** Column head with its unit underneath, right-aligned to sit over the figures. */
function NumHead({ label, unit }: { label: string; unit: string }) {
  return (
    <TableHead className="text-right">
      <span className="block leading-3">{label}</span>
      <span className="block font-normal normal-case tracking-normal text-muted-foreground/60">
        {unit}
      </span>
    </TableHead>
  );
}

export const metadata = { title: "Pumps" };

/**
 * Every pump model held for the tenant, plus AI pump search.
 *
 * Backed by `POST /search` rather than `GET /pump-models`: the search endpoint already
 * joins the vendor and the current spec values, which is what a list needs. The faceted
 * workspace on `/` is for narrowing down; this page is the flat inventory.
 */
export default async function PumpsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; sort?: string; page?: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  const { q, sort, page } = await searchParams;
  const offset = Math.max(0, (Number(page ?? "1") - 1) * PAGE_SIZE);

  let results: SearchResponse | null = null;
  let error: string | null = null;
  try {
    results = await apiFetch<SearchResponse>("/search", {
      method: "POST",
      body: {
        query: q || null,
        sort: sort || "completeness_desc",
        limit: PAGE_SIZE,
        offset,
        include_facets: false,
      },
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  const shown = results ? results.offset + results.items.length : 0;
  const currentPage = Math.max(1, Number(page ?? "1"));
  const pageHref = (next: number) =>
    hrefToString({
      pathname: "/pumps",
      query: {
        ...(q ? { q } : {}),
        ...(sort ? { sort } : {}),
        ...(next > 1 ? { page: next } : {}),
      },
    });

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Pumps"
        lede="Every pump model held for your organisation, with its duty point, commercial terms and the source behind each value."
        actions={
          <>
            <AiSearch kind="pump" />
            <form
              className="flex flex-wrap items-center gap-1.5"
              action="/pumps"
            >
              <Input
                type="search"
                name="q"
                defaultValue={q ?? ""}
                placeholder="Model or vendor"
                aria-label="Search pump models"
                className="w-44"
              />
              <select
                name="sort"
                defaultValue={sort ?? "completeness_desc"}
                aria-label="Sort pump models"
                className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <option value="completeness_desc">Most complete</option>
                {/* The list's real job for most people: which records still need work. */}
                <option value="completeness_asc">Least complete (needs data)</option>
                <option value="confidence_desc">Highest confidence</option>
                <option value="capacity_desc">Largest capacity</option>
                <option value="capacity_asc">Smallest capacity</option>
                <option value="relevance">Relevance</option>
              </select>
              <Button type="submit" variant="outline">
                Apply
              </Button>
            </form>
          </>
        }
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        {results ? (
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                {results.total.toLocaleString("en-GB")} pump model
                {results.total === 1 ? "" : "s"}
              </CardTitle>
              {results.took_ms === null ? null : (
                <span className="figure text-muted-foreground">
                  {results.took_ms} ms
                </span>
              )}
            </CardHeader>

            {results.items.length === 0 ? (
              <EmptyState
                title="No pump models yet"
                hint="Run an AI pump search to find models on the web, or upload a datasheet from the import queue."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Vendor / model</TableHead>
                    <TableHead>Type</TableHead>
                    <NumHead label="Capacity" unit="m³/h" />
                    <NumHead label="Head" unit="m" />
                    <NumHead label="NPSHr" unit="m" />
                    <NumHead label="Efficiency" unit="%" />
                    <NumHead label="Price" unit="USD" />
                    <NumHead label="Lead" unit="weeks" />
                    <NumHead label="Complete" unit="%" />
                    <TableHead>Confidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.items.map((row) => (
                    <TableRow key={row.pump_model_id}>
                      <TableCell className="max-w-[18rem]">
                        <RowLink
                          href={"/pumps/" + row.pump_model_id}
                          label={`Opening ${row.model_code ?? row.label}…`}
                          className="block truncate font-mono text-xs font-medium text-foreground transition-colors hover:text-primary"
                        >
                          {row.model_code ?? row.label}
                        </RowLink>
                        <div className="mt-0.5 flex items-center gap-1.5 text-[0.625rem] text-muted-foreground">
                          <span className="truncate">
                            {row.vendor_name ?? EM_DASH}
                          </span>
                          {row.country_of_origin ? (
                            <span className="font-mono">
                              {row.country_of_origin}
                            </span>
                          ) : null}
                        </div>
                        {row.fpso_experience || row.open_flag_count ? (
                          <div className="mt-1 flex flex-wrap items-center gap-1">
                            {row.fpso_experience ? (
                              <Badge variant="outline">FPSO</Badge>
                            ) : null}
                            {row.open_flag_count ? (
                              <Badge variant="warning">
                                {row.open_flag_count} flag
                                {row.open_flag_count === 1 ? "" : "s"}
                              </Badge>
                            ) : null}
                          </div>
                        ) : null}
                      </TableCell>

                      <TableCell>
                        <span className="font-mono text-xs text-foreground">
                          {pumpTypeCode(row.pump_type)}
                        </span>
                        <span className="mt-0.5 block text-[0.625rem] text-muted-foreground">
                          {standardLabel(row.applicable_standard)}
                        </span>
                      </TableCell>

                      <TableCell className="figure text-right">
                        {num(row.rated_capacity_m3h, { decimals: 1 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {num(row.rated_head_m, { decimals: 1 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {num(row.npsh_required_m, { decimals: 1 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {num(row.hydraulic_efficiency_pct, { decimals: 1 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {row.base_price_usd === null ||
                        row.base_price_usd === undefined
                          ? EM_DASH
                          : money(row.base_price_usd)}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {num(row.standard_lead_time_weeks, { decimals: 0 })}
                      </TableCell>
                      <TableCell className="figure text-right">
                        {ratioAsPct(row.data_completeness_pct)}
                      </TableCell>
                      <TableCell>
                        <ConfidenceChip level={row.confidence_level} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
        ) : null}

        {results ? (
          <Pager
            total={results.total}
            offset={results.offset}
            limit={PAGE_SIZE}
            prevHref={currentPage > 1 ? pageHref(currentPage - 1) : null}
            nextHref={shown < results.total ? pageHref(currentPage + 1) : null}
            noun="pump models"
          />
        ) : null}
      </div>
    </AppShell>
  );
}
