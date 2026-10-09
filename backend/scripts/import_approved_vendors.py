"""Load a client's approved vendor lists into their own tenancy.

Three kinds of document, which mean three different things, and the difference is the
point of this script:

* **A signed approved suppliers list** (the ONGC KG-DWN-98/2 PDF). An engineering
  authority has stated that these vendors may be used for these equipment packages.
  That is a verified fact about the vendor's standing on that project.
* **A project package list** (Kikeh). The same kind of statement, per package.
* **An SAP vendor master export.** This says only that the client has an account with
  the company. A cleaning contractor and a pump OEM look identical in it.

So the first two produce pump records - a vendor approved for "Sea Water Lift Pump" gets
a pump the catalogue can find and cite - and the third does not. Creating a pump record
for a law firm because it appears in a vendor master would be inventing equipment that
does not exist, which is the one thing this platform must never do.

Everything lands under the client's own tenant, never shared master. An approved vendor
list is commercially sensitive: it tells a competitor who a client will buy from. Row
level security keeps it to the tenancy that owns it.

Provenance is what makes the result answerable. Every row carries a `Source` naming the
document it came from and a `SourceType` - `pdf` or `spreadsheet` - which is what
separates it from `web_page` and `parallel_search` in an answer. Ask the assistant a
question and a record from here cites as [R1] with `confidence_level = verified`, while
a web finding stays [W1] and `ai_extracted`.

Usage, dry run first because it is the safer default::

    python scripts/import_approved_vendors.py --dir "../Approved Vendor List"
    python scripts/import_approved_vendors.py --dir "../Approved Vendor List" --commit

Re-running is safe. Vendors match on normalised name within the tenancy, pumps on
(vendor, package), so a second run updates rather than duplicates.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import tenant_session  # noqa: E402
from app.models.enums import (  # noqa: E402
    ConfidenceLevel,
    IngestionStatus,
    PumpType,
    SourceType,
    TenantPlan,
    TenantStatus,
    VendorApprovalStatus,
    VendorTier,
    VerificationStatus,
)
from app.models.pump import Pump, PumpModel  # noqa: E402
from app.models.source import ImportBatch, Source  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.vendor import Vendor  # noqa: E402
from app.services import client_records  # noqa: E402
from app.services.indexing import reindex_pump_model  # noqa: E402

TENANT_SLUG = "sp-energy"
TENANT_NAME = "SP Energy"

#: Stamped on every record, every source and every import batch this script writes.
#:
#: Asked for as "Confidence: SP Energy", and it is deliberately *not* a
#: `ConfidenceLevel`. That enum is a platform-wide PostgreSQL type owned by the schema
#: owner, and its values say how much a figure can be trusted - verified, vendor
#: declared, AI extracted. "SP Energy" answers a different question: whose data this
#: is. Adding a client's name to a shared enum would put it in every other client's
#: schema and would still not mean "confidence". It is carried as provenance instead,
#: which is the field that actually means this, and needs no DDL.
SOURCE_TAG = "SP Energy"

#: How many companies to write per transaction.
#:
#: The first run held sixteen hundred inserts open in one transaction for about seven
#: minutes and the hosted PostgreSQL closed the connection underneath it - the whole
#: import rolled back at row 1,400-odd. Committing in batches keeps any single
#: transaction under a minute, and because the script matches on normalised name a
#: re-run after a failure resumes rather than duplicating.
BATCH_SIZE = 200

# Company-form words carry no identity: "KSB SE & Co. KGaA" and "KSB" are one company.
_FORMS = (
    r"pte|pvt|private|ltd|limited|llc|inc|corp|corporation|co|company|gmbh|sdn|bhd|"
    r"bv|b\.v|srl|s\.p\.a|spa|sa|as|a/s|ag|se|kgaa|plc|group|holdings|international|"
    r"intl|aktiengesellschaft"
)


#: What the documents call places, against what ISO 3166 calls them. A signed list
#: written by engineers says "USA", "UK" and "Dubai"; the column takes two letters.
_COUNTRY_ALIASES = {
    "usa": "US", "u.s.a": "US", "us": "US", "uk": "GB", "england": "GB",
    "scotland": "GB", "great britain": "GB", "netherland": "NL", "holland": "NL",
    "korea": "KR", "south korea": "KR", "uae": "AE", "dubai": "AE",
    "abu dhabi": "AE", "vietnam": "VN", "viet nam": "VN", "russia": "RU",
    "taiwan": "TW", "czech republic": "CZ", "batam": "ID", "switzerland": "CH",
}


def to_iso2(text: str | None) -> tuple[str | None, list[str]]:
    """A country cell as ISO codes: the first one, and every one it names.

    The lists carry "UK / Brazil / India" in a single cell - where a vendor builds, not
    a typo. The first becomes the headquarters, all of them the manufacturing
    countries, and the original string is kept in `extra` because a mapping that drops
    something should still be able to show what it dropped.
    """
    from app.core.countries import COUNTRIES

    reverse = {name.lower(): code for code, name in COUNTRIES.items()}
    codes: list[str] = []
    for part in re.split(r"[/,]|\band\b", text or ""):
        key = " ".join(part.split()).lower().strip(" .")
        if not key:
            continue
        code = _COUNTRY_ALIASES.get(key) or reverse.get(key)
        if code and code not in codes:
            codes.append(code)
    return (codes[0] if codes else None), codes


def normalise(name: str) -> str:
    """A name reduced to what identifies the company.

    Parenthetical qualifiers go too - "Flowserve (Austria) GmbH" is Flowserve, and the
    country is carried in its own column rather than inside the name.
    """
    text = (name or "").strip().lower()
    text = re.sub(r"[‘’'`]", "", text)
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(rf"\b(?:{_FORMS})\b\.?", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


# === Parsing =================================================================

#: Every country named in the signed list. pypdf gives no column geometry for this
#: table, so the country is split off the name with a vocabulary rather than by
#: whitespace, which was wrong often enough to fuse "Flowserve (Austria) GmbH Austria".
COUNTRIES = [
    "USA", "U.S.A", "US", "UK", "United Kingdom", "England", "Scotland", "Norway",
    "Italy", "Germany", "France", "Spain", "Sweden", "Denmark", "Netherlands",
    "Netherland", "Switzerland", "Finland", "Austria", "Belgium", "Japan", "China",
    "South Korea", "Korea", "India", "Singapore", "Malaysia", "Indonesia", "Thailand",
    "Vietnam", "Australia", "Canada", "Brazil", "Mexico", "Dubai", "UAE", "Batam",
    "Liberia",
]
_C = "|".join(re.escape(c) for c in sorted(COUNTRIES, key=len, reverse=True))
_TRAILING = re.compile(rf"(?:\b(?:{_C})\b)(?:\s*(?:/|,|\band\b)\s*(?:{_C})\b)*\s*$", re.I)

# "14.  i Ellehammer" - the sub-letter sits any distance from the number, and a
# single-space rule silently dropped four of the twelve firewater pump vendors and
# promoted one of them to a package of its own.
_ITEM = re.compile(r"^\s*(\d{1,2})\s*\.\s*([a-z])\s+(.*)$")
_NUM_ONLY = re.compile(r"^\s*(\d{1,2})\s*\.\s*$")
_NUM_TITLE = re.compile(r"^\s*(\d{1,2})\s*\.\s+([A-Za-z(].*)$")
_NOISE = ("Doc. No", "Rev No", "Page ", "Sr. No")

#: A package whose name says it is pumping something. Only these produce pump records.
PUMP_PACKAGE = re.compile(r"\bpumps?\b", re.I)


@dataclass
class Row:
    """One vendor as one document names it."""

    source_file: str
    source_kind: SourceType
    list_kind: str
    name: str
    normalized: str = ""
    country: str | None = None
    package: str | None = None
    project: str | None = None
    city: str | None = None
    region: str | None = None
    email: str | None = None
    phone: str | None = None
    sap_vendor_no: str | None = None
    company_codes: set[str] = field(default_factory=set)
    identifiers: dict = field(default_factory=dict)
    #: Every column of the source row, under its own heading.
    columns: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.normalized = normalise(self.name)


def _split_country(text: str) -> tuple[str, str | None]:
    text = " ".join(text.split())
    match = _TRAILING.search(text)
    if not match:
        return text, None
    name = text[: match.start()].strip(" -,")
    # A row that is only a country is not a vendor: keep the text as the name.
    return (name, " ".join(match.group(0).split())) if name else (text, None)


def parse_signed_list(path: str) -> list[Row]:
    reader = PdfReader(path)
    lines: list[str] = []
    for page in reader.pages:
        for raw in (page.extract_text() or "").splitlines():
            raw = raw.replace("�", "-").rstrip()
            if raw.strip() and not raw.lstrip().startswith(_NOISE):
                lines.append(raw)

    rows: list[Row] = []
    package: str | None = None
    awaiting_title = False
    for line in lines:
        stripped = line.strip()
        item = _ITEM.match(line)
        if item:
            awaiting_title = False
            name, country = _split_country(item.group(3))
            if name:
                rows.append(
                    Row(
                        source_file=os.path.basename(path),
                        source_kind=SourceType.PDF,
                        list_kind="signed_approved_suppliers",
                        project="ONGC KG-DWN-98/2",
                        package=package,
                        name=name,
                        country=country,
                    )
                )
            continue
        if _NUM_ONLY.match(line):
            # "25." alone: the package title is on the next line, which is how
            # "Process Pumps" and its nineteen vendors went missing.
            awaiting_title, package = True, None
            continue
        if awaiting_title:
            package = stripped if package is None else f"{package} {stripped}"
            awaiting_title = stripped.endswith("(") or stripped.startswith("(")
            continue
        title = _NUM_TITLE.match(line)
        if title:
            package = " ".join(title.group(2).split())
            continue
        if rows and not rows[-1].country and _TRAILING.fullmatch(stripped):
            rows[-1].country = stripped
    return rows


def parse_package_list(path: str) -> list[Row]:
    """The Kikeh workbook: a package column that only repeats when it changes."""
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    rows: list[Row] = []
    package: str | None = None
    for raw in sheet.iter_rows(min_row=3, values_only=True):
        cells = [" ".join(str(c).split()) if c else "" for c in raw[:4]]
        if cells[1]:
            package = cells[1]
        if cells[2]:
            rows.append(
                Row(
                    source_file=os.path.basename(path),
                    source_kind=SourceType.SPREADSHEET,
                    list_kind="project_package_list",
                    project="Kikeh",
                    package=package,
                    name=cells[2],
                    country=cells[3] or None,
                )
            )
    book.close()
    return rows


#: The SAP export's columns, by position. The identifiers are carried into
#: `Vendor.extra` at the platform owner's explicit instruction - see the module note
#: in the README section this script prints on completion.
_SAP = {
    "company_code": 4, "vendor_no": 6, "name": 7, "gst": 9, "pan": 10, "phone": 13,
    "city": 18, "email": 19, "region": 27, "lst": 40, "gst_class": 49, "msme": 51,
    "bank_name": 54, "bank_account": 55, "bank_key": 56, "created": 57, "msme_type": 58,
    "country": 46, "currency": 47,
}


def parse_vendor_master(path: str) -> list[Row]:
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    cells = sheet.iter_rows(values_only=True)
    header = next(cells, None)

    # Any other spreadsheet left in the folder is skipped rather than read as an
    # export. Without this the importer crashed on an unrelated workbook that
    # happened to be saved beside the source files - a folder is not a contract,
    # and an import that dies on a stray file is worse than one that ignores it.
    expected = max(_SAP.values()) + 1
    if not header or len(header) < expected or str(header[_SAP["vendor_no"]]).strip() != "Vendor":
        print(f"   skipped {os.path.basename(path)}: not an SAP vendor master export")
        book.close()
        return []

    rows: list[Row] = []
    for raw in cells:
        if not raw or len(raw) < expected or not raw[_SAP["vendor_no"]]:
            continue
        name = str(raw[_SAP["name"]] or "").strip()
        if not name:
            continue

        def value(key: str, raw=raw) -> str | None:  # noqa: B008 - bind this row
            cell = raw[_SAP[key]]
            return str(cell).strip() or None if cell not in (None, "") else None

        identifiers = {
            key: value(key)
            for key in ("gst", "pan", "lst", "msme", "msme_type", "gst_class",
                        "bank_name", "bank_account", "bank_key", "currency")
            if value(key)
        }
        # Every column the export carries, under the heading the export gave it.
        #
        # The named fields above are the ones this platform understands; this is
        # everything else, kept verbatim so the import is not also a silent edit.
        # An SAP column nobody has mapped yet is still the client's data, and a
        # reader who needs it should not have to go back to the spreadsheet.
        columns = {
            str(head).strip(): (str(cell).strip() if cell not in (None, "") else None)
            for head, cell in zip(header, raw, strict=False)
            if head and cell not in (None, "")
        }
        rows.append(
            Row(
                source_file=os.path.basename(path),
                source_kind=SourceType.SPREADSHEET,
                list_kind="sap_vendor_master",
                name=name,
                country=value("country"),
                city=value("city"),
                region=value("region"),
                email=(value("email") or "").lower() or None,
                phone=value("phone"),
                sap_vendor_no=str(raw[_SAP["vendor_no"]]).strip(),
                company_codes={str(raw[_SAP["company_code"]] or "").strip()} - {""},
                identifiers=identifiers,
                columns=columns,
            )
        )
    book.close()
    return rows


def parse_all(directory: str) -> list[Row]:
    rows: list[Row] = []
    for path in sorted(glob.glob(os.path.join(directory, "*.pdf"))):
        rows += parse_signed_list(path)
    for path in sorted(glob.glob(os.path.join(directory, "*.[xX][lL][sS][xX]"))):
        name = os.path.basename(path)
        rows += parse_package_list(path) if "Kikeh" in name else parse_vendor_master(path)
    return rows


# === Loading =================================================================


def _merge(rows: list[Row]) -> dict[str, list[Row]]:
    """One company, however many documents named it."""
    grouped: dict[str, list[Row]] = {}
    for row in rows:
        if row.normalized:
            grouped.setdefault(row.normalized, []).append(row)
    return grouped


def _tenant(db: Session, commit: bool) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == TENANT_SLUG))
    if tenant is not None:
        return tenant
    tenant = Tenant(
        slug=TENANT_SLUG,
        name=TENANT_NAME,
        industry_segment="upstream FPSO operator / EPC contractor",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.TRIAL,
        can_use_shared_master=True,
        # An approved vendor list is this client's commercial position. It must never
        # leak into the catalogue every other client reads.
        can_contribute_shared_master=False,
    )
    db.add(tenant)
    db.flush()
    print(f"   + tenant {tenant.name} ({tenant.id})")
    return tenant


def _source(db: Session, tenant: Tenant, row: Row, batches: dict) -> Source:
    key = f"{SOURCE_TAG} - {row.source_file}"
    if key in batches:
        return batches[key][0]
    source = db.scalar(
        select(Source).where(Source.tenant_id == tenant.id, Source.title == key)
    )
    if source is None:
        source = Source(
            tenant_id=tenant.id,
            source_type=row.source_kind,
            title=key,
            captured_at=datetime.now(UTC),
            # A signed list and an ERP export are not equally authoritative. The first
            # is an engineering authority's statement; the second says only that an
            # account exists.
            confidence_level=(
                ConfidenceLevel.VERIFIED
                if row.list_kind != "sap_vendor_master"
                else ConfidenceLevel.THIRD_PARTY
            ),
        )
        db.add(source)
        db.flush()
    batch = db.scalar(
        select(ImportBatch).where(
            ImportBatch.tenant_id == tenant.id, ImportBatch.name == key
        )
    )
    if batch is None:
        batch = ImportBatch(
            tenant_id=tenant.id,
            name=key,
            import_mode="approved_vendor_list",
            source_type=row.source_kind,
            status=IngestionStatus.PARSED,
            started_at=datetime.now(UTC),
            config={
                "list_kind": row.list_kind,
                "project": row.project,
                "data_owner": SOURCE_TAG,
                "confidence_tag": f"Confidence: {SOURCE_TAG}",
                "source_file": row.source_file,
            },
        )
        db.add(batch)
        db.flush()
    batches[key] = (source, batch)
    return source


def load(db: Session, rows: list[Row], commit: bool) -> dict[str, int]:
    tenant = _tenant(db, commit)
    counts = {"vendors_new": 0, "vendors_updated": 0, "also_in_shared": 0,
              "contacts": 0, "pumps": 0, "models": 0, "indexed": 0}
    batches: dict[str, tuple] = {}

    # Everything this script needs to recognise, read once.
    #
    # This database answers in about a third of a second, so what costs is the number
    # of queries, not their size. Looking each company up on its own was sixteen
    # hundred round trips and half an hour; three queries and a dictionary is seconds,
    # and the whole working set is a few thousand rows.
    shared = {
        normalise(v.name): v
        for v in db.scalars(
            select(Vendor).where(Vendor.tenant_id.is_(None), Vendor.deleted_at.is_(None))
        ).all()
    }
    mine = {
        v.normalized_name: v
        for v in db.scalars(
            select(Vendor).where(
                Vendor.tenant_id == tenant.id, Vendor.deleted_at.is_(None)
            )
        ).all()
    }
    pumps_by_key = {
        (p.vendor_id, p.normalized_name): p
        for p in db.scalars(
            select(Pump).where(Pump.tenant_id == tenant.id, Pump.deleted_at.is_(None))
        ).all()
    }
    models_by_key = {
        (m.pump_id, m.model_code): m
        for m in db.scalars(
            select(PumpModel).where(
                PumpModel.tenant_id == tenant.id, PumpModel.deleted_at.is_(None)
            )
        ).all()
    }
    import time as _t
    print(f"   preloaded {len(shared)} shared, {len(mine)} tenant vendors, "
          f"{len(pumps_by_key)} pumps at {_t.strftime('%H:%M:%S')}", flush=True)
    caches = (mine, pumps_by_key, models_by_key)
    pump_jobs: list[tuple] = []

    merged = sorted(_merge(rows).items())
    for done, (key, group) in enumerate(merged, 1):
        # Commit as we go. One transaction spanning every company is what the hosted
        # server closed the connection on last time, losing the whole run at the very
        # end; a batch that fails now costs only that batch, and the next run picks up
        # from the last committed company because matching is by normalised name.
        # Gated on `commit`: a dry run that committed its batches would not be a dry
        # run. Without `--commit` nothing is sent, and the whole thing rolls back.
        if commit and done % BATCH_SIZE == 0:
            db.commit()
            print(f"   committed {done}/{len(merged)} companies "
                  f"at {_t.strftime('%H:%M:%S')}", flush=True)

        approved = [r for r in group if r.list_kind != "sap_vendor_master"]
        primary = (approved or group)[0]
        source = _source(db, tenant, primary, batches)

        # Every company gets the client's own record, including the six the shared
        # catalogue already knows.
        #
        # Attaching to the shared row instead looked tidier and lost real data: KSB
        # alone carries eight SAP rows, and Flowserve, SPP Pumps and Amarinth five
        # more between them, none of which can be written to a shared record. Writes
        # to shared master are platform-admin only, and they would publish this
        # client's approvals and account numbers to every other client on the
        # platform. So shared master is read here and never touched: it tells us the
        # catalogue already knows the company, which is worth counting and nothing
        # more.
        if key in shared:
            counts["also_in_shared"] += 1
        vendor = mine.get(key)
        if vendor is None:
            vendor = Vendor(tenant_id=tenant.id, name=primary.name, normalized_name=key)
            db.add(vendor)
            mine[key] = vendor
            counts["vendors_new"] += 1
        else:
            counts["vendors_updated"] += 1

        aliases = sorted({r.name for r in group} - {vendor.name})
        vendor.aliases = aliases or None
        raw_country = next((r.country for r in group if r.country), None)
        primary, every = to_iso2(raw_country)
        vendor.country = primary
        vendor.hq_country = primary
        vendor.manufacturing_countries = every or None
        vendor.hq_city = next((r.city for r in group if r.city), None)
        vendor.approval_status = (
            VendorApprovalStatus.APPROVED if approved
            else VendorApprovalStatus.PENDING_QUALIFICATION
        )
        vendor.vendor_tier = (
            VendorTier.TIER_1_OEM if approved else VendorTier.UNCLASSIFIED
        )
        vendor.confidence_level = (
            ConfidenceLevel.VERIFIED if approved else ConfidenceLevel.THIRD_PARTY
        )
        vendor.verification_status = (
            VerificationStatus.VERIFIED if approved else VerificationStatus.UNVERIFIED
        )
        vendor.primary_source_id = source.id
        vendor.last_verified_at = datetime.now(UTC) if approved else None
        vendor.is_shared_master = False
        packages = sorted({r.package for r in group if r.package})
        vendor.product_families = packages or None

        sap = [r for r in group if r.sap_vendor_no]
        extra = dict(vendor.extra or {})
        # The tag, on the record itself rather than only on the source it points at,
        # so a reader looking at one vendor can see whose data it is without a join.
        extra["data_owner"] = SOURCE_TAG
        extra["confidence_tag"] = f"Confidence: {SOURCE_TAG}"
        extra["approved_packages"] = [
            {"project": r.project, "package": r.package, "country": r.country}
            for r in approved if r.package
        ]
        extra["source_documents"] = sorted({r.source_file for r in group})
        # Kept verbatim so a country the mapping could not place is still visible.
        extra["country_as_written"] = sorted({r.country for r in group if r.country})
        if sap:
            extra["sap"] = {
                "vendor_numbers": sorted({r.sap_vendor_no for r in sap}),
                "company_codes": sorted(set().union(*(r.company_codes for r in sap))),
                "created": next((r.identifiers.get("created") for r in sap), None),
                # Carried at the platform owner's explicit instruction.
                "identifiers": {k: v for r in sap for k, v in r.identifiers.items()},
                # One entry per source row, every column under its own heading. The
                # instruction was to store the complete data, so a column this
                # platform has no field for is kept rather than quietly dropped.
                "rows": [
                    {"source_file": r.source_file, "vendor_no": r.sap_vendor_no,
                     "columns": r.columns}
                    for r in sap
                ],
            }
        # Contacts go in `extra`, not in `vendor_contacts`.
        #
        # The model declares `source_id`, `captured_at` and `origin` on that table
        # and the deployed database has none of them, so every ORM insert fails on
        # a column that does not exist. This platform applies schema as raw SQL run
        # by the owner - the application role has no DDL rights by design - so the
        # fix is a migration somebody with those rights must apply, not something
        # an import script should attempt. Until then the detail is kept rather
        # than dropped, and moving it later is a query, not a re-import.
        contacts = [
            {"email": r.email, "phone": r.phone, "company_name": r.name,
             "role": "commercial"}
            for r in group
            if r.email or r.phone
        ]
        seen: set[tuple] = set()
        unique = []
        for contact in contacts:
            key_ = (contact["email"], contact["phone"])
            if key_ not in seen:
                seen.add(key_)
                unique.append(contact)
        if unique:
            extra["contacts"] = unique
            counts["contacts"] += len(unique)
        vendor.extra = extra
        # No flush here. Primary keys are generated in Python, so `vendor.id` is
        # already usable, and flushing each of sixteen hundred companies is
        # sixteen hundred round trips for nothing.

        # A pump record only where a document says the vendor supplies pumps. An SAP
        # account number is not such a statement. Deferred to a second pass because a
        # vendor has no id until it is flushed, and flushing per company is what made
        # the first version take half an hour.
        for row in group:
            if row.package and PUMP_PACKAGE.search(row.package):
                pump_jobs.append((vendor, row, source))

    print(f"   vendor pass done, flushing at {_t.strftime('%H:%M:%S')}", flush=True)
    db.flush()

    # The same facts, in the tables that hold them: `vendor_approvals`,
    # `vendor_identifiers`, `vendor_contacts` and the identity columns. Everything
    # written there is read back out of `extra`, which this pass leaves intact - the
    # verbatim source rows are the evidence behind each structured value.
    #
    # Skipped with a logged hint where migrations 002 and 003 have not been applied, so
    # an import against an older database still succeeds and keeps the detail in `extra`
    # exactly as it did before. `scripts.structure_client_data` finishes the job later.
    touched = list(mine.values())
    if touched and client_records.structure_available(db):
        held = client_records.load_held(db, [vendor.id for vendor in touched])
        for vendor in touched:
            structured = client_records.sync_vendor(db, vendor, held=held)
            for key, value in structured.items():
                counts[f"structured_{key}"] = counts.get(f"structured_{key}", 0) + value
        db.flush()
        print(
            "   structured: "
            + ", ".join(
                f"{counts.get(f'structured_{k}', 0)} {k}"
                for k in ("approvals", "identifiers", "contacts", "fields")
            ),
            flush=True,
        )

    print(f"   flushed; {len(pump_jobs)} pump jobs at {_t.strftime('%H:%M:%S')}", flush=True)
    for vendor, row, source in pump_jobs:
        counts.update(_ensure_pump(db, tenant, vendor, row, source, caches, counts))

    return counts


def _ensure_pump(db, tenant, vendor, row, source, caches, counts) -> dict:
    """The package the vendor is approved for, as a findable record.

    Only what the document states: the package, the project and the approval. No model
    code, no duty point, no price - the list does not give them, and a placeholder
    figure in a catalogue an engineer selects from is the one unrecoverable mistake.
    """
    _, pumps_by_key, models_by_key = caches
    family = row.package
    pump_key = (vendor.id, normalise(family))
    pump = pumps_by_key.get(pump_key)
    if pump is None:
        pump = Pump(
            tenant_id=tenant.id,
            vendor_id=vendor.id,
            name=family,
            normalized_name=normalise(family),
            product_family=family[:160],
            pump_type=PumpType.OTHER,
            pump_type_raw=family[:160],
        )
        db.add(pump)
        # Flushed here, unlike the vendor pass: the model below needs `pump.id`, and
        # this runs once per approved pump package - a few dozen - not once per company.
        db.flush()
        pumps_by_key[pump_key] = pump
        counts["pumps"] += 1

    code = f"{row.project} approved - {family}"[:160]
    model_key = (pump.id, code)
    model = models_by_key.get(model_key)
    if model is None:
        model = PumpModel(tenant_id=tenant.id, pump_id=pump.id, model_code=code)
        db.add(model)
        models_by_key[model_key] = model
        counts["models"] += 1
    model.service_application = family[:255]
    model.confidence_level = ConfidenceLevel.VERIFIED
    model.verification_status = VerificationStatus.VERIFIED
    model.primary_source_id = source.id
    db.flush()

    if reindex_pump_model(db, model.id) is not None:
        counts["indexed"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, help="folder holding the lists")
    parser.add_argument(
        "--commit", action="store_true", help="write; without it nothing is saved"
    )
    args = parser.parse_args()

    import time
    clock = time.perf_counter()
    rows = parse_all(args.dir)
    print(f"[{time.perf_counter()-clock:6.1f}s] parsed")
    if not rows:
        print("No rows parsed - check --dir", file=sys.stderr)
        return 1

    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row.list_kind] = kinds.get(row.list_kind, 0) + 1
    print(f"Parsed {len(rows)} rows from {args.dir}")
    for kind, count in sorted(kinds.items()):
        print(f"   {kind:28} {count:5}")
    merged = _merge(rows)
    print(f"   {'distinct companies':28} {len(merged):5}")

    with tenant_session(None, is_platform_admin=True) as db:
        print(f"[{time.perf_counter()-clock:6.1f}s] connected")
        counts = load(db, rows, args.commit)
        print(f"[{time.perf_counter()-clock:6.1f}s] loaded")
        print("\nResult:")
        for key, value in counts.items():
            print(f"   {key:18} {value}")
        if not args.commit:
            db.rollback()
            print("\nDRY RUN - nothing written. Re-run with --commit.")
        else:
            print("\nCommitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
