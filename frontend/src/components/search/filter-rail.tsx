"use client";

import { useState } from "react";
import { ChevronDown, FilterX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  activeFilterCount,
  facetValues,
  MEASURE_UNITS,
  type FacetMap,
  type FilterOptions,
  type FilterState,
} from "@/components/search/filter-state";
import { labelFor } from "@/lib/labels";
import { cn } from "@/lib/utils";

function Group({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="border-b border-border last:border-0"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-3 py-2 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/60">
        <ChevronDown
          className={cn(
            "size-3 shrink-0 text-muted-foreground transition-transform",
            open ? "" : "-rotate-90",
          )}
        />
        <span className="label-xs flex-1 text-foreground">{title}</span>
        {count ? (
          <span className="font-mono text-2xs font-semibold text-primary">
            {count}
          </span>
        ) : null}
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down">
        <div className="px-3 pb-2.5">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}

const SHOW_INITIALLY = 8;

function CheckList({
  field,
  values,
  selected,
  facet,
  onToggle,
}: {
  field: string;
  values: string[];
  selected: string[];
  facet?: Record<string, number>;
  onToggle: (value: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  // Selected first, then by result count: the options that can actually narrow the
  // list should not be hidden behind "show all".
  const ordered = [...values].sort((a, b) => {
    const pickedA = selected.includes(a) ? 0 : 1;
    const pickedB = selected.includes(b) ? 0 : 1;
    if (pickedA !== pickedB) return pickedA - pickedB;
    return (facet?.[b] ?? 0) - (facet?.[a] ?? 0);
  });
  const shown = expanded ? ordered : ordered.slice(0, SHOW_INITIALLY);

  return (
    <div className="space-y-px">
      {shown.map((value) => {
        const id = field + "-" + value;
        const hits = facet?.[value];
        return (
          <label
            key={value}
            htmlFor={id}
            className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 transition-colors hover:bg-muted/50"
          >
            <Checkbox
              id={id}
              checked={selected.includes(value)}
              onCheckedChange={() => onToggle(value)}
            />
            <span className="min-w-0 flex-1 truncate text-2xs text-foreground/85">
              {labelFor(field, value)}
            </span>
            {hits ? (
              <span className="font-mono text-[0.625rem] text-muted-foreground">
                {hits}
              </span>
            ) : null}
          </label>
        );
      })}
      {ordered.length > SHOW_INITIALLY ? (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="mt-1 px-1 text-2xs text-primary transition-opacity hover:opacity-80"
        >
          {expanded ? "Show fewer" : "Show all " + String(ordered.length)}
        </button>
      ) : null}
    </div>
  );
}

function NumberPair({
  unit,
  minValue,
  maxValue,
  onMin,
  onMax,
}: {
  unit: string;
  minValue: string;
  maxValue: string;
  onMin: (value: string) => void;
  onMax: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <Input
        type="number"
        inputMode="decimal"
        value={minValue}
        onChange={(event) => onMin(event.target.value)}
        placeholder="min"
        aria-label={"Minimum, " + unit}
        className="h-7 font-mono text-2xs"
      />
      <span className="text-2xs text-muted-foreground">–</span>
      <Input
        type="number"
        inputMode="decimal"
        value={maxValue}
        onChange={(event) => onMax(event.target.value)}
        placeholder="max"
        aria-label={"Maximum, " + unit}
        className="h-7 font-mono text-2xs"
      />
      <span className="w-12 shrink-0 text-[0.625rem] text-muted-foreground">
        {unit}
      </span>
    </div>
  );
}

function Ceiling({
  unit,
  value,
  onChange,
  label,
}: {
  unit: string;
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-8 shrink-0 text-[0.625rem] text-muted-foreground">
        max
      </span>
      <Input
        type="number"
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="any"
        aria-label={label}
        className="h-7 font-mono text-2xs"
      />
      <span className="w-12 shrink-0 text-[0.625rem] text-muted-foreground">
        {unit}
      </span>
    </div>
  );
}

export function FilterRail({
  filters,
  options,
  facets,
  onToggle,
  onSet,
  onReset,
}: {
  filters: FilterState;
  options: FilterOptions | null;
  facets: FacetMap;
  onToggle: (key: keyof FilterState, value: string) => void;
  onSet: (key: keyof FilterState, value: string | boolean) => void;
  onReset: () => void;
}) {
  const active = activeFilterCount(filters);

  return (
    <aside className="h-fit overflow-hidden rounded-lg border border-border bg-card xl:sticky xl:top-[calc(var(--topbar-height)+1rem)]">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="label-xs flex-1 text-foreground">Filters</span>
        {active ? (
          <>
            <Badge variant="default">{active}</Badge>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onReset}
              aria-label="Clear all filters"
            >
              <FilterX />
            </Button>
          </>
        ) : null}
      </div>

      <Group title="Pump type" count={filters.pump_types.length} defaultOpen>
        <CheckList
          field="pump_types"
          values={options?.pump_types ?? []}
          selected={filters.pump_types}
          facet={facets.pump_type}
          onToggle={(value) => onToggle("pump_types", value)}
        />
      </Group>

      <Group title="Standard" count={filters.standards.length} defaultOpen>
        <CheckList
          field="standards"
          values={options?.standards ?? []}
          selected={filters.standards}
          facet={facets.applicable_standard}
          onToggle={(value) => onToggle("standards", value)}
        />
      </Group>

      <Group
        title="Duty point"
        count={
          [
            filters.capacity_min,
            filters.capacity_max,
            filters.head_min,
            filters.head_max,
            filters.npshr_max,
          ].filter(Boolean).length
        }
        defaultOpen
      >
        <div className="space-y-1.5">
          <p className="text-[0.625rem] text-muted-foreground">Capacity</p>
          <NumberPair
            unit={MEASURE_UNITS.capacity}
            minValue={filters.capacity_min}
            maxValue={filters.capacity_max}
            onMin={(value) => onSet("capacity_min", value)}
            onMax={(value) => onSet("capacity_max", value)}
          />
          <p className="pt-1 text-[0.625rem] text-muted-foreground">Head</p>
          <NumberPair
            unit={MEASURE_UNITS.head}
            minValue={filters.head_min}
            maxValue={filters.head_max}
            onMin={(value) => onSet("head_min", value)}
            onMax={(value) => onSet("head_max", value)}
          />
          <p className="pt-1 text-[0.625rem] text-muted-foreground">
            NPSH required
          </p>
          <Ceiling
            unit={MEASURE_UNITS.npshr}
            value={filters.npshr_max}
            onChange={(value) => onSet("npshr_max", value)}
            label="Maximum NPSH required"
          />
        </div>
      </Group>

      <Group
        title="Commercial"
        count={
          [filters.price_max, filters.lead_time_max].filter(Boolean).length
        }
      >
        <div className="space-y-1.5">
          <p className="text-[0.625rem] text-muted-foreground">Budget</p>
          <Ceiling
            unit={MEASURE_UNITS.price}
            value={filters.price_max}
            onChange={(value) => onSet("price_max", value)}
            label="Maximum price"
          />
          <p className="pt-1 text-[0.625rem] text-muted-foreground">
            Lead time
          </p>
          <Ceiling
            unit={MEASURE_UNITS.lead_time}
            value={filters.lead_time_max}
            onChange={(value) => onSet("lead_time_max", value)}
            label="Maximum lead time"
          />
        </div>
      </Group>

      <Group
        title="Area classification"
        count={filters.area_classifications.length}
      >
        <CheckList
          field="area_classifications"
          values={options?.area_classifications ?? []}
          selected={filters.area_classifications}
          facet={facets.area_classification}
          onToggle={(value) => onToggle("area_classifications", value)}
        />
      </Group>

      <Group title="Certifications" count={filters.certifications.length}>
        <CheckList
          field="certifications"
          values={facetValues(facets, "certifications", filters.certifications)}
          selected={filters.certifications}
          facet={facets.certifications}
          onToggle={(value) => onToggle("certifications", value)}
        />
      </Group>

      <Group title="Country of origin" count={filters.countries.length}>
        <CheckList
          field="countries"
          values={facetValues(facets, "country_of_origin", filters.countries)}
          selected={filters.countries}
          facet={facets.country_of_origin}
          onToggle={(value) => onToggle("countries", value)}
        />
      </Group>

      <Group title="Data confidence" count={filters.confidence_levels.length}>
        <CheckList
          field="confidence_levels"
          values={options?.confidence_levels ?? []}
          selected={filters.confidence_levels}
          facet={facets.confidence_level}
          onToggle={(value) => onToggle("confidence_levels", value)}
        />
      </Group>

      <Group
        title="Vendor"
        count={
          filters.vendor_approval_statuses.length +
          (filters.fpso_only ? 1 : 0) +
          (filters.nace_only ? 1 : 0) +
          (filters.weight_max ? 1 : 0)
        }
      >
        <CheckList
          field="vendor_approval_statuses"
          values={options?.vendor_approval_statuses ?? []}
          selected={filters.vendor_approval_statuses}
          facet={facets.approval_status}
          onToggle={(value) => onToggle("vendor_approval_statuses", value)}
        />
        <div className="mt-2 space-y-px border-t border-border pt-2">
          <label
            htmlFor="fpso-only"
            className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-muted/50"
          >
            <Checkbox
              id="fpso-only"
              checked={filters.fpso_only}
              onCheckedChange={(checked) =>
                onSet("fpso_only", checked === true)
              }
            />
            <span className="text-2xs text-foreground/85">
              FPSO / offshore experience
            </span>
          </label>
          <label
            htmlFor="nace-only"
            className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-muted/50"
          >
            <Checkbox
              id="nace-only"
              checked={filters.nace_only}
              onCheckedChange={(checked) =>
                onSet("nace_only", checked === true)
              }
            />
            <span className="text-2xs text-foreground/85">
              NACE MR0175 compliant
            </span>
          </label>
          <div className="pt-1.5">
            <p className="text-[0.625rem] text-muted-foreground">Dry weight</p>
            <div className="mt-1">
              <Ceiling
                unit={MEASURE_UNITS.weight}
                value={filters.weight_max}
                onChange={(value) => onSet("weight_max", value)}
                label="Maximum dry weight"
              />
            </div>
          </div>
        </div>
      </Group>
    </aside>
  );
}
