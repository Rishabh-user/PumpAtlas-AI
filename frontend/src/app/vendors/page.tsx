import { redirect } from "next/navigation";

import { ConfidenceChip } from "@/components/data/confidence";
import { Pager } from "@/components/data/pager";
import { RowLink } from "@/components/data/row-link";
import { EmptyState, ErrorState } from "@/components/data/states";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { AiSearch } from "@/components/discovery/ai-search";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { externalHref, hrefToString } from "@/lib/href";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { num, ratioAsPct } from "@/lib/format";
import { approvalLabel, humanise, vendorTierLabel } from "@/lib/labels";
import { loadShellContext } from "@/lib/session";
import type { Page, Vendor } from "@/types/api";

type Variant =
  "default" | "outline" | "secondary" | "destructive" | "success" | "warning";

const APPROVAL_VARIANT: Record<string, Variant> = {
  approved: "success",
  conditionally_approved: "warning",
  pending_qualification: "outline",
  under_review: "outline",
  not_approved: "destructive",
  suspended: "destructive",
  blacklisted: "destructive",
};

export const metadata = { title: "Vendors" };

/** Rows per page. Mirrored in the API call and the pager, so they cannot disagree. */
const PAGE_SIZE = 25;

const EM_DASH = "—";

/**
 * The columns here are the ones that carry data.
 *
 * It used to show OTD %, Units supplied and Complete %, which were empty for all 75
 * vendors in the database — those come from supplier questionnaires and the ingestion
 * path, not from web discovery, so a discovered supplier has none of them. Sanctions went
 * for a different reason: it was populated for every row and held one value,
 * "Not screened", so seventy-five identical badges said the same thing once. Both kinds
 * of column crowd out what is actually known.
 *
 * Measured before changing: category 21/75, product families 22/75, website 36/75,
 * HQ city 28/75, tier 6 distinct values. Those are the ones below. Everything dropped is
 * still on the vendor's own page, where a blank field is a prompt to fill it in rather
 * than a column of dashes.
 */
function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    // Not a parseable URL. Showing the raw value is more use than showing nothing.
    return url.replace(/^https?:\/\//, "").replace(/^www\./, "");
  }
}

export default async function VendorsPage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string;
    approval_status?: string;
    tenant_scope?: string;
    page?: string;
  }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");

  const { q, approval_status, tenant_scope, page } = await searchParams;

  // A platform administrator sees every tenancy, so an unscoped list interleaves the
  // shared-master catalogue with each client's own: 73 rows for 65 companies, with the
  // eight that exist in both appearing twice. The API defaults an administrator to the
  // shared-master catalogue; this mirrors that default so the control shows what is
  // actually being listed.
  // `loadShellContext` types `user` as nullable, so the flag is derived once here
  // rather than asserted at each of the four places that need it.
  const isPlatformAdmin = user?.is_platform_admin ?? false;
  const scope = tenant_scope ?? (isPlatformAdmin ? "shared" : "all");

  // Only a platform administrator can list tenants, and only they need the selector.
  let tenants: Array<{ id: string; name: string; slug: string }> = [];
  if (isPlatformAdmin) {
    try {
      const page = await apiFetch<
        Page<{ id: string; name: string; slug: string }>
      >("/tenants", { query: { limit: 100 }, revalidate: false });
      tenants = page.items;
    } catch {
      tenants = [];
    }
  }
  const currentPage = Math.max(1, Number(page ?? "1") || 1);
  const offset = (currentPage - 1) * PAGE_SIZE;

  // Paging must carry the filters with it, or page 2 of a search silently becomes page
  // 2 of everything.
  const pageHref = (next: number) =>
    hrefToString({
      pathname: "/vendors",
      query: {
        ...(q ? { q } : {}),
        ...(approval_status ? { approval_status } : {}),
        ...(tenant_scope ? { tenant_scope } : {}),
        ...(next > 1 ? { page: next } : {}),
      },
    });

  let vendors: Page<Vendor> | null = null;
  let error: string | null = null;
  try {
    vendors = await apiFetch<Page<Vendor>>("/vendors", {
      query: {
        q,
        approval_status,
        tenant_scope: scope,
        limit: PAGE_SIZE,
        offset,
      },
      revalidate: false,
    });
  } catch (caught) {
    if (caught instanceof ApiError && caught.isAuthError) redirect("/login");
    error = caught instanceof Error ? caught.message : "Unknown error";
  }

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        title="Vendors"
        lede="Manufacturers, packagers and distributors, with qualification status and delivery track record."
        actions={
          <>
            <AiSearch kind="vendor" />
            <form
              className="flex flex-wrap items-center gap-1.5"
              action="/vendors"
            >
              <Input
                type="search"
                name="q"
                defaultValue={q ?? ""}
                placeholder="Vendor name"
                aria-label="Search vendors by name"
                className="w-44"
              />
              <select
                name="approval_status"
                defaultValue={approval_status ?? ""}
                aria-label="Filter by qualification status"
                className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <option value="">Any status</option>
                {Object.keys(APPROVAL_VARIANT).map((status) => (
                  <option key={status} value={status}>
                    {approvalLabel(status)}
                  </option>
                ))}
              </select>
              {isPlatformAdmin ? (
                <select
                  name="tenant_scope"
                  defaultValue={scope}
                  aria-label="Which catalogue to list"
                  className="h-8 rounded-md border border-input bg-background px-2 text-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                >
                  <option value="shared">Shared master catalogue</option>
                  {tenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                  <option value="all">All catalogues (shows overlaps)</option>
                </select>
              ) : null}
              <Button type="submit" variant="outline">
                Apply
              </Button>
            </form>
          </>
        }
      />

      <div className="space-y-4">
        {error ? <ErrorState message={error} /> : null}

        {vendors ? (
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                {vendors.total.toLocaleString("en-GB")} vendors
              </CardTitle>
              {isPlatformAdmin ? (
                <span className="text-2xs text-muted-foreground">
                  {scope === "shared"
                    ? "shared master catalogue"
                    : scope === "all"
                      ? "every catalogue — a company held by a client and in shared master appears once per catalogue"
                      : (tenants.find((tenant) => tenant.id === scope)?.name ??
                        "one client catalogue")}
                </span>
              ) : null}
            </CardHeader>
            {vendors.items.length === 0 ? (
              <EmptyState
                title="No vendors match"
                hint="Run a vendor discovery search from the import queue to populate this list."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Vendor</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Tier</TableHead>
                    <TableHead>Product families</TableHead>
                    <TableHead>Website</TableHead>
                    <TableHead>Qualification</TableHead>
                    <TableHead>Confidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {vendors.items.map((vendor) => (
                    <TableRow key={vendor.id}>
                      <TableCell className="max-w-[16rem]">
                        <RowLink
                          href={"/vendors/" + vendor.id}
                          label={`Opening ${vendor.name}…`}
                          className="block truncate text-xs font-medium text-foreground transition-colors hover:text-primary"
                        >
                          {vendor.name}
                        </RowLink>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.625rem] text-muted-foreground">
                          <span className="font-mono">
                            {vendor.country ?? vendor.hq_country ?? EM_DASH}
                          </span>
                          {vendor.hq_city ? (
                            <span>{vendor.hq_city}</span>
                          ) : null}
                          {vendor.also_in_other_tenancies ? (
                            <span
                              className="text-muted-foreground/70"
                              title="The same company is recorded in another tenancy. A client's own record and the shared-master record are separate by design, so this is not a duplicate to merge."
                            >
                              also in {vendor.also_in_other_tenancies} other
                              tenancy
                            </span>
                          ) : null}
                          {vendor.is_shared_master ? (
                            <span>shared master</span>
                          ) : null}
                          {vendor.fpso_offshore_experience ? (
                            <span>FPSO</span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-foreground/80">
                        {vendor.vendor_category
                          ? humanise(vendor.vendor_category)
                          : EM_DASH}
                      </TableCell>
                      <TableCell className="text-xs text-foreground/80">
                        {vendorTierLabel(vendor.vendor_tier)}
                      </TableCell>
                      <TableCell className="max-w-[14rem]">
                        {vendor.product_families?.length ? (
                          <span className="block truncate text-2xs text-foreground/80">
                            {vendor.product_families.slice(0, 2).join(", ")}
                            {vendor.product_families.length > 2
                              ? ` +${vendor.product_families.length - 2}`
                              : ""}
                          </span>
                        ) : (
                          <span className="text-2xs text-muted-foreground">
                            {EM_DASH}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[11rem]">
                        {vendor.website ? (
                          <a
                            href={externalHref(vendor.website)}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="block truncate font-mono text-[0.625rem] text-primary hover:underline"
                          >
                            {hostOf(vendor.website)}
                          </a>
                        ) : (
                          <span className="text-2xs text-muted-foreground">
                            {EM_DASH}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            APPROVAL_VARIANT[vendor.approval_status ?? ""] ??
                            "outline"
                          }
                        >
                          {approvalLabel(vendor.approval_status)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <ConfidenceChip level={vendor.confidence_level} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
        ) : null}

        {vendors ? (
          <Pager
            total={vendors.total}
            offset={vendors.offset}
            limit={vendors.limit}
            prevHref={currentPage > 1 ? pageHref(currentPage - 1) : null}
            nextHref={
              offset + vendors.items.length < vendors.total
                ? pageHref(currentPage + 1)
                : null
            }
            noun="vendors"
          />
        ) : null}
      </div>
    </AppShell>
  );
}
