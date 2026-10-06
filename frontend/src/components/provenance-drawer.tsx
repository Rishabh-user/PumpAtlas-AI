"use client";

import { useState } from "react";

import { ConfidenceChip } from "@/components/data/confidence";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { clientFetch } from "@/lib/api-client";
import { dateTime } from "@/lib/format";
import { fieldLabel, humanise } from "@/lib/labels";
import type { ProvenanceEntry, ProvenanceSummary } from "@/types/api";

const ENTITY_SCOPES = [
  { value: "pump_models", label: "Pump model" },
  { value: "technical_specs", label: "Technical" },
  { value: "commercial_specs", label: "Commercial" },
  { value: "dimensional_specs", label: "Dimensional" },
  { value: "delivery_specs", label: "Delivery" },
  { value: "operational_specs", label: "Operational" },
  { value: "administrative_specs", label: "Administrative" },
];

/**
 * "Where did this number come from?" — the answer, per field.
 *
 * Loads on demand because a mature record can carry hundreds of provenance rows.
 */
export function ProvenanceDrawer({
  pumpModelId,
  summary,
}: {
  pumpModelId: string;
  summary: ProvenanceSummary;
}) {
  const [scope, setScope] = useState("technical_specs");
  const [entries, setEntries] = useState<ProvenanceEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(nextScope: string) {
    setScope(nextScope);
    setLoading(true);
    setError(null);
    try {
      setEntries(
        await clientFetch<ProvenanceEntry[]>(
          "/pump-models/" + pumpModelId + "/provenance",
          {
            query: { entity_type: nextScope },
          },
        ),
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not load provenance",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Field provenance</CardTitle>
        <Select value={scope} onValueChange={(value) => void load(value)}>
          <SelectTrigger className="h-7 w-36" aria-label="Provenance scope">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ENTITY_SCOPES.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </CardHeader>

      <div className="grid grid-cols-2 divide-x divide-border border-b border-border sm:grid-cols-4">
        <Cell label="Tracked" value={summary.total_fields_with_provenance} />
        <Cell label="AI-derived" value={summary.ai_derived_fields} />
        <Cell
          label="AI share"
          value={
            summary.ai_share_pct === null
              ? "—"
              : summary.ai_share_pct.toFixed(0) + "%"
          }
        />
        <Cell label="Verified" value={summary.by_confidence.verified ?? 0} />
      </div>

      {entries === null ? (
        <div className="px-3 py-6 text-center">
          <Button
            variant="outline"
            onClick={() => void load(scope)}
            disabled={loading}
          >
            {loading ? "Loading…" : "Show field lineage"}
          </Button>
          <p className="mt-2 text-2xs text-muted-foreground">
            Every value, its source, the evidence quote and who approved it.
          </p>
        </div>
      ) : error ? (
        <div className="p-3">
          <ErrorState message={error} />
        </div>
      ) : entries.length === 0 ? (
        <EmptyState
          title="No provenance recorded for this scope"
          hint="Values written before provenance tracking, or a spec group with no data yet."
        />
      ) : (
        <ul className="max-h-96 divide-y divide-border overflow-y-auto">
          {entries.map((entry, index) => (
            <li
              key={entry.field_name + "-" + String(index)}
              className="px-3 py-2.5"
            >
              <div className="flex items-start justify-between gap-2.5">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-foreground">
                    {fieldLabel(entry.field_name)}
                  </p>
                  <p className="figure mt-0.5 text-muted-foreground">
                    {entry.value_text ?? "—"}
                    {entry.previous_value_text ? (
                      <span className="text-muted-foreground/60">
                        {" "}
                        (was {entry.previous_value_text})
                      </span>
                    ) : null}
                  </p>
                </div>
                <ConfidenceChip level={entry.confidence_level} />
              </div>

              {entry.evidence_quote ? (
                <blockquote className="mt-2 border-l-2 border-primary/40 pl-2 text-2xs italic leading-relaxed text-muted-foreground">
                  {entry.evidence_quote}
                </blockquote>
              ) : null}

              <dl className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[0.625rem] text-muted-foreground/80">
                <span>{humanise(entry.value_origin)}</span>
                {entry.model_used ? (
                  <span className="font-mono">{entry.model_used}</span>
                ) : null}
                {entry.original_value ? (
                  <span>
                    source: {entry.original_value}
                    {entry.original_unit ? " " + entry.original_unit : ""}
                  </span>
                ) : null}
                {entry.confidence_score !== null ? (
                  <span>
                    confidence {(entry.confidence_score * 100).toFixed(0)}%
                  </span>
                ) : null}
                <span className="font-mono">{dateTime(entry.created_at)}</span>
                {!entry.is_current ? (
                  <span className="text-sev-medium">superseded</span>
                ) : null}
              </dl>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Cell({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="px-3 py-2">
      <div className="label-xs">{label}</div>
      <div className="mt-0.5 font-mono text-base font-medium tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}
