"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, ChevronDown, ChevronRight, ExternalLink, Loader2, Save } from "lucide-react";

import { RecordPanels } from "@/components/chat/record-panels";
import { isCurrencyCompanion, specValue } from "@/components/format-spec";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fieldLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type {
  ChatRecordHit,
  ChatWebSource,
  DiscoveryCandidate,
  StoredRecord,
} from "@/types/api";

/**
 * A cited record as a card, showing what the record actually says.
 *
 * The answer's prose names a model and quotes the one figure the question asked
 * about. That is correct for prose and useless for judging a model — "MSD-RO,
 * rated head 650 m" says nothing about flow, speed, materials or what standard it
 * is built to, all of which are on the record and none of which the sentence had
 * room for.
 *
 * So the card carries a duty summary. Which fields appear is decided per record
 * rather than fixed, because the catalogue is uneven: a page that states a
 * product-line envelope populates `max_capacity_m3h` and leaves
 * `rated_capacity_m3h` null, and a card wired to the rated columns alone would be
 * blank for most of the catalogue — the same "only the name" problem in a box.
 */

/**
 * Duty figures worth leading with, most telling first.
 *
 * Rated before envelope, because a rated point is a commitment and an envelope is
 * a range the model can be built within. Both are shown when both exist; the
 * label carries the difference, so nothing here has to pretend a maximum is a
 * duty point.
 */
const PREFERRED_FIELDS = [
  "rated_capacity_m3h",
  "max_capacity_m3h",
  "rated_head_m",
  "max_head_m",
  "rated_power_kw",
  "rated_speed_rpm",
  "npsh_required_m",
  "hydraulic_efficiency_pct",
  "bep_efficiency_pct",
  "stages",
  "size_designation",
  "material_class",
  "seal_system_type",
  "nace_mr0175_compliant",
  "area_classification",
  "casing_design_pressure_barg",
  "fluid_temperature_max_c",
  "driver_type",
  "suction_size_mm",
  "discharge_size_mm",
];

const MAX_HIGHLIGHTS = 8;

/** Whether a value is a quantity a reader would compare against the row above. */
function isFigure(value: unknown): boolean {
  if (typeof value === "number") return true;
  if (typeof value === "boolean") return false;
  if (typeof value === "string") return /^[\d][\d.,\s]*$/.test(value.trim());
  return false;
}

interface Highlight {
  name: string;
  value: unknown;
  /** The group's other values, so a money figure keeps its currency. */
  siblings: Record<string, unknown>;
}

/**
 * The fields to show on the card.
 *
 * The preferred list first, then whatever else the record holds, so a record with
 * an unusual shape still shows something rather than nothing. A record that holds
 * only identity fields yields an empty list, and the card says so — which is a
 * fact about the catalogue worth seeing, not a rendering failure.
 */
function highlightsFor(record: ChatRecordHit): Highlight[] {
  const pool = new Map<string, Highlight>();

  for (const group of record.groups) {
    const siblings: Record<string, unknown> = Object.fromEntries(
      group.fields.map((field) => [field.field_name, field.value]),
    );
    for (const field of group.fields) {
      if (pool.has(field.field_name)) continue;
      if (isCurrencyCompanion(field.field_name, siblings)) continue;
      pool.set(field.field_name, {
        name: field.field_name,
        value: field.value,
        siblings,
      });
    }
  }

  const chosen: Highlight[] = [];
  for (const name of PREFERRED_FIELDS) {
    const hit = pool.get(name);
    if (hit) {
      chosen.push(hit);
      pool.delete(name);
    }
    if (chosen.length >= MAX_HIGHLIGHTS) return chosen;
  }

  // Identity fields already sit in the card's header, so they would only repeat
  // themselves among the figures.
  const shownInHeader = new Set([
    "model_code",
    "pump_name",
    "vendor_name",
    "pump_type",
    "pump_type_raw",
    "applicable_standard",
    "product_family",
  ]);
  for (const [name, hit] of pool) {
    if (shownInHeader.has(name)) continue;
    // A UUID is never something a reader compares. These identify the row to the
    // database, not the pump to an engineer, and one of them on a thin record
    // pushes out a field that would have said something.
    if (/(^|_)id$/.test(name)) continue;
    // A false flag is not news. "Discontinued: no" is the ordinary case and
    // spends a row that a duty figure could have had — whereas a *true* one is
    // among the most important things on the card, so only the negative goes.
    if (hit.value === false) continue;
    chosen.push(hit);
    if (chosen.length >= MAX_HIGHLIGHTS) break;
  }
  return chosen;
}

export function RecordCard({
  record,
  highlighted = false,
  defaultOpen = false,
}: {
  record: ChatRecordHit;
  /** The marker in the prose was just clicked. */
  highlighted?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const highlights = highlightsFor(record);
  const tracked = record.groups.reduce((sum, group) => sum + group.tracked, 0);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border bg-card transition-shadow",
        highlighted ? "border-primary/60 ring-2 ring-primary/30" : "border-border",
      )}
    >
      <div className="border-b border-border px-3 py-2">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 rounded border border-primary/40 bg-primary/10 px-1 font-mono text-[0.625rem] leading-relaxed text-primary">
            {record.marker}
          </span>
          <div className="min-w-0 flex-1">
            <Link
              href={`/pumps/${record.pump_model_id}`}
              className="text-xs font-medium text-primary hover:underline"
            >
              {record.label || record.model_code || "pump model"}
              <ExternalLink className="ml-0.5 inline size-2.5" />
            </Link>
            <p className="truncate text-2xs text-muted-foreground">
              {record.vendor_name || "vendor not stated"}
            </p>
          </div>
          <span
            className="figure flex-shrink-0 text-2xs text-muted-foreground"
            title={`${record.recorded_count} of ${tracked} tracked fields are recorded for this model`}
          >
            {record.recorded_count}/{tracked}
          </span>
        </div>

        {record.pump_type || record.applicable_standard ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {record.pump_type ? (
              <Badge variant="outline" className="text-2xs">
                {record.pump_type.replace(/_/g, " ")}
              </Badge>
            ) : null}
            {record.applicable_standard ? (
              <Badge variant="outline" className="text-2xs">
                {record.applicable_standard.replace(/_/g, " ").toUpperCase()}
              </Badge>
            ) : null}
          </div>
        ) : null}
      </div>

      {highlights.length ? (
        <dl className="divide-y divide-border/60 px-3">
          {highlights.map((highlight) => (
            <div
              key={highlight.name}
              className="flex items-baseline justify-between gap-3 py-1"
            >
              <dt className="text-2xs text-muted-foreground">
                {fieldLabel(highlight.name)}
              </dt>
              <dd
                className={cn(
                  "min-w-0 flex-1 text-right text-foreground",
                  // `.figure` sets mono and tabular numerals so a column of
                  // numbers lines up. Applied to prose it just makes a service
                  // list harder to read, so it goes on figures only.
                  isFigure(highlight.value)
                    ? "figure"
                    : "line-clamp-2 text-2xs leading-relaxed",
                )}
                title={typeof highlight.value === "string" ? highlight.value : undefined}
              >
                {specValue(highlight.name, highlight.value, highlight.siblings)}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="px-3 py-2 text-2xs leading-relaxed text-muted-foreground">
          This record holds its identity and no specification fields — which is why
          the answer can name it but not describe its duty. Capture a datasheet to
          fill it in.
        </p>
      )}

      <div className="flex items-center gap-2 px-3 py-1.5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex items-center gap-0.5 text-2xs text-primary hover:underline"
        >
          {open ? (
            <ChevronDown className="size-3" />
          ) : (
            <ChevronRight className="size-3" />
          )}
          {open ? "Hide all fields" : "All fields"}
        </button>
      </div>

      {open ? (
        <div className="border-t border-border p-2">
          <RecordPanels record={record} defaultOpen />
        </div>
      ) : null}
    </div>
  );
}

/**
 * A cited web page, in the same card language as a held record.
 *
 * A search provider hands back a title and a link, which is not enough to judge
 * anything — so the page is fetched and read, and whatever the reading model
 * could support with a verbatim quote is shown here as fields. That is the same
 * pipeline `/pumps` uses, and every value carries the sentence it came from,
 * reachable from the field's tooltip.
 *
 * It still is not a record, and the card never pretends otherwise: the marker is
 * neutral where a record's is primary, the badge says "web page", and nothing is
 * in the database until **Store** is pressed. Until then this is a proposal with
 * its evidence attached.
 */
export function WebCard({
  source,
  candidate,
  reading = false,
  ruledOut = false,
  stored = null,
  storing = false,
  onStore,
}: {
  source: ChatWebSource;
  /** What reading the page produced, once it has been read. */
  candidate?: DiscoveryCandidate | null;
  /** The page is still being fetched and read. */
  reading?: boolean;
  /** The page was read and held no pump model — a category or listing page. */
  ruledOut?: boolean;
  /** Set once this candidate has been written to the record. */
  stored?: StoredRecord | null;
  storing?: boolean;
  onStore?: (candidate: DiscoveryCandidate) => void;
}) {
  let domain = source.url;
  try {
    domain = new URL(source.url).hostname.replace(/^www\./, "");
  } catch {
    // A provider can return something that is not a parseable URL; the raw
    // string is still the most useful thing to show.
  }

  const fields = (candidate?.fields ?? []).filter(
    (field) => field.value !== null && field.value !== "" && field.value !== undefined,
  );

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="border-b border-border px-3 py-2">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 rounded border border-border bg-muted px-1 font-mono text-[0.625rem] leading-relaxed text-muted-foreground">
            {source.marker}
          </span>
          <div className="min-w-0 flex-1">
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer noopener"
              className="line-clamp-2 text-xs font-medium text-primary hover:underline"
            >
              {candidate?.title || source.title || source.url}
              <ExternalLink className="ml-0.5 inline size-2.5" />
            </a>
            <p className="truncate text-2xs text-muted-foreground">
              {candidate?.vendor_name ? `${candidate.vendor_name} · ` : ""}
              {domain}
            </p>
          </div>
          <Badge variant="outline" className="flex-shrink-0 text-2xs">
            web page
          </Badge>
        </div>

        {candidate?.pump_type || candidate?.applicable_standard ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {candidate.pump_type ? (
              <Badge variant="outline" className="text-2xs">
                {candidate.pump_type.replace(/_/g, " ")}
              </Badge>
            ) : null}
            {candidate.applicable_standard ? (
              <Badge variant="outline" className="text-2xs">
                {candidate.applicable_standard.replace(/_/g, " ").toUpperCase()}
              </Badge>
            ) : null}
          </div>
        ) : null}
      </div>

      {fields.length ? (
        <dl className="divide-y divide-border/60 px-3">
          {fields.slice(0, MAX_HIGHLIGHTS).map((field) => (
            <div
              key={field.field_name}
              className="flex items-baseline justify-between gap-3 py-1"
            >
              <dt className="text-2xs text-muted-foreground">{field.label}</dt>
              <dd
                className={cn(
                  "min-w-0 flex-1 text-right text-foreground",
                  isFigure(field.value)
                    ? "figure"
                    : "line-clamp-2 text-2xs leading-relaxed",
                )}
                // The quote behind the value. A figure with no traceable sentence
                // is exactly what this platform refuses to store.
                title={field.evidence ?? undefined}
              >
                {String(field.value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : reading ? (
        <p className="flex items-center gap-1.5 px-3 py-2 text-2xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin text-primary" />
          Reading this page for its specification…
        </p>
      ) : ruledOut ? (
        <p className="px-3 py-2 text-2xs leading-relaxed text-muted-foreground">
          Read, and it names no pump model — a category or listing page rather than
          a product. Nothing here to record.
        </p>
      ) : (
        <p className="px-3 py-2 text-2xs leading-relaxed text-muted-foreground">
          {source.excerpt
            ? `“${source.excerpt.trim()}”`
            : "The provider returned a link and no page text."}
        </p>
      )}

      {candidate ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-1.5">
          {stored ? (
            <span className="flex items-center gap-1 text-2xs text-primary">
              <Check className="size-3" />
              Stored as {stored.label}
              {stored.id ? (
                <Link
                  href={`/pumps/${stored.id}`}
                  className="underline hover:no-underline"
                >
                  open
                </Link>
              ) : null}
            </span>
          ) : candidate.blocked_reason ? (
            <span className="text-2xs text-muted-foreground" title={candidate.blocked_reason}>
              Cannot be stored: {candidate.blocked_reason}
            </span>
          ) : (
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={storing}
                onClick={() => onStore?.(candidate)}
              >
                {storing ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Save className="size-3" />
                )}
                {storing ? "Storing…" : "Store in database"}
              </Button>
              <span className="figure text-2xs text-muted-foreground">
                {candidate.field_count} field
                {candidate.field_count === 1 ? "" : "s"} with evidence
              </span>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
