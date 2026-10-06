import { SeverityChip } from "@/components/data/confidence";
import { Stat, StatStrip } from "@/components/data/stat";
import { EmptyState, FieldRow } from "@/components/data/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { dateOnly, money, num, ratioAsPct, text } from "@/lib/format";
import { externalHref } from "@/lib/href";
import { fieldLabel, humanise } from "@/lib/labels";
import { ContactDetails } from "@/components/vendors/contact-details";
import { QualificationPanel } from "@/components/vendors/qualification-panel";
import type { VendorProfileResponse } from "@/app/vendors/[vendorId]/page";
import type { VendorContactDetails } from "@/types/api";

/** A JSON column rendered as the facts it holds, rather than as `[object Object]`. */
function jsonSummary(value: unknown): string {
  if (!value || typeof value !== "object") return text(value);
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return text(null);
  return entries
    .map(([key, held]) => `${fieldLabel(key)}: ${text(held)}`)
    .join(" \u00b7 ");
}

export function VendorDetailPanels({
  profile,
  vendorId,
  contactDetails,
}: {
  profile: VendorProfileResponse;
  vendorId: string;
  contactDetails: VendorContactDetails;
}) {
  const vendor = profile.vendor;

  // Facts the extraction found that have no column of their own. `store_candidate` keeps
  // them here rather than discarding them, so the page has to look here for them or they
  // are written and never seen.
  const discovery = ((vendor.extra as Record<string, unknown> | null)
    ?.discovery ?? {}) as Record<string, unknown>;
  const aliases = (vendor.aliases as string[] | null) ?? [];

  // `refused` is written by `store_candidate`: the field, what the page said, and why it
  // was not stored. `refused_at` and `refused_source_id` sit beside it and are not fields.
  const refused = Object.entries(
    (discovery.refused ?? {}) as Record<
      string,
      { value?: unknown; reason?: string } | null
    >,
  );

  return (
    <>
      {/* Who the company is.
       *
       * These fields were being written and never shown: a vendor could hold its
       * website, headquarters, category and legal entity name while the profile
       * displayed financial and governance panels full of dashes — which read as "the
       * web had nothing" when the record was the fullest thing on the screen. */}
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Company</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-x-6 md:grid-cols-2">
            <div>
              <FieldRow label="Legal entity">
                {text(discovery.legal_entity_name as string | null)}
              </FieldRow>
              <FieldRow label="Logo">
                {vendor.logo_url ? (
                  <a
                    href={externalHref(String(vendor.logo_url))}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-primary hover:underline"
                  >
                    {text(vendor.logo_url)}
                  </a>
                ) : (
                  text(null)
                )}
              </FieldRow>
              <FieldRow label="Also known as">
                {aliases.length ? aliases.join(", ") : text(null)}
              </FieldRow>
              <FieldRow label="Headquarters">
                {[vendor.hq_city, vendor.hq_country ?? vendor.country]
                  .filter(Boolean)
                  .join(", ") || text(null)}
              </FieldRow>
              <FieldRow label="Website">
                {vendor.website ? (
                  <a
                    href={externalHref(String(vendor.website))}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="font-mono text-primary hover:underline"
                  >
                    {String(vendor.website).replace(/^https?:\/\/(www\.)?/, "")}
                  </a>
                ) : (
                  text(null)
                )}
              </FieldRow>
            </div>
            <div>
              <FieldRow label="Category">
                {humanise(String(vendor.vendor_category ?? ""))}
              </FieldRow>
              <FieldRow label="Tier">
                {humanise(String(vendor.vendor_tier ?? ""))}
              </FieldRow>
              <FieldRow label="Certifications">
                {text(discovery.certifications as string | null)}
              </FieldRow>
              <FieldRow label="Notable references">
                {text(discovery.notable_references as string | null)}
              </FieldRow>
            </div>
          </div>

          {vendor.description ? (
            <p className="mt-2 border-t border-border pt-2 text-2xs leading-relaxed text-foreground/85">
              {String(vendor.description)}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Financial standing</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldRow label="Annual revenue">
              {money(vendor.annual_revenue_usd as number | null)}
            </FieldRow>
            <FieldRow label="Revenue year">
              {text(vendor.revenue_year)}
            </FieldRow>
            <FieldRow label="Employees">
              {num(vendor.employee_count as number | null, { decimals: 0 })}
            </FieldRow>
            <FieldRow label="Credit rating">
              {text(vendor.credit_rating)}
              {vendor.credit_rating_agency
                ? ` (${text(vendor.credit_rating_agency)})`
                : ""}
            </FieldRow>
            <FieldRow label="Bonding capacity">
              {money(vendor.bonding_capacity_usd as number | null)}
            </FieldRow>
            <FieldRow label="Performance bond">
              {text(vendor.can_provide_performance_bond)}
            </FieldRow>
            <FieldRow label="Advance payment guarantee">
              {text(vendor.can_provide_advance_payment_guarantee)}
            </FieldRow>
            <FieldRow label="Insurance cover">
              {money(vendor.insurance_coverage_usd as number | null)}
            </FieldRow>
            {/* Held in the table and never rendered until now. A D&B number is how a
              * finance team identifies a supplier independently of its trading name,
              * and the notes are where a reviewer wrote what the figures do not say. */}
            <FieldRow label="D&B number">
              {text(vendor.dun_bradstreet_number)}
            </FieldRow>
            <FieldRow label="Insurance detail">
              {jsonSummary(vendor.insurance_details)}
            </FieldRow>
            <FieldRow label="Financial notes">
              {text(vendor.financial_standing_notes)}
            </FieldRow>
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Governance</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldRow label="Approval expiry">
              {dateOnly(vendor.approval_expiry as string | null)}
            </FieldRow>
            <FieldRow label="Sanctions screened">
              {dateOnly(vendor.sanctions_screened_at as string | null)}
            </FieldRow>
            <FieldRow label="Sanctions notes">
              {text(vendor.sanctions_notes)}
            </FieldRow>
            <FieldRow label="Manufacturing countries">
              {text(vendor.manufacturing_countries)}
            </FieldRow>
            <FieldRow label="Product families">
              {text(vendor.product_families)}
            </FieldRow>
            <FieldRow label="FPSO experience">
              {text(vendor.fpso_offshore_experience)}
            </FieldRow>
            <FieldRow label="Verification">
              {humanise(String(vendor.verification_status ?? ""))}
            </FieldRow>
            <FieldRow label="Last verified">
              {dateOnly(vendor.last_verified_at as string | null)}
            </FieldRow>
            <FieldRow label="Geopolitical notes">
              {text(vendor.geopolitical_risk_notes)}
            </FieldRow>
            <FieldRow label="Profile completeness">
              {ratioAsPct(vendor.data_completeness_pct as number | null)}
            </FieldRow>

            {/* The decision itself, where the fields describing it already are. */}
            <QualificationPanel
              vendorId={vendorId}
              status={(vendor.approval_status as string | null) ?? null}
              expiry={(vendor.approval_expiry as string | null) ?? null}
              approvedBy={(vendor.approved_by_user_id as string | null) ?? null}
              claims={
                (discovery.supplier_claims as Record<
                  string,
                  { value?: unknown; quote?: string | null }
                > | null) ?? null
              }
            />
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Contacts ({profile.contacts.length})</CardTitle>
          </CardHeader>
          {profile.contacts.length === 0 ? (
            <div className="px-3 pb-3">
              <EmptyState
                title="No contacts recorded"
                hint="Authorized representatives and agents are captured here."
              />
              <ContactDetails vendorId={vendorId} details={contactDetails} />
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {profile.contacts.map((contact, index) => (
                <li key={String(contact.id ?? index)} className="px-3 py-2.5">
                  <p className="text-xs text-foreground">
                    {text(contact.full_name ?? contact.company_name)}
                  </p>
                  <p className="mt-0.5 text-[0.625rem] text-muted-foreground">
                    {contact.is_primary ? "Primary \u00b7 " : ""}
                    {humanise(String(contact.contact_role ?? ""))}
                    {contact.country ? ` \u00b7 ${text(contact.country)}` : ""}
                    {contact.territory
                      ? ` \u00b7 ${text(contact.territory)}`
                      : ""}
                  </p>
                  {contact.email ? (
                    <p className="mt-0.5 text-[0.625rem] text-primary">
                      {text(contact.email)}
                    </p>
                  ) : null}
                  {/* A contact recorded from a page is often a switchboard number and
                   * nothing else; without this line it rendered as a nameless row. */}
                  {contact.phone ? (
                    <p className="mt-0.5 font-mono text-[0.625rem] text-foreground">
                      {text(contact.phone)}
                    </p>
                  ) : null}
                  {/* Where it came from. Auto-recorded details are read from the
                   * company's own site, so they are as traceable as every other stored
                   * value — and a reader can see which ones a person chose. */}
                  {contact.origin === "ai_extraction" ? (
                    <p className="mt-0.5 text-[0.625rem] text-muted-foreground">
                      From the company website
                      {contact.captured_at
                        ? ` · captured ${dateOnly(contact.captured_at as string)}`
                        : ""}
                    </p>
                  ) : null}
                  {contact.agency_agreement_valid_until ? (
                    <p className="mt-0.5 text-[0.625rem] text-muted-foreground">
                      Agency valid until{" "}
                      {dateOnly(contact.agency_agreement_valid_until as string)}
                    </p>
                  ) : null}
                </li>
              ))}
              <li className="px-3 pb-2">
                <ContactDetails vendorId={vendorId} details={contactDetails} />
              </li>
            </ul>
          )}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Product lines ({profile.product_lines.length})</CardTitle>
        </CardHeader>
        {profile.product_lines.length === 0 ? (
          <EmptyState
            title="No pumps recorded for this vendor"
            hint="Ingest a catalogue or datasheet to populate the portfolio."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product line</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Standard</TableHead>
                <TableHead>Service</TableHead>
                <TableHead className="text-right">Models</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {profile.product_lines.map((line) => (
                <TableRow key={line.pump_id}>
                  <TableCell className="text-xs font-medium text-foreground">
                    {line.name}
                  </TableCell>
                  <TableCell className="text-xs">
                    {humanise(line.pump_type)}
                  </TableCell>
                  <TableCell className="text-xs">
                    {humanise(line.applicable_standard)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {line.service_application ?? "\u2014"}
                  </TableCell>
                  <TableCell className="figure text-right">
                    {line.model_count}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {profile.open_flags.length ? (
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Vendor-level data flags</CardTitle>
          </CardHeader>
          <ul className="divide-y divide-border">
            {profile.open_flags.map((flag) => (
              <li
                key={flag.id}
                className="flex items-start gap-2.5 px-3 py-2.5"
              >
                <SeverityChip severity={flag.severity} />
                <div>
                  <p className="text-xs text-foreground">{flag.message}</p>
                  <p className="mt-0.5 text-[0.625rem] text-muted-foreground">
                    {flag.field_name
                      ? `${fieldLabel(flag.field_name)} \u00b7 `
                      : ""}
                    {humanise(flag.flag_type)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {/* Values a page stated that the write gate refused - almost always for want of a
        * verbatim quote. They were being kept on the record and shown nowhere, so a
        * profile full of dashes read as "the web had nothing about this supplier" when
        * the truth was "the web said it and we would not write it down untraceably".
        * Shown here, with the reason, because that is a different and more useful fact. */}
      {refused.length ? (
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Found but not recorded ({refused.length})</CardTitle>
          </CardHeader>
          <div className="px-3 pb-3">
            <p className="text-[0.625rem] leading-relaxed text-muted-foreground">
              A page stated these and they were refused rather than stored untraceably.
              Recording one is a person&apos;s decision.
            </p>
            <ul className="mt-1.5 space-y-1">
              {refused.map(([field, entry]) => (
                <li key={field} className="text-2xs">
                  <span className="text-muted-foreground">{fieldLabel(field)}: </span>
                  <span className="text-foreground">{text(entry?.value)}</span>
                  {entry?.reason ? (
                    <span className="text-[0.625rem] text-muted-foreground">
                      {" \u2014 "}
                      {text(entry.reason)}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Data provenance</CardTitle>
        </CardHeader>
        <StatStrip className="rounded-none border-0 sm:grid-cols-4 lg:grid-cols-4">
          <Stat
            label="Fields tracked"
            value={profile.provenance_summary.total_fields_with_provenance}
          />
          <Stat
            label="AI-derived"
            value={profile.provenance_summary.ai_derived_fields}
          />
          <Stat
            label="AI share"
            value={
              profile.provenance_summary.ai_share_pct === null
                ? "\u2014"
                : `${profile.provenance_summary.ai_share_pct.toFixed(0)}%`
            }
          />
          <Stat
            label="Verified fields"
            value={profile.provenance_summary.by_confidence.verified ?? 0}
          />
        </StatStrip>
      </Card>
    </>
  );
}
