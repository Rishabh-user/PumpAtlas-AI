"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeftRight, Search, SlidersHorizontal } from "lucide-react";

import { FilterRail } from "@/components/search/filter-rail";
import { ActiveFilters, ResultsTable } from "@/components/search/results-table";
import {
  activeFilterCount,
  EMPTY_FILTERS,
  normaliseFacets,
  toNumber,
  type FilterOptions,
  type FilterState,
} from "@/components/search/filter-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { clientFetch } from "@/lib/api-client";
import { humanise } from "@/lib/labels";
import type { SearchResponse } from "@/types/api";

const PAGE_SIZE = 25;
const MAX_COMPARE = 12;

export function SearchWorkspace({
  options,
  initialQuery = "",
}: {
  options: FilterOptions | null;
  initialQuery?: string;
}) {
  const [filters, setFilters] = useState<FilterState>({
    ...EMPTY_FILTERS,
    query: initialQuery,
  });
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const body = useMemo(
    () => ({
      query: filters.query || null,
      pump_types: filters.pump_types,
      standards: filters.standards,
      countries: filters.countries,
      certifications: filters.certifications,
      area_classifications: filters.area_classifications,
      confidence_levels: filters.confidence_levels,
      vendor_approval_statuses: filters.vendor_approval_statuses,
      capacity_min: toNumber(filters.capacity_min),
      capacity_max: toNumber(filters.capacity_max),
      head_min: toNumber(filters.head_min),
      head_max: toNumber(filters.head_max),
      npshr_max: toNumber(filters.npshr_max),
      price_max: toNumber(filters.price_max),
      lead_time_max: toNumber(filters.lead_time_max),
      weight_max: toNumber(filters.weight_max),
      fpso_experience: filters.fpso_only ? true : null,
      nace_compliant: filters.nace_only ? true : null,
      sort: filters.sort,
      limit: PAGE_SIZE,
      offset,
      include_facets: true,
    }),
    [filters, offset],
  );

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResults(
        await clientFetch<SearchResponse>("/search", { method: "POST", body }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }, [body]);

  // Debounced, so typing in the box does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => void run(), filters.query ? 250 : 0);
    return () => clearTimeout(timer);
  }, [run, filters.query]);

  const toggleList = useCallback((key: keyof FilterState, value: string) => {
    setOffset(0);
    setFilters((current) => {
      const list = current[key] as string[];
      return {
        ...current,
        [key]: list.includes(value)
          ? list.filter((entry) => entry !== value)
          : [...list, value],
      };
    });
  }, []);

  const setField = useCallback(
    (key: keyof FilterState, value: string | boolean) => {
      setOffset(0);
      setFilters((current) => ({ ...current, [key]: value }));
    },
    [],
  );

  const clearField = useCallback((key: keyof FilterState) => {
    setOffset(0);
    setFilters((current) => ({
      ...current,
      [key]:
        typeof current[key] === "boolean"
          ? false
          : Array.isArray(current[key])
            ? []
            : "",
    }));
  }, []);

  const reset = useCallback(() => {
    setOffset(0);
    setFilters((current) => ({ ...EMPTY_FILTERS, query: current.query }));
  }, []);

  const rail = (
    <FilterRail
      filters={filters}
      options={options}
      facets={normaliseFacets(results?.facets)}
      onToggle={toggleList}
      onSet={setField}
      onReset={reset}
    />
  );

  const active = activeFilterCount(filters);
  const shown = results ? results.offset + results.items.length : 0;

  return (
    <div className="grid gap-4 xl:grid-cols-[15rem_minmax(0,1fr)]">
      <div className="hidden xl:block">{rail}</div>

      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {/* The rail collapses into a sheet below xl, where it would eat the grid. */}
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline" size="default" className="xl:hidden">
                <SlidersHorizontal />
                Filters
                {active ? <Badge variant="default">{active}</Badge> : null}
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-80 overflow-y-auto p-3">
              <SheetTitle className="sr-only">Filters</SheetTitle>
              {rail}
            </SheetContent>
          </Sheet>

          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              value={filters.query}
              onChange={(event) => setField("query", event.target.value)}
              placeholder='Narrow these results — "API 610 BB3 crude export", or a model code'
              aria-label="Search within results"
              className="pl-8"
            />
          </div>

          <Select
            value={filters.sort}
            onValueChange={(value) => setField("sort", value)}
          >
            <SelectTrigger className="w-40" aria-label="Sort results">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(options?.sort_options ?? ["relevance"]).map((option) => (
                <SelectItem key={option} value={option}>
                  {humanise(option)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <ActiveFilters
          filters={filters}
          onRemoveFromList={toggleList}
          onClearField={clearField}
        />

        {selected.length > 1 ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/[0.07] px-3 py-2">
            <span className="text-xs font-medium text-primary">
              <span className="font-mono">{selected.length}</span> models
              selected
            </span>
            <div className="flex items-center gap-1.5">
              <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
                Clear
              </Button>
              <Button size="sm" asChild>
                <Link href={"/compare?models=" + selected.join(",")}>
                  <ArrowLeftRight />
                  Compare
                </Link>
              </Button>
            </div>
          </div>
        ) : null}

        <ResultsTable
          response={results}
          loading={loading}
          error={error}
          selected={selected}
          onToggleSelected={(id) =>
            setSelected((current) =>
              current.includes(id)
                ? current.filter((value) => value !== id)
                : [...current, id].slice(0, MAX_COMPARE),
            )
          }
        />

        {results && results.total > PAGE_SIZE ? (
          <div className="flex items-center justify-between text-2xs text-muted-foreground">
            <span className="font-mono">
              {results.offset + 1}–{shown} of{" "}
              {results.total.toLocaleString("en-GB")}
            </span>
            <div className="flex gap-1.5">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + PAGE_SIZE >= results.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
