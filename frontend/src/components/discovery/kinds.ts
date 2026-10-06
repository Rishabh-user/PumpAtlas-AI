import type { LucideIcon } from "lucide-react";
import { Building2, Cog } from "lucide-react";

/**
 * The two discovery kinds, as the UI presents them.
 *
 * The API contract is identical for both — same paths under a different prefix, same run
 * and candidate shapes — so one component drives either. What differs is wording, the
 * example queries, and the icon.
 *
 * This config holds a `LucideIcon`, which is a React component and therefore cannot
 * cross a server-to-client boundary: passing it throws *"Functions cannot be passed
 * directly to Client Components"*. A server page names the kind by its slug and the
 * client component looks the config up here — the same shape `shell/nav-items.ts` uses
 * for the same reason.
 */
export type DiscoveryKindSlug = "vendor" | "pump";
export interface DiscoveryKindConfig {
  slug: DiscoveryKindSlug;
  /** API prefix; the backend mounts `/vendor-discovery` and `/pump-discovery`. */
  path: string;
  icon: LucideIcon;
  triggerLabel: string;
  title: string;
  blurb: string;
  /** Plural noun for counts: "3 suppliers found". */
  noun: string;
  nounPlural: string;
  emptyTitle: string;
  emptyHint: string;
}

export const VENDOR_KIND: DiscoveryKindConfig = {
  slug: "vendor",
  path: "/vendor-discovery",
  icon: Building2,
  triggerLabel: "AI vendor search",
  title: "AI vendor search",
  blurb:
    "Choose a duty and a country — or nothing at all — and a web search finds candidate companies. A reading model reads each page, decides whether it is an Oil & Gas pump supplier, and pulls out its legal entity, headquarters, standards and certifications. Nothing is stored until you approve it.",
  noun: "supplier",
  nounPlural: "suppliers",
  emptyTitle: "No Oil & Gas pump suppliers found yet",
  emptyHint:
    "The reading model rules out directories, marketplaces and pump companies that do not serve Oil & Gas duty. Try another duty, add a country, or sweep every country instead of one search.",
};

export const PUMP_KIND: DiscoveryKindConfig = {
  slug: "pump",
  path: "/pump-discovery",
  icon: Cog,
  triggerLabel: "AI pump search",
  title: "AI pump search",
  blurb:
    "A web search hunts for datasheets and performance curves; a reading model reads each one and pulls out the model's duty point, materials and commercial terms. Nothing is stored until you pick it.",
  noun: "pump model",
  nounPlural: "pump models",
  emptyTitle: "No Oil & Gas pump models found yet",
  emptyHint:
    "A page has to name both a manufacturer and a model designation to become a candidate — a category page about 'BB3 pumps' is not a product. Try a more specific duty, or name a manufacturer.",
};

const DISCOVERY_KINDS: Record<DiscoveryKindSlug, DiscoveryKindConfig> = {
  vendor: VENDOR_KIND,
  pump: PUMP_KIND,
};

export function discoveryKind(slug: DiscoveryKindSlug): DiscoveryKindConfig {
  return DISCOVERY_KINDS[slug];
}
