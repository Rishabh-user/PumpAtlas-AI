import { notFound, redirect } from "next/navigation";

import { ExternalLink } from "lucide-react";

import { ConfidenceChip } from "@/components/data/confidence";
import { Stat, StatStrip } from "@/components/data/stat";
import { ErrorState } from "@/components/data/states";
import { VendorDetailPanels } from "@/components/vendor-detail-panels";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EnrichPanel } from "@/components/vendors/enrich-panel";
import { ImportedRecord } from "@/components/vendors/imported-record";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { externalHref } from "@/lib/href";
import { ApiError, apiFetch, hasSession } from "@/lib/api";
import { dateOnly, num, ratioAsPct, text } from "@/lib/format";
import { humanise, vendorTierLabel } from "@/lib/labels";
import { loadShellContext } from "@/lib/session";
import type {
  ConfidenceLevel,
  ProvenanceSummary,
  QualityFlag,
  VendorContactDetails,
  VendorVersion,
} from "@/types/api";

export interface VendorProfileResponse {
  vendor: Record<string, unknown>;
  contacts: Record<string, unknown>[];
  product_lines: {
    pump_id: string;
    name: string;
    pump_type: string | null;
    applicable_standard: string | null;
    service_application: string | null;
    model_count: number;
  }[];
  open_flags: QualityFlag[];
  provenance_summary: ProvenanceSummary;
  /**
   * What the client's own documents state: the packages this supplier is approved for,
   * and the registration identifiers that name it independently of its trading name.
   * Empty arrays until migration 003 is applied.
   */
  approvals?: {
    project: string;
    package: string;
    approved_country: string | null;
    document_reference: string | null;
    status: string;
    expires_on: string | null;
  }[];
  identifiers?: { scheme: string; value: string }[];
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ vendorId: string }>;
}) {
  const { vendorId } = await params;
  try {
    const profile = await apiFetch<VendorProfileResponse>(
      `/vendors/${vendorId}/profile`,
      {
        revalidate: false,
      },
    );
    return { title: text(profile.vendor.name) };
  } catch {
    return { title: "Vendor" };
  }
}

export default async function VendorProfilePage({
  params,
}: {
  params: Promise<{ vendorId: string }>;
}) {
  if (!(await hasSession())) redirect("/login");
  const { user, counts, authFailed } = await loadShellContext();
  if (authFailed) redirect("/login");
  const { vendorId } = await params;

  let profile: VendorProfileResponse;
  try {
    profile = await apiFetch<VendorProfileResponse>(
      `/vendors/${vendorId}/profile`,
      {
        revalidate: false,
      },
    );
  } catch (caught) {
    if (caught instanceof ApiError) {
      if (caught.isAuthError) redirect("/login");
      if (caught.status === 404) notFound();
      return (
        <AppShell user={user} counts={counts}>
          <ErrorState message={caught.message} />
        </AppShell>
      );
    }
    throw caught;
  }

  // The version history is a second call, and a failure of it must not cost the page:
  // the profile is the point, the history is context beside it.
  let versions: VendorVersion[] = [];
  try {
    versions = await apiFetch<VendorVersion[]>(
      `/vendors/${vendorId}/versions`,
      {
        revalidate: false,
      },
    );
  } catch {
    versions = [];
  }

  // What the captured pages said by way of contact details. A second call, and a failure
  // of it must not cost the page.
  let contactDetails: VendorContactDetails = { emails: [], phones: [] };
  try {
    contactDetails = await apiFetch<VendorContactDetails>(
      `/vendors/${vendorId}/contact-details`,
      { revalidate: false },
    );
  } catch {
    contactDetails = { emails: [], phones: [] };
  }

  const vendor = profile.vendor;
  const totalModels = profile.product_lines.reduce(
    (sum, line) => sum + line.model_count,
    0,
  );
  // `extra` is untyped JSON, so read it defensively rather than asserting a shape.
  const extra =
    vendor.extra && typeof vendor.extra === "object" && !Array.isArray(vendor.extra)
      ? (vendor.extra as Record<string, unknown>)
      : null;
  const dataOwner =
    typeof extra?.data_owner === "string" ? extra.data_owner : "";

  return (
    <AppShell user={user} counts={counts}>
      <PageHeader
        crumbs={[
          { label: "Vendors", href: "/vendors" },
          { label: text(vendor.name) },
        ]}
        title={text(vendor.name)}
        lede={`${vendorTierLabel(String(vendor.vendor_tier ?? ""))}${
          vendor.hq_city ? ` · ${text(vendor.hq_city)}` : ""
        }${vendor.hq_country ? `, ${text(vendor.hq_country)}` : ""}`}
        meta={
          <>
            <ConfidenceChip
              level={vendor.confidence_level as ConfidenceLevel}
            />
            {/* Whose data this is, which `confidence_level` cannot say: that enum is
                platform-wide and its values grade how far a figure can be trusted,
                not who supplied it. */}
            {dataOwner ? <Badge variant="outline">{dataOwner}</Badge> : null}
            <Badge
              variant={
                vendor.approval_status === "approved" ? "success" : "warning"
              }
            >
              {humanise(String(vendor.approval_status ?? ""))}
            </Badge>
            <Badge
              variant={
                vendor.sanctions_status === "cleared"
                  ? "success"
                  : "destructive"
              }
            >
              Sanctions: {humanise(String(vendor.sanctions_status ?? ""))}
            </Badge>
            {vendor.is_shared_master ? (
              <Badge variant="secondary">Shared master</Badge>
            ) : null}
            <Badge variant="outline">
              {totalModels} pump model{totalModels === 1 ? "" : "s"}
            </Badge>
          </>
        }
        actions={
          vendor.website ? (
            <Button variant="outline" asChild>
              <a
                href={externalHref(String(vendor.website))}
                target="_blank"
                rel="noreferrer noopener"
              >
                <ExternalLink />
                Vendor website
              </a>
            </Button>
          ) : null
        }
      />

      <div className="space-y-4">
        {vendor.ai_summary ? (
          <Card>
            <CardHeader>
              <CardTitle>AI vendor briefing</CardTitle>
              <Badge variant="warning">Assistant layer</Badge>
            </CardHeader>
            <CardContent className="space-y-1.5">
              <p className="text-xs leading-relaxed text-foreground/85">
                {text(vendor.ai_summary)}
              </p>
              <p className="text-[0.625rem] text-muted-foreground">
                Generated from facts already held in the database on{" "}
                {dateOnly(vendor.ai_summary_generated_at as string | null)}. It
                is a reading aid, not a source.
              </p>
            </CardContent>
          </Card>
        ) : null}

        <StatStrip>
          <Stat label="Product lines" value={profile.product_lines.length} />
          <Stat label="Pump models" value={totalModels} />
          <Stat
            label="On-time delivery"
            value={ratioAsPct(vendor.on_time_delivery_pct as number | null)}
          />
          <Stat
            label="Units supplied"
            value={num(vendor.total_units_supplied as number | null, {
              decimals: 0,
            })}
          />
          <Stat
            label="Open flags"
            value={profile.open_flags.length}
            tone={profile.open_flags.length ? "warn" : "good"}
          />
        </StatStrip>

        {/* Before the enrichment panel on purpose: what a client's own signed
            document says outranks anything the platform went and found. */}
        <ImportedRecord extra={vendor.extra} />

        <EnrichPanel
          vendorId={vendorId}
          vendorName={text(vendor.name)}
          versions={versions}
        />

        <VendorDetailPanels
          profile={profile}
          vendorId={vendorId}
          contactDetails={contactDetails}
        />
      </div>
    </AppShell>
  );
}
