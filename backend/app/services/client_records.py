"""Turning a client document's facts into records the platform can answer with.

Three kinds of document were imported into this platform - a signed approved suppliers
list, a project package list, and five SAP vendor-master exports - and the import kept
every column. Nothing was lost. But most of it was kept inside `vendors.extra` as JSON,
because at the time there was nowhere else for it to go, and JSON is a holding pen rather
than a destination: 333 approval statements and 1,404 sets of registration identifiers
that cannot be queried, indexed, filtered, cited or shown on a page.

This module reads what is in `extra` and writes it where it belongs - `vendor_approvals`,
`vendor_identifiers`, `vendor_contacts`, and the identity columns migration 003 adds. The
same functions serve the backfill of what is already imported and the import itself, so
there is one definition of "what this document means" rather than two that drift.

`extra` is left intact. It holds the verbatim source rows, which is the evidence behind
every structured value here; deleting it to avoid duplication would be deleting the
provenance to tidy the record.

Every function is idempotent. Running the backfill twice writes the same rows once.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ai import FieldProvenance
from app.models.enums import ConfidenceLevel, ValueOrigin
from app.models.vendor import (
    MIGRATION_003_COLUMNS,
    Vendor,
    VendorApproval,
    VendorIdentifier,
)
from app.services import completeness, provenance

log = get_logger(__name__)

#: Which `extra.sap.identifiers` keys are identifiers, and what to call each scheme.
#:
#: `currency` and `gst_class` are in that dictionary too and are not identifiers - one is
#: a purchase-order default, the other a tax treatment - so they stay in `extra`.
#:
#: The bank keys are deliberately absent. `bank_account`, `bank_key` and `bank_name` are
#: payment instructions for 59 suppliers; a pump intelligence platform has no use for
#: them and holding them is a liability, not an asset. They are left where they are rather
#: than copied into a second place, and `scripts.purge_bank_details` removes them.
IDENTIFIER_SCHEMES = {
    "gst": "gst",
    "pan": "pan",
    "msme": "msme",
    "vat": "vat",
    "lst": "lst",
    "cst": "cst",
    "duns": "duns",
}

#: SAP headings carrying the parts of a street address, in the order they print.
_ADDRESS_COLUMNS = ("Street", "Street 2", "Street 3", "Street 4", "Street 5")

#: Headings whose value is a 'Yes' when the client has barred buying from a supplier.
_BLOCK_COLUMNS = ("Centrally imposed purchasing block", "Central posting block")

_MIGRATION_HINT = (
    "Apply db/migrations/003_client_vendor_structure.sql as the schema owner to "
    "structure the client document data."
)

#: The identity columns migration 003 adds, named in `app.models.vendor` beside the
#: columns themselves so there is one list rather than two that drift. A caller that
#: sweeps every column by name defeats the deferral, so it asks here what to leave out.
MIGRATION_003_VENDOR_COLUMNS = MIGRATION_003_COLUMNS


_READY: bool | None = None


def vendor_columns(db: Session) -> list:
    """The `vendors` columns this database actually has, for a full-record serialisation."""
    table = Vendor.__table__
    if structure_available(db):
        return list(table.c)
    return [c for c in table.c if c.name not in MIGRATION_003_VENDOR_COLUMNS]


def structure_available(db: Session) -> bool:
    """Whether migration 003 has been applied.

    Cached per process: it is a catalogue lookup, and the answer only changes when
    somebody applies a migration, which restarts the service anyway.
    """
    global _READY
    if _READY is None:
        tables = set(sa_inspect(db.get_bind()).get_table_names())
        _READY = {"vendor_approvals", "vendor_identifiers"} <= tables
        if not _READY:
            log.warning("client_records.structure_missing", hint=_MIGRATION_HINT)
    return _READY


def _clean(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _sap_rows(vendor: Vendor) -> list[dict[str, Any]]:
    sap = (vendor.extra or {}).get("sap") or {}
    rows = sap.get("rows") or []
    return [row.get("columns") or {} for row in rows if isinstance(row, dict)]


# --------------------------------------------------------------------- what the documents say


def approvals_for(vendor: Vendor) -> list[dict[str, Any]]:
    """One entry per "approved for this package on this project" statement."""
    entries = (vendor.extra or {}).get("approved_packages") or []
    documents = (vendor.extra or {}).get("source_documents") or []
    reference = documents[0] if len(documents) == 1 else None

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        project = _clean(entry.get("project"))
        package = _clean(entry.get("package"))
        if not project or not package:
            continue
        key = (project, package)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "project": project[:160],
                "package": package[:300],
                # Verbatim: "UK / Brazil / India" is what the document says, and the
                # document is the authority on what it said.
                "approved_country": (_clean(entry.get("country")) or "")[:160] or None,
                "document_reference": reference,
            }
        )
    return out


def identifiers_for(vendor: Vendor) -> list[dict[str, str]]:
    """Registration and tax identifiers, one per scheme and value."""
    sap = (vendor.extra or {}).get("sap") or {}
    held = sap.get("identifiers") or {}

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for number in sap.get("vendor_numbers") or []:
        value = _clean(number)
        if value and ("sap_vendor_no", value) not in seen:
            seen.add(("sap_vendor_no", value))
            out.append({"scheme": "sap_vendor_no", "value": value[:120]})

    for key, scheme in IDENTIFIER_SCHEMES.items():
        value = _clean(held.get(key))
        # "NA" is how a spreadsheet says "we did not fill this in". Storing it as an
        # identifier would make a company findable by searching for nothing.
        if not value or value.upper() in {"NA", "N/A", "NIL", "NONE", "-"}:
            continue
        if value.strip("0") == "" or (scheme, value) in seen:
            continue
        seen.add((scheme, value))
        out.append({"scheme": scheme, "value": value[:120]})

    if vendor.dun_bradstreet_number:
        value = _clean(vendor.dun_bradstreet_number)
        if value and ("duns", value) not in seen:
            out.append({"scheme": "duns", "value": value[:120]})
    return out


def identity_for(vendor: Vendor) -> dict[str, Any]:
    """The identity columns migration 003 adds, read off the SAP rows."""
    rows = _sap_rows(vendor)
    if not rows:
        return {}

    out: dict[str, Any] = {}

    for row in rows:
        parts = [_clean(row.get(name)) for name in _ADDRESS_COLUMNS]
        address = ", ".join(part for part in parts if part)
        if address:
            out["address_line"] = address[:500]
            break

    for row in rows:
        region = _clean(row.get("Region (State, Province, County)")) or _clean(row.get("Region"))
        if region:
            out["state_region"] = region[:120]
            break

    # The second and third name lines are the registered name where they differ from the
    # trading name; where they repeat it, they say nothing and are skipped.
    for row in rows:
        primary = (_clean(row.get("Name 1")) or "").casefold()
        for heading in ("Name 2", "Name 3"):
            candidate = _clean(row.get(heading))
            if candidate and candidate.casefold() != primary and len(candidate) > 3:
                out.setdefault("legal_entity_name", candidate[:255])
                break

    for row in rows:
        created = row.get("Vendor Cr. Date")
        if isinstance(created, datetime):
            out["client_since"] = created.date()
            break
        if isinstance(created, date):
            out["client_since"] = created
            break
        text = _clean(created)
        if text:
            try:
                out["client_since"] = datetime.fromisoformat(text[:10]).date()
                break
            except ValueError:
                continue

    blocked = [
        heading
        for row in rows
        for heading in _BLOCK_COLUMNS
        if str(row.get(heading) or "").strip().lower() in {"yes", "x", "true"}
    ]
    if blocked:
        out["is_purchasing_blocked"] = True
        out["purchasing_block_note"] = (
            "Stated in the client's SAP vendor master: " + ", ".join(sorted(set(blocked)))
        )
    return out


def contacts_for(vendor: Vendor) -> list[dict[str, Any]]:
    """The contact entries the import parked in `extra` while the table lacked columns."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for entry in (vendor.extra or {}).get("contacts") or []:
        if not isinstance(entry, dict):
            continue
        email = _clean(entry.get("email"))
        phone = _clean(entry.get("phone"))
        if not email and not phone:
            continue
        key = ((email or "").lower(), re_digits(phone))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "email": email[:320] if email else None,
                "phone": phone[:64] if phone else None,
                "company_name": (_clean(entry.get("company_name")) or "")[:255] or None,
                "contact_role": _clean(entry.get("role")) or "commercial",
            }
        )
    return out


def re_digits(value: str | None) -> str:
    return "".join(character for character in (value or "") if character.isdigit())


# ------------------------------------------------------------------------------ writing


def load_held(db: Session, vendor_ids: list) -> tuple[set, set]:
    """What is already structured, for a whole batch, in two queries.

    `sync_vendor` otherwise asks twice per vendor whether a row exists. Across 1,684
    vendors that is 3,368 round trips to a database roughly 300ms away - about seventeen
    minutes of waiting to discover that almost nothing is there yet. The caller loads
    once and passes the answer in.
    """
    if not vendor_ids or not _READY:
        return set(), set()
    approvals = {
        (row.vendor_id, row.project, row.package)
        for row in db.scalars(
            select(VendorApproval).where(VendorApproval.vendor_id.in_(vendor_ids))
        ).all()
    }
    identifiers = {
        (row.vendor_id, row.scheme, row.value)
        for row in db.scalars(
            select(VendorIdentifier).where(VendorIdentifier.vendor_id.in_(vendor_ids))
        ).all()
    }
    return approvals, identifiers


#: The columns a client document establishes, and which therefore need provenance.
#:
#: Without a provenance row a value is untraceable *and* unprotected: the guard in
#: `provenance.apply_field` that refuses an AI write over a human-verified value reads
#: `field_provenance.confidence_level`, and all 1,601 imported vendors had no rows at
#: all. An enrichment run could have replaced a client's signed country or product list
#: with whatever a web page said.
DOCUMENT_ESTABLISHED_FIELDS = (
    "name",
    "country",
    "hq_country",
    "hq_city",
    "product_families",
    "manufacturing_countries",
    "approval_status",
)


def record_document_provenance(db: Session, vendor: Vendor) -> int:
    """Say where each imported value came from, and protect it from being overwritten.

    The evidence is the document itself - a signed approved suppliers list, a project
    package list, an SAP export - which the import already recorded as a `Source`. The
    confidence mirrors what the import judged: a signed list is `VERIFIED`, an ERP
    account is `THIRD_PARTY`.

    `record_unchanged` is the point. These values are already on the row, written at
    insert; without it `apply_field` sees no change and records nothing, which is how the
    most trustworthy data in the platform ended up as the only data with no source.

    Writes nothing for a field that already has provenance, so re-running is free.
    """
    extra = vendor.extra or {}
    if "data_owner" not in extra:
        return 0

    documents = extra.get("source_documents") or []
    stated = ", ".join(documents) if documents else "a client document"
    confidence = (
        ConfidenceLevel.VERIFIED
        if vendor.confidence_level == ConfidenceLevel.VERIFIED
        else ConfidenceLevel.THIRD_PARTY
    )
    held = {
        name
        for (name,) in db.execute(
            select(FieldProvenance.field_name).where(
                FieldProvenance.entity_type == "vendors",
                FieldProvenance.entity_id == vendor.id,
            )
        ).all()
    }

    context = provenance.ProvenanceContext(
        # Not MANUAL and not AI: a document the client supplied, loaded by a script.
        origin=ValueOrigin.IMPORT,
        confidence_level=confidence,
        source_id=vendor.primary_source_id,
        tenant_id=vendor.tenant_id,
    )

    written = 0
    for name in DOCUMENT_ESTABLISHED_FIELDS:
        if name in held:
            continue
        value = getattr(vendor, name, None)
        if not completeness.is_recorded(value):
            continue
        provenance.apply_field(
            db,
            vendor,
            name,
            value,
            context,
            evidence_quote=f"Stated by {stated}",
            record_unchanged=True,
        )
        written += 1
    return written


def sync_vendor(
    db: Session,
    vendor: Vendor,
    *,
    source_id=None,
    held: tuple[set, set] | None = None,
) -> dict[str, int]:
    """Write everything this vendor's documents state into the tables that hold it.

    Idempotent, and additive: an approval or identifier already present is left alone,
    and an identity column already holding a value is not overwritten - a person may have
    corrected it, and a re-run of an import is not grounds to undo that.
    """
    counts = {"approvals": 0, "identifiers": 0, "contacts": 0, "fields": 0}
    if not structure_available(db):
        return counts

    source = source_id or vendor.primary_source_id
    now = datetime.now(UTC)

    if held is None:
        held_approvals, held_identifiers = load_held(db, [vendor.id])
    else:
        held_approvals, held_identifiers = held

    for entry in approvals_for(vendor):
        if (vendor.id, entry["project"], entry["package"]) in held_approvals:
            continue
        held_approvals.add((vendor.id, entry["project"], entry["package"]))
        db.add(
            VendorApproval(
                tenant_id=vendor.tenant_id,
                vendor_id=vendor.id,
                source_id=source,
                status="approved",
                **entry,
            )
        )
        counts["approvals"] += 1

    for entry in identifiers_for(vendor):
        if (vendor.id, entry["scheme"], entry["value"]) in held_identifiers:
            continue
        held_identifiers.add((vendor.id, entry["scheme"], entry["value"]))
        db.add(
            VendorIdentifier(
                tenant_id=vendor.tenant_id,
                vendor_id=vendor.id,
                source_id=source,
                captured_at=now,
                **entry,
            )
        )
        counts["identifiers"] += 1

    for name, value in identity_for(vendor).items():
        if getattr(vendor, name, None) in (None, "", False):
            setattr(vendor, name, value)
            counts["fields"] += 1

    counts["contacts"] = _sync_contacts(db, vendor, source=source, now=now)
    return counts


def _sync_contacts(db: Session, vendor: Vendor, *, source, now) -> int:
    """Move the parked contact entries into `vendor_contacts`.

    Guarded separately: these need migration **002**, which adds the provenance columns,
    and a database can have one migration and not the other.
    """
    from app.services import vendor_discovery

    if not vendor_discovery.contact_provenance_available(db):
        return 0

    held = vendor_discovery.contact_rows(db, vendor.id)
    known_emails = {(row["email"] or "").lower() for row in held if row["email"]}
    known_phones = {re_digits(row["phone"]) for row in held if row["phone"]}

    added = 0
    for entry in contacts_for(vendor):
        email = (entry["email"] or "").lower()
        phone = re_digits(entry["phone"])
        if (email and email in known_emails) or (phone and phone in known_phones):
            continue
        if email:
            known_emails.add(email)
        if phone:
            known_phones.add(phone)
        vendor_discovery.insert_contact(
            db,
            vendor_id=vendor.id,
            tenant_id=vendor.tenant_id,
            full_name=entry["company_name"] or vendor.name,
            company_name=entry["company_name"],
            email=entry["email"],
            phone=entry["phone"],
            contact_role=entry["contact_role"],
            source_id=source,
            captured_at=now,
            # A client's own document, not something a model read off a web page.
            origin="manual",
        )
        added += 1
    return added
