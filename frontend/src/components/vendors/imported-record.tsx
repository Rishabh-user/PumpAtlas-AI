import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * What a client's own documents said about this vendor, as they said it.
 *
 * A vendor loaded from an approved supplier list is a different kind of record from
 * one the platform discovered: somebody's engineering authority put its name on a
 * document. That claim lives in `extra` rather than in a column, because the columns
 * are the platform's vocabulary and a client's spreadsheet is not - an SAP export
 * carries reconciliation accounts and MSME registrations that no pump catalogue has a
 * field for.
 *
 * Dropping those on import would have made the import a silent edit, so they are kept
 * verbatim, and this panel is where they become visible. It reads whatever is there
 * and renders nothing when there is nothing, so a vendor that came from anywhere else
 * is unaffected.
 */

/** `extra` is untyped JSON from the database; nothing here may assume a shape. */
function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

interface ApprovedPackage {
  project: string;
  package: string;
  country: string;
}

interface SourceRow {
  source_file: string;
  vendor_no: string;
  columns: Record<string, string>;
}

export function ImportedRecord({ extra }: { extra: unknown }) {
  const data = asRecord(extra);
  if (!data) return null;

  const owner = asText(data.data_owner);
  const tag = asText(data.confidence_tag);
  const documents = asArray(data.source_documents).map(asText).filter(Boolean);
  const packages: ApprovedPackage[] = asArray(data.approved_packages)
    .map(asRecord)
    .filter((row): row is Record<string, unknown> => row !== null)
    .map((row) => ({
      project: asText(row.project),
      package: asText(row.package),
      country: asText(row.country),
    }))
    .filter((row) => row.package);

  const sap = asRecord(data.sap);
  const vendorNumbers = asArray(sap?.vendor_numbers).map(asText).filter(Boolean);
  const companyCodes = asArray(sap?.company_codes).map(asText).filter(Boolean);
  const sourceRows: SourceRow[] = asArray(sap?.rows)
    .map(asRecord)
    .filter((row): row is Record<string, unknown> => row !== null)
    .map((row) => ({
      source_file: asText(row.source_file),
      vendor_no: asText(row.vendor_no),
      columns: Object.fromEntries(
        Object.entries(asRecord(row.columns) ?? {}).map(([key, value]) => [
          key,
          asText(value),
        ]),
      ),
    }));

  const contacts = asArray(data.contacts)
    .map(asRecord)
    .filter((row): row is Record<string, unknown> => row !== null);

  // Nothing imported, nothing to say.
  if (
    !owner &&
    !documents.length &&
    !packages.length &&
    !vendorNumbers.length &&
    !sourceRows.length
  ) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Imported record</CardTitle>
        {owner ? <Badge variant="success">{tag || owner}</Badge> : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {documents.length ? (
          <div>
            <p className="label-xs">Source documents</p>
            <ul className="mt-1 space-y-0.5">
              {documents.map((document) => (
                <li key={document} className="text-xs text-foreground/85">
                  {document}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {packages.length ? (
          <div>
            <p className="label-xs">Approved for</p>
            <div className="mt-1.5 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1 pr-3 font-medium">Project</th>
                    <th className="py-1 pr-3 font-medium">Equipment package</th>
                    <th className="py-1 font-medium">Country as written</th>
                  </tr>
                </thead>
                <tbody>
                  {packages.map((row, index) => (
                    <tr
                      key={`${row.project}-${row.package}-${index}`}
                      className="border-b border-border/50 last:border-0"
                    >
                      <td className="py-1 pr-3 text-foreground/85">{row.project}</td>
                      <td className="py-1 pr-3 text-foreground">{row.package}</td>
                      <td className="py-1 text-muted-foreground">{row.country}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {vendorNumbers.length || companyCodes.length ? (
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {vendorNumbers.length ? (
              <div>
                <p className="label-xs">Vendor numbers</p>
                <p className="mt-0.5 figure text-xs text-foreground">
                  {vendorNumbers.join(", ")}
                </p>
              </div>
            ) : null}
            {companyCodes.length ? (
              <div>
                <p className="label-xs">Company codes</p>
                <p className="mt-0.5 figure text-xs text-foreground">
                  {companyCodes.join(", ")}
                </p>
              </div>
            ) : null}
          </div>
        ) : null}

        {contacts.length ? (
          <div>
            <p className="label-xs">Contacts on file</p>
            <ul className="mt-1 space-y-0.5">
              {contacts.map((contact, index) => (
                <li key={index} className="text-xs text-foreground/85">
                  {[asText(contact.email), asText(contact.phone)]
                    .filter(Boolean)
                    .join(" · ")}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {/*
          Collapsed by default. It is the whole source row - thirty-odd columns of
          reconciliation accounts and registration numbers - which is worth keeping
          and not worth reading unless someone came looking for it.
        */}
        {sourceRows.map((row, index) => (
          <details
            key={`${row.source_file}-${row.vendor_no}-${index}`}
            className="rounded-md border border-border"
          >
            <summary className="cursor-pointer px-3 py-2 text-xs text-foreground/85">
              Every column as imported — {row.source_file}
              {row.vendor_no ? ` · vendor ${row.vendor_no}` : ""}
              <span className="ml-1.5 text-muted-foreground">
                ({Object.keys(row.columns).length} fields)
              </span>
            </summary>
            <div className="border-t border-border px-3 py-2">
              <table className="w-full text-xs">
                <tbody>
                  {Object.entries(row.columns).map(([column, value]) => (
                    <tr
                      key={column}
                      className="border-b border-border/40 last:border-0"
                    >
                      <td className="w-1/2 py-1 pr-3 align-top text-muted-foreground">
                        {column}
                      </td>
                      <td className="py-1 align-top text-foreground/90">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ))}
      </CardContent>
    </Card>
  );
}
