/**
 * Build a query-string URL. Plain module, usable from a server or a client component.
 *
 * It lives here rather than beside the pager for a reason that cost a broken page: every
 * export of a `"use client"` module is a client reference, so a server component calling
 * one gets *"Attempted to call hrefToString() from the server but hrefToString is on the
 * client"* at request time. `tsc` and `next build` both compile that happily — the rule
 * is enforced when the call actually runs. A helper shared across the boundary therefore
 * has to sit in a module with no directive at all.
 */

/** A `{pathname, query}` pair, as the list pages build them. */
export interface HrefParts {
  pathname: string;
  query: Record<string, string | number | string[] | undefined>;
}

export function hrefToString({ pathname, query }: HrefParts): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      for (const entry of value) params.append(key, entry);
    } else {
      params.set(key, String(value));
    }
  }
  // `URLSearchParams` encodes a space as `+`, which is the form-encoding convention
  // rather than the URL one. Passing `{pathname, query}` to `<Link>` produced `%20`, and
  // a search term is the value here most likely to contain a space — so it is normalised
  // rather than left to depend on how the receiving parser reads `+`.
  const search = params.toString().replace(/\+/g, "%20");
  return search ? `${pathname}?${search}` : pathname;
}

/**
 * A stored web address, made safe to put in an `href`.
 *
 * Five vendor records held `www.handolpumps.com` with no scheme, and a browser reads
 * that as a *relative* path — so the "Vendor website" button pointed at
 * `/vendors/www.handolpumps.com`, a link that looks right and goes nowhere. The write
 * gate now adds the scheme, but a record written before that, or by hand, still reaches
 * this page, and a link is the wrong place to discover it.
 *
 * Anything that is not plainly an http address comes back empty, so the caller renders
 * text rather than a link to somewhere unintended — `javascript:` included.
 */
export function externalHref(value: string | null | undefined): string {
  const address = (value ?? "").trim();
  if (!address) return "";
  if (/^https?:\/\//i.test(address)) return address;
  if (/^[a-z][a-z0-9+.-]*:/i.test(address)) return "";
  const host = address.split("/")[0] ?? "";
  if (!host.includes(".")) return "";
  return `https://${address.replace(/^\/+/, "")}`;
}
