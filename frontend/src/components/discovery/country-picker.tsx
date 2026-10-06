"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Globe2, Loader2, X } from "lucide-react";

import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { CountryOption } from "@/types/api";

/**
 * Pick countries by name, from the real ISO list.
 *
 * The box this replaces was two characters of free text, which is an invitation to type
 * "Uk", "usa" or "germany" — none of which are alpha-2 codes, and all of which the
 * extraction pipeline already has to repair when a model returns them. Choosing from
 * names removes the class of mistake rather than correcting it afterwards.
 *
 * Pump-supply countries are listed first because they are almost always the answer;
 * everything else follows, so the list is complete without being a wall.
 */
export function CountryPicker({
  selected,
  onChange,
  multiple = false,
  max,
  label = "Country",
}: {
  selected: string[];
  onChange: (codes: string[]) => void;
  /** Single-country bias for one search, or a set of countries to sweep. */
  multiple?: boolean;
  max?: number;
  label?: string;
}) {
  const [countries, setCountries] = useState<CountryOption[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (countries || failed) return;
    clientFetch<{ countries: CountryOption[] }>("/meta/countries")
      .then((data) => setCountries(data.countries))
      .catch(() => setFailed(true));
  }, [countries, failed]);

  const byCode = useMemo(
    () => new Map((countries ?? []).map((country) => [country.code, country])),
    [countries],
  );
  const supply = (countries ?? []).filter((country) => country.pump_supply);
  const rest = (countries ?? []).filter((country) => !country.pump_supply);
  const atMax = max !== undefined && selected.length >= max;

  function toggle(code: string) {
    if (!multiple) {
      onChange(selected[0] === code ? [] : [code]);
      setOpen(false);
      return;
    }
    if (selected.includes(code)) {
      onChange(selected.filter((value) => value !== code));
    } else if (!atMax) {
      onChange([...selected, code]);
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label-xs text-muted-foreground">{label}</span>
        {multiple && selected.length ? (
          <button
            type="button"
            onClick={() => onChange([])}
            className="text-2xs text-primary hover:underline"
          >
            Clear {selected.length}
          </button>
        ) : null}
      </div>

      {selected.length ? (
        <div className="flex flex-wrap gap-1">
          {selected.map((code) => (
            <Badge key={code} variant="outline" className="gap-1">
              {byCode.get(code)?.name ?? code}
              <button
                type="button"
                onClick={() => toggle(code)}
                aria-label={`Remove ${byCode.get(code)?.name ?? code}`}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-2.5" />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}

      {open ? (
        <Command className="rounded-md border border-border bg-card">
          <CommandInput placeholder="Search countries…" />
          <CommandList className="max-h-56">
            {countries === null ? (
              <p className="flex items-center gap-1.5 px-2 py-3 text-2xs text-muted-foreground">
                {failed ? (
                  "Could not load the country list."
                ) : (
                  <>
                    <Loader2 className="size-3 animate-spin" />
                    Loading countries…
                  </>
                )}
              </p>
            ) : (
              <>
                <CommandGroup heading="Oil & Gas pump supply">
                  {supply.map((country) => (
                    <Row
                      key={country.code}
                      country={country}
                      checked={selected.includes(country.code)}
                      disabled={atMax && !selected.includes(country.code)}
                      onSelect={() => toggle(country.code)}
                    />
                  ))}
                </CommandGroup>
                <CommandGroup heading="Everywhere else">
                  {rest.map((country) => (
                    <Row
                      key={country.code}
                      country={country}
                      checked={selected.includes(country.code)}
                      disabled={atMax && !selected.includes(country.code)}
                      onSelect={() => toggle(country.code)}
                    />
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      ) : (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setOpen(true)}
        >
          <Globe2 />
          {selected.length
            ? multiple
              ? "Add or remove"
              : "Change"
            : multiple
              ? "Choose countries"
              : "Anywhere"}
        </Button>
      )}

      {atMax ? (
        <p className="text-2xs text-sev-medium">
          {max} is the most a single sweep takes — each country is one search and
          up to a page-count of reading.
        </p>
      ) : null}
    </div>
  );
}

function Row({
  country,
  checked,
  disabled,
  onSelect,
}: {
  country: CountryOption;
  checked: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <CommandItem
      value={`${country.name} ${country.code}`}
      onSelect={disabled ? undefined : onSelect}
      className={cn(
        "flex items-center gap-2 text-xs",
        disabled ? "opacity-40" : null,
      )}
    >
      <Check
        className={cn("size-3 shrink-0", checked ? "text-primary" : "opacity-0")}
      />
      <span className="flex-1">{country.name}</span>
      <span className="font-mono text-2xs text-muted-foreground">
        {country.code}
      </span>
    </CommandItem>
  );
}
