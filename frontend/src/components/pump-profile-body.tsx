import Link from "next/link";

import { ConfidenceChip } from "@/components/data/confidence";
import { EmptyState, FieldRow } from "@/components/data/states";
import { SpecPanelEditor } from "@/components/pumps/spec-panel-editor";
import { isCurrencyCompanion, specValue } from "@/components/format-spec";
import { ProvenanceDrawer } from "@/components/provenance-drawer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { bytes, dateOnly, num, ratioAsPct } from "@/lib/format";
import { fieldLabel, humanise } from "@/lib/labels";
import type { PumpProfile } from "@/types/api";

const SPEC_GROUP_LABELS: Record<string, string> = {
  technical: "Technical",
  commercial: "Commercial",
  dimensional: "Weights & dimensions",
  delivery: "Delivery",
  operational: "Operational track record",
  administrative: "Administrative & compliance",
};

/**
 * Fields that state a range rather than a duty point, shown only when populated.
 *
 * A model family covers an envelope - "flow to 1,000 m3/h, head to 150 m" - and has no
 * single rated figure until a size is chosen. 56 of 78 records hold a maximum capacity
 * and 6 hold a rated one, so the panel that showed only the rated field reported
 * "Not recorded" over data the record was holding.
 */
const ENVELOPE_FALLBACKS = new Set(["max_capacity_m3h", "max_head_m"]);

/** The fields a reviewer looks at first. Everything else is available under the fold. */
const HEADLINE_FIELDS: Record<string, string[]> = {
  technical: [
    // Both the rated point and the envelope. A model sold in 45 sizes has no single
    // rated capacity - its datasheet states "flow to 1,000 m3/h" - so showing only
    // `rated_capacity_m3h` printed "Not recorded" over a record that holds the answer.
    "rated_capacity_m3h",
    "max_capacity_m3h",
    "rated_head_m",
    "max_head_m",
    "npsh_required_m",
    "hydraulic_efficiency_pct",
    "rated_power_kw",
    "rated_speed_rpm",
    "material_class",
    "seal_system_type",
    "seal_piping_plan",
    "area_classification",
    "casing_design_pressure_barg",
    "api_610_type_code",
    "nace_mr0175_compliant",
    "marine_class_society",
  ],
  commercial: [
    "base_price_amount",
    "base_price_currency",
    "incoterm",
    "payment_terms",
    "warranty_months",
    "lifecycle_cost_usd",
    "price_escalation_formula",
    "local_content_pct",
  ],
  dimensional: [
    "dry_weight_kg",
    "operating_weight_kg",
    "shipping_weight_kg",
    "max_maintenance_lift_weight_kg",
    "footprint_area_m2",
    "baseplate_length_mm",
    "baseplate_width_mm",
    "lifting_points_count",
    "fpso_module_space_envelope",
  ],
  delivery: [
    "standard_lead_time_weeks",
    "expedited_lead_time_weeks",
    "expedite_premium_pct",
    "primary_manufacturing_country",
    "country_of_origin",
    "fat_duration_days",
    "historical_on_time_delivery_pct",
    "export_control_classification",
  ],
  operational: [
    "units_supplied",
    "units_installed_operating",
    "mtbf_hours",
    "fpso_experience",
    "fpso_units_supplied",
    "nearest_service_center",
    "post_warranty_spares_years",
    "qaqc_certifications",
  ],
  administrative: [
    "legal_entity_name",
    "registration_number",
    "registration_country",
    "authorized_representative_name",
    "local_agent_name",
    "esg_rating",
    "iso_27001_certified",
    "verification_method",
  ],
};

/**
 * Attributes held on the pump itself rather than in a versioned spec table.
 *
 * These were being stored and never shown. A candidate accepted from the AI review
 * queue writes its pump-level values — type, standard, service, fluids — onto the
 * `pumps` row, while the six panels below read only the spec tables, so a record could
 * hold a service application and handled fluids and still show "Not recorded"
 * everywhere. They belong to the pump family, shared by every model variant under it,
 * which is why they are a separate card and not folded into Technical.
 *
 * Prose (`description`, `ai_summary`) is rendered underneath instead of as a row,
 * because a paragraph in a right-aligned value column is unreadable.
 */
const PUMP_ATTRIBUTE_FIELDS = [
  "product_family",
  "pump_type",
  "pump_type_raw",
  "applicable_standard",
  "standard_edition",
  "additional_standards",
  "service_application",
  "handled_fluids",
  "is_discontinued",
] as const;

const PUMP_PROSE_FIELDS = ["description", "ai_summary"] as const;

/** Where the generic humaniser reads awkwardly ("Is discontinued"). */
const ATTRIBUTE_LABELS: Record<string, string> = {
  is_discontinued: "Discontinued",
  pump_type_raw: "Pump type, as written",
};

/** Model-level identity beyond the model code already in the page title. */
const MODEL_ATTRIBUTE_FIELDS = [
  "size_designation",
  "frame_size",
  "stages",
  "orientation",
  "generation",
  "tag_number",
  "project_reference",
] as const;

/**
 * Whether this value wants a line of its own.
 *
 * A duty point is three characters and belongs on the right of its label. A service
 * list is sixty and does not: squeezed into the value column it wrapped into a ragged
 * right-aligned block, crushed the label beside it into a stack of single letters,
 * and - before `FieldRow` was taught to shrink - ran clean out of the card into the
 * panel next door.
 */
function wantsOwnLine(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 2;
  return typeof value === "string" && value.length > 32;
}

function present(record: Record<string, unknown>, field: string): boolean {
  const value = record[field];
  return (
    value !== null &&
    value !== undefined &&
    value !== "" &&
    !(Array.isArray(value) && value.length === 0)
  );
}

function PumpAttributes({
  pump,
  pumpModel,
}: {
  pump: Record<string, unknown>;
  pumpModel: Record<string, unknown>;
}) {
  const rows: Array<[string, Record<string, unknown>]> = [
    ...MODEL_ATTRIBUTE_FIELDS.filter((field) => present(pumpModel, field)).map(
      (field) => [field, pumpModel] as [string, Record<string, unknown>],
    ),
    ...PUMP_ATTRIBUTE_FIELDS.filter((field) => present(pump, field)).map(
      (field) => [field, pump] as [string, Record<string, unknown>],
    ),
  ];
  const prose = PUMP_PROSE_FIELDS.filter((field) => present(pump, field));

  // No card at all when there is nothing: another "Not recorded" box would say less
  // than the six that already do.
  if (!rows.length && !prose.length) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pump attributes</CardTitle>
        <span className="figure text-muted-foreground">
          {rows.length + prose.length}
        </span>
      </CardHeader>
      <CardContent>
        {rows.map(([field, record]) => (
          <FieldRow
            key={field}
            label={ATTRIBUTE_LABELS[field] ?? fieldLabel(field)}
            stacked={wantsOwnLine(record[field])}
          >
            {specValue(field, record[field], record)}
          </FieldRow>
        ))}
        {prose.map((field) => (
          <div key={field} className="mt-2 border-t border-border pt-2">
            <span className="label-xs">{fieldLabel(field)}</span>
            <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
              {String(pump[field])}
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SpecPanels({
  specs,
  specFields,
  coverage,
  pump,
  pumpModel,
  pumpModelId,
}: {
  specs: PumpProfile["specs"];
  specFields: PumpProfile["spec_fields"];
  coverage: PumpProfile["spec_coverage"];
  pump: Record<string, unknown>;
  pumpModel: Record<string, unknown>;
  pumpModelId: string;
}) {
  return (
    // `[&>*]:min-w-0` because a grid item's default `min-width: auto` lets a card
    // overflow its own column rather than constrain what is inside it. That is how
    // "Mo" from the Commercial panel ended up rendered inside the Technical one.
    <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
      <PumpAttributes pump={pump} pumpModel={pumpModel} />
      {Object.entries(SPEC_GROUP_LABELS).map(([group, label]) => {
        const spec = specs[group];
        // Only the columns that are pump data. Filtering on "not null" alone listed
        // `id`, `created_at`, `pump_model_id`, `version` and `source_id` among the
        // specifications and counted them towards the total it advertised.
        const real = new Set(specFields[group] ?? []);
        const populated = spec
          ? Object.entries(spec).filter(
              ([field, value]) =>
                real.has(field) &&
                value !== null &&
                value !== "" &&
                !isCurrencyCompanion(field, spec),
            )
          : [];
        const tracked = coverage[group]?.tracked ?? 0;
        return (
          <Card key={group}>
            <CardHeader>
              <CardTitle>{label}</CardTitle>
              {spec && tracked ? (
                // "16 / 144", not "31". One number says nothing about how much of the
                // group is still open, and the old one counted bookkeeping.
                <span className="figure text-muted-foreground">
                  {populated.length}
                  <span className="opacity-60"> / {tracked}</span>
                </span>
              ) : null}
            </CardHeader>
            {!spec ? (
              <>
                <EmptyState
                  title="Not recorded"
                  hint={
                    group === "technical"
                      ? "Find the datasheet from the web, or type the values in."
                      : "A datasheet will not carry these — they come from a quotation."
                  }
                />
                <SpecPanelEditor
                  pumpModelId={pumpModelId}
                  group={group}
                  groupLabel={label}
                  headlineFields={HEADLINE_FIELDS[group] ?? []}
                  current={null}
                  empty
                />
              </>
            ) : (
              <CardContent>
                {(HEADLINE_FIELDS[group] ?? [])
                  .filter((field) => !isCurrencyCompanion(field, spec))
                  // An envelope field earns its row only when it holds something.
                  // Otherwise a record with neither would show "Rated capacity —"
                  // and "Max capacity —" where one dash said it already.
                  .filter(
                    (field) =>
                      !ENVELOPE_FALLBACKS.has(field) ||
                      (spec[field] !== null && spec[field] !== undefined),
                  )
                  .map((field) => (
                    <FieldRow
                      key={field}
                      label={fieldLabel(field)}
                      stacked={wantsOwnLine(spec[field])}
                    >
                      {specValue(field, spec[field], spec)}
                    </FieldRow>
                  ))}
                {/* A details element, not a Collapsible: this panel renders on the
                    server and the toggle needs no JavaScript. */}
                <details className="mt-2 border-t border-border pt-2">
                  <summary className="cursor-pointer text-2xs text-primary">
                    All {populated.length} recorded field
                    {populated.length === 1 ? "" : "s"}
                  </summary>
                  <div className="mt-1">
                    {populated.map(([field, value]) => (
                      <FieldRow
                        key={field}
                        label={fieldLabel(field)}
                        stacked={wantsOwnLine(value)}
                      >
                        {specValue(field, value, spec)}
                      </FieldRow>
                    ))}
                  </div>
                </details>
              </CardContent>
            )}
            {spec ? (
              <SpecPanelEditor
                pumpModelId={pumpModelId}
                group={group}
                groupLabel={label}
                headlineFields={HEADLINE_FIELDS[group] ?? []}
                current={spec}
              />
            ) : null}
          </Card>
        );
      })}
    </div>
  );
}

function SourceList({ sources }: { sources: PumpProfile["sources"] }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Sources ({sources.length})</CardTitle>
      </CardHeader>
      {sources.length === 0 ? (
        <EmptyState title="No sources linked to this record" />
      ) : (
        <ul className="divide-y divide-border">
          {sources.map((source) => (
            <li key={source.id} className="px-3 py-2.5">
              <div className="flex items-start justify-between gap-2.5">
                <div className="min-w-0">
                  <p className="truncate text-xs text-foreground">
                    {source.title ?? source.source_url}
                  </p>
                  <p className="mt-0.5 text-[0.625rem] text-muted-foreground">
                    {humanise(source.source_type)} · captured{" "}
                    {dateOnly(source.captured_at)}
                    {source.is_authoritative ? " · authoritative" : ""}
                  </p>
                </div>
                <ConfidenceChip level={source.confidence_level} />
              </div>
              {source.source_url ? (
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-1 block truncate font-mono text-[0.625rem] text-primary hover:underline"
                >
                  {source.source_url}
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function DocumentTable({ documents }: { documents: PumpProfile["documents"] }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Documents ({documents.length})</CardTitle>
      </CardHeader>
      {documents.length === 0 ? (
        <EmptyState title="No documents attached" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead className="text-right">Pages</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents.map((document) => (
              <TableRow key={document.id}>
                <TableCell className="max-w-[16rem] truncate text-xs text-foreground">
                  {document.filename}
                </TableCell>
                <TableCell className="text-xs text-foreground/80">
                  {humanise(document.document_kind)}
                </TableCell>
                <TableCell className="figure text-right">
                  {bytes(document.size_bytes)}
                </TableCell>
                <TableCell className="figure text-right">
                  {document.page_count ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}

function SimilarTable({ similar }: { similar: PumpProfile["similar"] }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Similar duty points</CardTitle>
      </CardHeader>
      {similar.length === 0 ? (
        <EmptyState
          title="No comparable pumps found"
          hint="Similarity matching needs a recorded capacity and head."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Duty</TableHead>
              <TableHead className="text-right">Match</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {similar.map((row) => (
              <TableRow key={row.pump_model_id}>
                <TableCell>
                  <Link
                    href={"/pumps/" + row.pump_model_id}
                    className="font-mono text-xs text-foreground transition-colors hover:text-primary"
                  >
                    {row.model_code}
                  </Link>
                  <div className="text-[0.625rem] text-muted-foreground">
                    {row.vendor_name}
                  </div>
                </TableCell>
                <TableCell className="figure text-right">
                  {num(row.rated_capacity_m3h, { unit: "m3/h" })}
                  <div className="text-muted-foreground">
                    {num(row.rated_head_m, { unit: "m" })}
                  </div>
                </TableCell>
                <TableCell className="figure text-right">
                  {row.similarity === null || row.similarity === undefined
                    ? "—"
                    : ratioAsPct(row.similarity)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}

export function PumpProfileBody({
  profile,
  pumpModelId,
}: {
  profile: PumpProfile;
  pumpModelId: string;
}) {
  return (
    <>
      <SpecPanels
        pumpModelId={pumpModelId}
        specs={profile.specs}
        specFields={profile.spec_fields ?? {}}
        coverage={profile.spec_coverage ?? {}}
        pump={profile.pump}
        pumpModel={profile.pump_model}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <ProvenanceDrawer
          pumpModelId={pumpModelId}
          summary={profile.provenance_summary}
        />
        <SourceList sources={profile.sources} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <DocumentTable documents={profile.documents} />
        <SimilarTable similar={profile.similar} />
      </div>
    </>
  );
}
