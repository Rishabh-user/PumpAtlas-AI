# Client documents → platform structure

What the seven documents in `Approved Vendor List` contain, where each fact lands in this
platform, and how to check that it got there.

Measured from the files themselves: **2,534 SAP rows across five exports (59 columns),
262 approval lines in the signed PDF, 71 in the Kikeh list.**

---

## The three document types mean three different things

| Document | Shape | What it states |
| --- | --- | --- |
| `20171-SPOG-14100-PM-LS-0002 D0 … Signed 05.05.2019.pdf` | package → vendors → countries, 13 pages | An engineering authority approved these companies for these equipment packages. The strongest statement in the set. |
| `Kikeh Key Packages Vendor List.xlsx` | 4 columns: NO., PACKAGES, APPROVED VENDORS, VENDOR LOCATION | The same kind of statement, per package, for a different project. |
| `G020 / G030 / G040 / G060 / G100 …XLSX` | 59-column SAP vendor master | The client has an *account* with this company. A cleaning contractor and a pump OEM look identical here. |

That difference is why the import creates pump records from the first two and never from
the third: an account number is not a statement that a company supplies pumps.

---

## Was the data already structured correctly?

**Partly.** Nothing was lost — every one of the 59 columns survives in
`vendors.extra.sap.rows[].columns` — but most of it was stored as JSON, which is a
holding pen rather than a destination. Three kinds of fact deserved real structure and
did not have it:

| Fact | Count | Was | Now |
| --- | --- | --- | --- |
| "Approved for package X on project Y" | 333 | `extra.approved_packages` (JSON) | `vendor_approvals` table |
| Registration identifiers (GST, PAN, MSME, SAP no.) | 664 | `extra.sap.identifiers` (JSON) | `vendor_identifiers` table |
| Contact details | 1,426 | `extra.contacts` (JSON) | `vendor_contacts` table |
| Street, state, legal name, account-opened date, purchasing block | ~2,500 rows | `extra.sap.rows` only | columns on `vendors` |

Migration **003** adds the two tables and six columns; migration **002** (already written,
still unapplied) adds the provenance columns that let contacts move.

---

## Column by column

### The signed list and the Kikeh list

| In the document | In the platform |
| --- | --- |
| Package / "PACKAGES" | `vendor_approvals.package`, and `pumps.name` where the package names a pump |
| Approved vendor | `vendors.name`, matched on the normalised name within the client's tenancy |
| Country / "VENDOR LOCATION" | `vendor_approvals.approved_country` **verbatim** ("UK / Brazil / India"), and `vendors.country` as ISO-2 where one country is named |
| Project (from the document) | `vendor_approvals.project` |
| Document number | `vendor_approvals.document_reference`, plus a `sources` row for citation |

### The SAP vendor master

Of 59 columns, **17 are empty on all 2,534 rows** (Aadhar, RC, RIB, NIS, TIN, NIF, Excise,
CST, Service Tax, Postl Code, Ariba Id, deletion flags…). They are carried in `extra` and
given no column: a column populated zero times is not a field.

| SAP column | Fill | In the platform |
| --- | --- | --- |
| Name 1 | 100% | `vendors.name` |
| Name 2 / Name 3 | 100% / 18% | `vendors.aliases`, and `vendors.legal_entity_name` where it differs from Name 1 |
| Vendor (account no.) | 100% | `vendor_identifiers` scheme `sap_vendor_no` |
| Country Key | 100% | `vendors.hq_country` (ISO-2), raw text kept in `extra.country_as_written` |
| Region / Region (State, Province, County) | 100% | `vendors.state_region` |
| City | 86% | `vendors.hq_city` |
| Street 2 … Street 5, Street | 84% → 5% | `vendors.address_line`, joined in printing order |
| E-Mail Address | 88% | `vendor_contacts.email` |
| Telephone | 73% | `vendor_contacts.phone` |
| Vendor Cr. Date | 100% | `vendors.client_since` |
| GST Number | 39% | `vendor_identifiers` scheme `gst` |
| Permanent account number (PAN) | 43% | `vendor_identifiers` scheme `pan` |
| MSME Number | 4% | `vendor_identifiers` scheme `msme` |
| VAT Registration No. | 1% | `vendor_identifiers` scheme `vat` (the nine all-zero values are rejected) |
| Centrally imposed purchasing block | 2% (50 rows) | `vendors.is_purchasing_blocked` + `purchasing_block_note` |
| CoCd / Company Code / POrg / Purchasing Organization | 100% | `extra.sap.company_codes` — which client entity buys, not a fact about the supplier |
| Purchase order currency, Vendor Classification for GST | 100% | `extra.sap.identifiers` — a payment default and a tax treatment, not identity |
| **Name of bank, Bank Account, Bank Key** | 27% | **Deliberately not structured.** Payment instructions for 691 rows; this platform has no use for them and holding them is a liability. They remain in `extra` and should be purged. |

---

## How to verify it

### 1. Reconcile the documents against the database

```bash
cd backend
python -m scripts.verify_client_data --dir "../../OneDrive_2026-09-21/Approved Vendor List"
```

Re-reads every document from disk — a verification that trusts the import is not a
verification — and answers four questions: did every company reach the database, did the
facts reach it, where do those facts live, and is there anything in the database that no
document mentions.

Current result:

```
document                                              rows  companies  in db  absent
20171-SPOG-14100-PM-LS-0002 D0 Approved Suppliers Li   262        197    197       0
G020-SPE_EXPORT_20260915_133135.XLSX                   433        308    308       0
G030_SPOGM_EXPORT_20260914_153000.XLSX                 263        153    153       0
G040-EXPORT_20260914_152630.XLSX                       531        496    496       0
G060_SPBAG_EXPORT_20260914_152902.XLSX                 764        258    258       0
G100-EPC_EXPORT_20260914_152809.XLSX                   543        513    513       0
Kikeh Key Packages Vendor List.xlsx                     71         55     55       0

in the database but in no document: 0
```

Every company in every document is held, and nothing was invented. Useful flags:
`--missing` names anything absent, `--vendor ABB` traces one company from document line to
stored record.

### 2. Trace one company end to end

```bash
python -m scripts.verify_client_data --dir "..." --vendor "SULZER"
```

Prints each document row that mentions it, what is stored, and what the structuring would
write — so a disagreement is visible at the field rather than as a count.

### 3. On screen

Open the vendor and read the **Approved to supply** panel: package, project, the countries
as the document wrote them, and the document number. The Company panel carries the
identifiers. Both are empty until migration 003 is applied.

### 4. Over the API

```bash
curl .../api/v1/vendors/{id}/profile -H 'X-API-Key: pa_...' | jq '.approvals, .identifiers'
```

---

## To make it live

```bash
# 1. the schema, as the owner (the application role has no DDL rights by design)
python scripts/apply_schema.py --url "postgresql://OWNER:...@HOST/DB?sslmode=require" \
    --file db/migrations/002_vendor_contact_provenance.sql
python scripts/apply_schema.py --url "postgresql://OWNER:...@HOST/DB?sslmode=require" \
    --file db/migrations/003_client_vendor_structure.sql

# 2. move what is already imported out of JSON (dry run first)
cd backend
python -m scripts.structure_client_data
python -m scripts.structure_client_data --commit

# 3. check it landed
python -m scripts.verify_client_data --dir "../../OneDrive_2026-09-21/Approved Vendor List"
```

Nothing re-reads a document or calls an AI provider: step 2 moves facts that are already
in the database. `extra` is left intact afterwards — it holds the verbatim source rows,
which are the evidence behind every structured value.

The application runs correctly before, during and after: the new columns are mapped
`deferred` so an un-migrated database still serves every page, and every new read is
guarded by a catalogue check that logs what to apply.
