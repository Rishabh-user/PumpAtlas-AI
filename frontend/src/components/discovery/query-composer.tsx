"use client";

import { Search } from "lucide-react";

import { CountryPicker } from "@/components/discovery/country-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { DiscoveryScopes } from "@/types/api";

/**
 * Say what you are looking for without knowing who makes it.
 *
 * The box this replaces asked for a "pump type or duty" as free text, with pump-type
 * presets underneath — which is the wrong question for finding a *supplier*. Someone
 * searching for vendors knows the duty they are buying for and does not know the
 * manufacturers; that is the entire reason they are searching. Asking them to type a
 * name they do not have, or a pump type they may not have decided on, makes the feature
 * look like it needs knowledge it is supposed to provide.
 *
 * So the query is composed from two vocabularies the platform already enforces — pump
 * type and service duty — plus a country, and the exact phrase that will be sent is
 * shown before the click. Everything is optional: with nothing chosen it searches for
 * Oil & Gas pump suppliers generally, which is a perfectly good place to start. The free
 * text box stays for the case the pickers cannot express, including a company name when
 * you do know one.
 */
export interface ComposedQuery {
  pumpType: string | null;
  service: string | null;
  countries: string[];
  freeText: string;
}

export const EMPTY_QUERY: ComposedQuery = {
  pumpType: null,
  service: null,
  countries: [],
  freeText: "",
};

/**
 * The phrase that goes to the search provider.
 *
 * Built here rather than server-side so the person sees the actual words before starting
 * a run that can take an hour. The pieces are the vocabulary's own phrases, so what is
 * previewed is what is searched.
 */
export function composeQuery(
  value: ComposedQuery,
  scopes: DiscoveryScopes | null,
  noun: string,
): string {
  const free = value.freeText.trim();
  if (free) return free;

  const type = scopes?.pump_types.find(
    (option) => option.value === value.pumpType,
  );
  const service = scopes?.services.find(
    (option) => option.value === value.service,
  );

  const parts: string[] = [];
  parts.push(type ? type.phrase : `Oil & Gas ${noun}s`);
  if (service) parts.push(`for ${service.phrase}`);
  return parts.join(" ");
}

export function QueryComposer({
  value,
  onChange,
  scopes,
  noun,
  sweeping,
  sweepingCountries,
  maxCountries,
}: {
  value: ComposedQuery;
  onChange: (next: ComposedQuery) => void;
  scopes: DiscoveryScopes | null;
  noun: string;
  sweeping: boolean;
  sweepingCountries: boolean;
  maxCountries?: number;
}) {
  const preview = composeQuery(value, scopes, noun);
  const usingFreeText = value.freeText.trim().length > 0;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Choice
          id="composer-type"
          label="Pump type"
          hint="Any type"
          value={value.pumpType}
          options={(scopes?.pump_types ?? []).map((option) => ({
            value: option.value,
            label: option.phrase,
          }))}
          onChange={(next) => onChange({ ...value, pumpType: next })}
        />
        <Choice
          id="composer-service"
          label="Service or duty"
          hint="Any duty"
          value={value.service}
          options={(scopes?.services ?? []).map((option) => ({
            value: option.value,
            label: option.phrase,
          }))}
          onChange={(next) => onChange({ ...value, service: next })}
        />
      </div>

      {/* Its own row. Squeezed into a 5rem column beside a number input, the country
          list clipped every name to "Alger" and wrapped its own label. */}
      <CountryPicker
        selected={value.countries}
        onChange={(codes) => onChange({ ...value, countries: codes })}
        multiple={sweeping && sweepingCountries}
        max={sweeping && sweepingCountries ? maxCountries : 1}
        label={
          sweeping && sweepingCountries ? "Countries to sweep" : "Country"
        }
      />

      <div className="space-y-1.5">
        <Label htmlFor="composer-free">
          Or search for something specific
        </Label>
        <Input
          id="composer-free"
          value={value.freeText}
          onChange={(event) =>
            onChange({ ...value, freeText: event.target.value })
          }
          placeholder="A company name, a product line, or any phrase — overrides the choices above"
        />
      </div>

      {!sweeping ? (
        <p
          className={cn(
            "flex items-start gap-1.5 rounded-md border px-2.5 py-2 text-2xs leading-relaxed",
            usingFreeText
              ? "border-border bg-background/50 text-muted-foreground"
              : "border-primary/30 bg-primary/[0.06] text-foreground",
          )}
        >
          <Search className="mt-px size-3 shrink-0 text-primary" />
          <span>
            Searching for{" "}
            <span className="font-medium text-foreground">{preview}</span>
            {value.countries.length ? (
              <>
                {" "}
                in{" "}
                <span className="font-medium text-foreground">
                  {value.countries.join(", ")}
                </span>
              </>
            ) : null}
            .{" "}
            {usingFreeText
              ? "Your own words, so the pickers above are ignored."
              : "Nothing chosen means every Oil & Gas pump supplier the provider can find."}
          </span>
        </p>
      ) : null}
    </div>
  );
}

function Choice({
  id,
  label,
  hint,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string | null;
  options: Array<{ value: string; label: string }>;
  onChange: (next: string | null) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-50"
        disabled={!options.length}
      >
        <option value="">{hint}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
