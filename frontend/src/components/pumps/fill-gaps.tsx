"use client";

import { FillGaps, type FillGapsTarget } from "@/components/data/fill-gaps";
import type { SearchResultRow } from "@/types/api";

/**
 * Filling gaps on pump models, which differs from vendors in two ways that matter.
 *
 * **Most records cannot be filled at all.** Of 160, only 67 name a product; the rest
 * are approved-suppliers lines ("ONGC KG-DWN-98/2 approved - Process Pumps"), resolver
 * placeholders and bare API 610 type codes. There is no datasheet for a procurement
 * category, so offering to look for one spends a search and a reading-model call per
 * page to come back with nothing. `model_kind` comes from the API, computed by the
 * same classifier the profile page uses.
 *
 * **Only technical specifications arrive.** Measured across ten runs: six models
 * gained technical specs and none gained commercial, delivery, dimensional,
 * operational or administrative. A manufacturer publishes duty curves and materials;
 * price, lead time and on-time delivery come from a quotation, and no amount of
 * reading will find them. So the gap this reports is the technical group alone -
 * claiming the others would make a working feature look broken.
 */

const target: FillGapsTarget<SearchResultRow> = {
  id: (row) => row.pump_model_id,
  label: (row) => `${row.vendor_name} ${row.model_code}`,
  blocked: (row) =>
    row.model_kind && row.model_kind !== "product"
      ? row.model_kind.replace("_", " ")
      : null,
  gaps: (row) => {
    // The duty figures the list itself shows as a dash. "Has a technical row at all"
    // was the first definition and it was far too coarse: a model with twelve fields
    // but no NPSHr, efficiency or speed counted as finished, so a page of records with
    // three visibly empty columns reported nothing to do.
    //
    // Capacity and head count the envelope as present - a family that states "flow to
    // 1,000 m3/h" has answered the question, even with no single rated figure.
    const envelope = row.duty_envelope ?? {};
    const hasEnvelope = (key: string, rated: number | null) =>
      rated !== null ||
      envelope[key]?.rated != null ||
      envelope[key]?.max != null ||
      envelope[key]?.min != null;

    const missing: string[] = [];
    if (!hasEnvelope("capacity", row.rated_capacity_m3h)) missing.push("capacity");
    if (!hasEnvelope("head", row.rated_head_m)) missing.push("head");
    if (row.npsh_required_m === null) missing.push("NPSHr");
    if (!hasEnvelope("efficiency", row.hydraulic_efficiency_pct)) {
      missing.push("efficiency");
    }
    // Deliberately not price or lead time. Ten measured runs returned neither, so
    // counting them would mark every record permanently unfinished.
    return missing;
  },
  enrichPath: (row) => `/pump-models/${row.pump_model_id}/enrich?max_results=8`,
  watchPath: (runId) => `/pump-discovery/${runId}`,
  refetchPath: (row) => `/pump-models/${row.pump_model_id}`,
};

export function PumpFillGaps({ rows }: { rows: SearchResultRow[] }) {
  return (
    <FillGaps
      items={rows}
      target={target}
      noun="model"
      nounPlural="models"
      description={
        "Hunts for the datasheet behind each model on this page that has no technical " +
        "specifications yet — one at a time, writing only what it can quote. Values " +
        "arrive flagged unverified; confirm them on the record, and an existing one " +
        "gains a new version rather than losing what it held. It will not find price, " +
        "lead time or weights: those come from a quotation, not a datasheet."
      }
    />
  );
}
