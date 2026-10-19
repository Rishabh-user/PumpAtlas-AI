"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, PencilLine, X } from "lucide-react";

import { ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { clientFetch } from "@/lib/api-client";
import { fieldLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * Enter specification data by hand.
 *
 * Every empty panel told the reader to "submit the data through the manual form", and
 * no such form existed — nothing in the product ever called
 * `PUT /pump-models/{id}/specs/{group}`. For five of the six groups that was the only
 * route in: a manufacturer publishes duty curves and materials, and never publishes a
 * price, a lead time or a delivery record. Measured over ten enrichment runs, six
 * models gained technical specifications and none gained anything else.
 *
 * The fields come from the API rather than a list kept here, because a form that
 * hardcodes sixty commercial column names drifts from the schema the first time a
 * column is added — and drifts silently, by simply never showing the new field.
 */

interface FieldDescriptor {
  name: string;
  label: string;
  type: "text" | "number" | "boolean" | "date" | "choice" | "list";
  unit: string | null;
  choices: string[] | null;
}

export function SpecForm({
  pumpModelId,
  group,
  groupLabel,
  headlineFields,
  current,
  onDone,
}: {
  pumpModelId: string;
  group: string;
  groupLabel: string;
  /** Shown first; everything else sits behind a disclosure. */
  headlineFields: string[];
  current: Record<string, unknown> | null;
  onDone?: () => void;
}) {
  const router = useRouter();
  const [fields, setFields] = useState<FieldDescriptor[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [showAll, setShowAll] = useState(false);
  const [verified, setVerified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    clientFetch<FieldDescriptor[]>(`/spec-fields/${group}`)
      .then((rows) => {
        if (!cancelled) setFields(rows);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof Error ? caught.message : "Could not load the fields",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [group]);

  if (error && !fields) return <ErrorState message={error} />;
  if (!fields) {
    return (
      <p className="flex items-center gap-1.5 p-3 text-2xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" /> Loading {groupLabel} fields…
      </p>
    );
  }

  const headline = new Set(headlineFields);
  const ordered = [
    ...fields.filter((f) => headline.has(f.name)),
    ...fields.filter((f) => !headline.has(f.name)),
  ];
  const shown = showAll ? ordered : ordered.filter((f) => headline.has(f.name));

  function set(name: string, raw: string) {
    setValues((prev) => ({ ...prev, [name]: raw }));
    setSaved(null);
  }

  /** Only what was actually typed. An untouched field must not overwrite a value. */
  function payload(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const field of fields ?? []) {
      const raw = values[field.name];
      if (raw === undefined || raw.trim() === "") continue;
      if (field.type === "number") {
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) out[field.name] = parsed;
      } else if (field.type === "boolean") {
        out[field.name] = raw === "true";
      } else if (field.type === "list") {
        out[field.name] = raw
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean);
      } else {
        out[field.name] = raw.trim();
      }
    }
    return out;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const body = payload();
    const count = Object.keys(body).length;
    if (!count) {
      setError("Nothing to save — fill in at least one field.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await clientFetch(
        `/pump-models/${pumpModelId}/specs/${group}?mark_verified=${verified}`,
        { method: "PUT", body },
      );
      setSaved(count);
      setValues({});
      // The panels above are server-rendered, so the page has to re-fetch to show it.
      router.refresh();
      onDone?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-3 p-3">
      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((field) => {
          const held = current?.[field.name];
          return (
            <label key={field.name} className="block min-w-0">
              <span className="label-xs block truncate text-muted-foreground">
                {fieldLabel(field.name) || field.label}
                {field.unit ? (
                  <span className="ml-1 opacity-60">({field.unit})</span>
                ) : null}
              </span>

              {field.type === "choice" && field.choices ? (
                <select
                  value={values[field.name] ?? ""}
                  onChange={(event) => set(field.name, event.target.value)}
                  className="mt-0.5 h-7 w-full rounded border border-border bg-background px-1.5 text-xs"
                >
                  <option value="">—</option>
                  {field.choices.map((choice) => (
                    <option key={choice} value={choice}>
                      {choice}
                    </option>
                  ))}
                </select>
              ) : field.type === "boolean" ? (
                <select
                  value={values[field.name] ?? ""}
                  onChange={(event) => set(field.name, event.target.value)}
                  className="mt-0.5 h-7 w-full rounded border border-border bg-background px-1.5 text-xs"
                >
                  <option value="">—</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              ) : (
                <Input
                  type={
                    field.type === "number"
                      ? "number"
                      : field.type === "date"
                        ? "date"
                        : "text"
                  }
                  step={field.type === "number" ? "any" : undefined}
                  value={values[field.name] ?? ""}
                  onChange={(event) => set(field.name, event.target.value)}
                  placeholder={
                    held !== null && held !== undefined && held !== ""
                      ? String(held)
                      : field.type === "list"
                        ? "comma, separated"
                        : ""
                  }
                  className="mt-0.5 h-7 text-xs"
                />
              )}
            </label>
          );
        })}
      </div>

      {ordered.length > shown.length || showAll ? (
        <button
          type="button"
          onClick={() => setShowAll((previous) => !previous)}
          className="text-2xs text-primary hover:underline"
        >
          {showAll
            ? `Show the ${headlineFields.length} main fields`
            : `Show all ${ordered.length} ${groupLabel.toLowerCase()} fields`}
        </button>
      ) : null}

      {error ? <p className="text-2xs text-destructive">{error}</p> : null}
      {saved ? (
        <p className="flex items-center gap-1.5 text-2xs text-conf-verified">
          <Check className="size-3" />
          Saved {saved} field{saved === 1 ? "" : "s"} as a new version. The
          previous one is retained.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="sm" disabled={saving}>
          {saving ? <Loader2 className="animate-spin" /> : <Check />}
          {saving ? "Saving…" : "Save"}
        </Button>
        <label className="flex items-center gap-1.5 text-2xs text-muted-foreground">
          <input
            type="checkbox"
            checked={verified}
            onChange={(event) => setVerified(event.target.checked)}
            className="size-3 accent-[var(--conf-verified)]"
          />
          {/* Not cosmetic: a verified value is one an AI run is refused permission to
            * overwrite, which is the whole point of recording who said it. */}
          I am confirming these from a document — record as verified
        </label>
      </div>
    </form>
  );
}

/** The button that opens the form, so a panel can stay collapsed until it is wanted. */
export function SpecFormToggle({
  label = "Enter data",
  open,
  onToggle,
  className,
}: {
  label?: string;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "inline-flex items-center gap-1 text-2xs text-primary hover:underline",
        className,
      )}
    >
      {open ? <X className="size-3" /> : <PencilLine className="size-3" />}
      {open ? "Cancel" : label}
    </button>
  );
}
