"use client";

import Link from "next/link";
import { X } from "lucide-react";

import { ConfidenceChip } from "@/components/data/confidence";
import {
  EmptyState,
  ErrorState,
  TableSkeleton,
} from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  LIST_KEYS,
  RANGE_LABELS,
  RANGE_UNITS,
  type FilterState,
} from "@/components/search/filter-state";
import { money, num, ratioAsPct } from "@/lib/format";
import { labelFor, pumpTypeCode, standardLabel } from "@/lib/labels";
import type { SearchResponse } from "@/types/api";

const EM_DASH = "—";

/** Removable chips for what is currently applied — the only way to see it at a glance. */
export function ActiveFilters({
  filters,
  onRemoveFromList,
  onClearField,
}: {
  filters: FilterState;
  onRemoveFromList: (key: keyof FilterState, value: string) => void;
  onClearField: (key: keyof FilterState) => void;
}) {
  const chips: React.ReactNode[] = [];

  for (const key of LIST_KEYS) {
    for (const value of filters[key]) {
      chips.push(
        <button
          key={key + "-" + value}
          type="button"
          onClick={() => onRemoveFromList(key, value)}
          className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-1.5 py-px text-2xs text-primary transition-colors hover:bg-primary/20"
        >
          {labelFor(key, value)}
          <X className="size-2.5" />
        </button>,
      );
    }
  }

  for (const [key, label] of Object.entries(RANGE_LABELS)) {
    const value = filters[key as keyof FilterState];
    if (typeof value === "string" && value.trim()) {
      chips.push(
        <button
          key={key}
          type="button"
          onClick={() => onClearField(key as keyof FilterState)}
          className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-1.5 py-px text-2xs text-primary transition-colors hover:bg-primary/20"
        >
          <span className="text-primary/70">{label}</span>
          <span className="font-mono">{value}</span>
          {RANGE_UNITS[key] ? (
            <span className="text-primary/70">{RANGE_UNITS[key]}</span>
          ) : null}
          <X className="size-2.5" />
        </button>,
      );
    } else if (value === true) {
      chips.push(
        <button
          key={key}
          type="button"
          onClick={() => onClearField(key as keyof FilterState)}
          className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-1.5 py-px text-2xs text-primary transition-colors hover:bg-primary/20"
        >
          {label}
          <X className="size-2.5" />
        </button>,
      );
    }
  }

  if (!chips.length) return null;
  return <div className="flex flex-wrap items-center gap-1.5">{chips}</div>;
}

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

export function ResultsTable({
  response,
  loading,
  error,
  selected,
  onToggleSelected,
}: {
  response: SearchResponse | null;
  loading: boolean;
  error: string | null;
  selected: string[];
  onToggleSelected: (id: string) => void;
}) {
  if (error) return <ErrorState message={error} />;

  if (loading && !response) {
    return (
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex h-9 items-center border-b border-border px-3">
          <span className="label-xs">Pump models</span>
        </div>
        <TableSkeleton rows={8} cols={9} />
      </div>
    );
  }

  if (!response) return null;

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex h-9 items-center gap-2 border-b border-border px-3">
        <span className="label-xs text-foreground">
          {response.total.toLocaleString("en-GB")} pump model
          {response.total === 1 ? "" : "s"}
        </span>
        {response.took_ms === null ? null : (
          <span className="font-mono text-[0.625rem] text-muted-foreground">
            {response.took_ms} ms
          </span>
        )}
        {loading ? (
          <span className="ml-auto flex items-center gap-1.5 text-2xs text-primary">
            <span className="size-1.5 animate-pulse rounded-full bg-primary" />
            Searching
          </span>
        ) : null}
      </div>

      {response.items.length === 0 ? (
        <EmptyState
          title="No pump models match these filters"
          hint="Widen a range, clear a filter, or bring in more sources from the import queue."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Vendor / model</TableHead>
              <TableHead>Type</TableHead>
              <NumHead label="Capacity" unit="m³/h" />
              <NumHead label="Head" unit="m" />
              <NumHead label="NPSHr" unit="m" />
              <NumHead label="Price" unit="USD" />
              <NumHead label="Lead" unit="weeks" />
              <NumHead label="Dry wt" unit="kg" />
              <TableHead>Confidence</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {response.items.map((row) => {
              const picked = selected.includes(row.pump_model_id);
              return (
                <TableRow
                  key={row.pump_model_id}
                  data-state={picked ? "selected" : undefined}
                >
                  <TableCell>
                    <Checkbox
                      checked={picked}
                      onCheckedChange={() =>
                        onToggleSelected(row.pump_model_id)
                      }
                      aria-label={"Select " + row.label}
                    />
                  </TableCell>

                  <TableCell className="max-w-[18rem]">
                    <Link
                      href={"/pumps/" + row.pump_model_id}
                      className="block truncate font-mono text-xs font-medium text-foreground transition-colors hover:text-primary"
                    >
                      {row.model_code ?? row.label}
                    </Link>
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
                    {row.base_price_usd === null ||
                    row.base_price_usd === undefined
                      ? EM_DASH
                      : money(row.base_price_usd)}
                  </TableCell>
                  <TableCell className="figure text-right">
                    {num(row.standard_lead_time_weeks, { decimals: 0 })}
                  </TableCell>
                  <TableCell className="figure text-right">
                    {num(row.dry_weight_kg, { decimals: 0 })}
                  </TableCell>

                  <TableCell>
                    <ConfidenceChip level={row.confidence_level} />
                    {row.data_completeness_pct !== null &&
                    row.data_completeness_pct !== undefined ? (
                      <span className="mt-0.5 block font-mono text-[0.625rem] text-muted-foreground">
                        {ratioAsPct(row.data_completeness_pct)} complete
                      </span>
                    ) : null}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
