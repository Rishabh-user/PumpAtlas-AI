"use client";

import { FillGaps, type FillGapsTarget } from "@/components/data/fill-gaps";
import type { Vendor } from "@/types/api";

/** The fields a web search can realistically answer about a supplier. */
const WANTED = ["website", "hq_city", "description"] as const;

const target: FillGapsTarget<Vendor> = {
  id: (vendor) => vendor.id,
  label: (vendor) => vendor.name,
  gaps: (vendor) =>
    WANTED.filter((field) => {
      const value = vendor[field as keyof Vendor];
      return value === null || value === undefined || value === "";
    }),
  enrichPath: (vendor) => `/vendors/${vendor.id}/enrich?max_results=6`,
  watchPath: (runId) => `/vendor-discovery/${runId}`,
  refetchPath: (vendor) => `/vendors/${vendor.id}`,
};

export function VendorFillGaps({ vendors }: { vendors: Vendor[] }) {
  return (
    <FillGaps
      items={vendors}
      target={target}
      noun="supplier"
      nounPlural="suppliers"
      description={
        "Reads the web for each supplier on this page that is missing a website, a " +
        "city or a description — one at a time, writing what it can quote onto that " +
        "record. Values arrive flagged unverified; confirm them on the record. An " +
        "existing value is never replaced silently: each run opens a new version and " +
        "keeps the last."
      }
    />
  );
}
