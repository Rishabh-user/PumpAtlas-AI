"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

import { isCurrencyCompanion, specValue } from "@/components/format-spec";
import { Badge } from "@/components/ui/badge";
import { fieldLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { ChatRecordGroup, ChatRecordHit } from "@/types/api";

/**
 * A held record, panel by panel, as the pump profile page shows it.
 *
 * The chat used to list a cited record as one line — its label and its head — which is
 * enough to know *which* record was cited and not enough to judge it. The same fields
 * the profile page shows are here, grouped and labelled identically, so a citation can
 * be checked where it is read instead of in another tab.
 *
 * Only recorded fields appear. A group holding nothing says so with its count rather
 * than a column of dashes, because "not recorded" is the useful fact and repeating it
 * twenty times is not.
 */
export function RecordPanels({
  record,
  defaultOpen = false,
}: {
  record: ChatRecordHit;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const populated = record.groups.filter((group) => group.fields.length > 0);
  const empty = record.groups.filter((group) => group.fields.length === 0);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-2">
        <span className="font-mono text-2xs text-muted-foreground">
          [{record.marker}]
        </span>
        <Link
          href={`/pumps/${record.pump_model_id}`}
          className="text-xs font-medium text-primary hover:underline"
        >
          {record.label || record.model_code || "pump model"}
          <ExternalLink className="ml-0.5 inline size-2.5" />
        </Link>
        {record.vendor_name ? (
          <span className="text-2xs text-muted-foreground">
            {record.vendor_name}
          </span>
        ) : null}
        <span className="figure ml-auto text-2xs text-muted-foreground">
          {record.recorded_count} recorded field
          {record.recorded_count === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="flex items-center gap-0.5 text-2xs text-primary hover:underline"
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="size-3" />
          ) : (
            <ChevronRight className="size-3" />
          )}
          {open ? "Hide fields" : "Show all fields"}
        </button>
      </div>

      {open ? (
        <div className="divide-y divide-border">
          {populated.map((group) => (
            <GroupPanel key={group.key} group={group} />
          ))}
          {record.notes.length ? (
            <div className="px-3 py-2">
              {record.notes.map((note, index) => (
                <p
                  key={index}
                  className="text-2xs leading-relaxed text-muted-foreground"
                >
                  {note}
                </p>
              ))}
            </div>
          ) : null}
          {empty.length ? (
            <div className="flex flex-wrap gap-1.5 px-3 py-2">
              {empty.map((group) => (
                <Badge
                  key={group.key}
                  variant="outline"
                  title={`${group.tracked} tracked fields, none recorded — ingest a datasheet or submit the data through the manual form`}
                >
                  {group.label}: not recorded
                </Badge>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5 px-3 py-2">
          {record.groups.map((group) => (
            <Badge
              key={group.key}
              variant={group.fields.length ? "success" : "outline"}
              className={cn(group.fields.length ? null : "opacity-70")}
            >
              {group.label} {group.recorded}/{group.tracked}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function GroupPanel({ group }: { group: ChatRecordGroup }) {
  // `specValue` pairs a money amount with its sibling currency column, so it needs the
  // whole group as a record — a figure shown without its currency is a procurement
  // hazard, and the currency row itself would then repeat the same fact.
  const values: Record<string, unknown> = Object.fromEntries(
    group.fields.map((field) => [field.field_name, field.value]),
  );

  return (
    <div className="px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label-xs text-foreground">{group.label}</span>
        <span className="figure text-2xs text-muted-foreground">
          {group.recorded}/{group.tracked}
        </span>
      </div>
      <dl className="mt-1 divide-y divide-border/60">
        {group.fields
          .filter((field) => !isCurrencyCompanion(field.field_name, values))
          .map((field) => (
            <div
              key={field.field_name}
              className="flex items-baseline justify-between gap-3 py-1"
            >
              <dt className="text-2xs text-muted-foreground">
                {fieldLabel(field.field_name)}
              </dt>
              <dd className="figure min-w-0 flex-1 text-right text-foreground">
                {specValue(field.field_name, field.value, values)}
              </dd>
            </div>
          ))}
      </dl>
    </div>
  );
}
