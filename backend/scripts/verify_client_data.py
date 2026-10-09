"""Check that what the client's documents say is what this platform holds.

    python -m scripts.verify_client_data --dir "../../OneDrive_2026-09-21/Approved Vendor List"
    python -m scripts.verify_client_data --dir "..." --missing      # list what is absent
    python -m scripts.verify_client_data --dir "..." --vendor ABB   # one company, end to end

Read-only. Writes nothing, calls no AI, and re-reads the documents from disk every time -
which is the point: a verification that trusts the import is not a verification.

It answers four questions, per document:

1. **Did every company in the document reach the database?** Matched on the same
   normalised name the import matches on, within the client's tenancy.
2. **Did the facts reach it?** Approval statements, registration identifiers and contact
   details, counted in the file and counted in the database.
3. **Where do those facts live?** A fact in `vendors.extra` is imported but unstructured;
   the same fact in `vendor_approvals` is queryable, citable and visible in the API. The
   gap between the two columns is exactly what `scripts.structure_client_data` closes.
4. **Is anything in the database that the documents do not say?** The reverse direction,
   which is how an import bug that invents records would show up.

A difference is not automatically an error - a company named twice in one file is one
record, and `--missing` shows which rows were absorbed that way.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.tenant import Tenant
from app.models.vendor import Vendor
from app.services import client_records

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_approved_vendors import SOURCE_TAG, Row, normalise, parse_all  # noqa: E402

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)


def digits(value: str | None) -> str:
    return "".join(character for character in (value or "") if character.isdigit())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, help="folder holding the client documents")
    parser.add_argument("--missing", action="store_true", help="name what is not in the database")
    parser.add_argument("--vendor", help="trace one company from document to record")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f"No such folder: {args.dir}", file=sys.stderr)
        return 2

    print(f"reading {args.dir} ...")
    rows: list[Row] = parse_all(args.dir)
    if not rows:
        print("No rows parsed. Is this the right folder?", file=sys.stderr)
        return 2

    by_file: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_file[row.source_file].append(row)

    with tenant_session(None, is_platform_admin=True) as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == SOURCE_TAG))
        if tenant is None:
            print(f"No tenant named {SOURCE_TAG!r}. Has the import been run?", file=sys.stderr)
            return 2

        vendors = {
            vendor.normalized_name: vendor
            for vendor in db.scalars(
                select(Vendor).where(
                    Vendor.tenant_id == tenant.id, Vendor.deleted_at.is_(None)
                )
            ).all()
        }
        print(f"tenant {tenant.name!r}: {len(vendors)} live vendor(s)\n")

        structured = client_records.structure_available(db)
        counts = (
            db.execute(
                text("""
                SELECT (SELECT count(*) FROM vendor_approvals),
                       (SELECT count(*) FROM vendor_identifiers),
                       (SELECT count(*) FROM vendor_contacts)
                """)
            ).first()
            if structured
            else (0, 0, db.scalar(select(func.count()).select_from(text("vendor_contacts"))))
        )

        # ------------------------------------------------------------------ per document
        header = f"{'document':52} {'rows':>5} {'companies':>10} {'in db':>6} {'absent':>7}"
        print(header)
        print("-" * len(header))
        missing_by_file: dict[str, list[str]] = {}
        for name in sorted(by_file):
            file_rows = by_file[name]
            names = {row.normalized for row in file_rows if row.normalized}
            absent = sorted(n for n in names if n not in vendors)
            missing_by_file[name] = absent
            print(
                f"{name[:52]:52} {len(file_rows):5} {len(names):10} "
                f"{len(names) - len(absent):6} {len(absent):7}"
            )

        # --------------------------------------------------------------- facts, two ways
        doc_approvals = {
            (row.normalized, row.project, row.package)
            for row in rows
            if row.package and row.project
        }
        doc_contacts = {
            (row.normalized, (row.email or "").lower(), digits(row.phone))
            for row in rows
            if row.email or row.phone
        }
        doc_identifiers = {
            (row.normalized, scheme, str(value))
            for row in rows
            for scheme, value in (row.identifiers or {}).items()
            if scheme in client_records.IDENTIFIER_SCHEMES and value
        }

        in_extra = db.execute(
            text("""
            SELECT
              (SELECT coalesce(sum(jsonb_array_length(
                        coalesce(extra->'approved_packages','[]'::jsonb))), 0)
                 FROM vendors WHERE tenant_id = :t AND deleted_at IS NULL),
              (SELECT coalesce(sum(jsonb_array_length(coalesce(extra->'contacts','[]'::jsonb))), 0)
                 FROM vendors WHERE tenant_id = :t AND deleted_at IS NULL)
            """),
            {"t": tenant.id},
        ).first()

        print(f"\n{'fact':26} {'in the documents':>18} {'in extra (JSON)':>17} {'structured':>12}")
        print("-" * 78)
        print(f"{'approval statements':26} {len(doc_approvals):18} {in_extra[0]:17} {counts[0]:12}")
        print(f"{'registration identifiers':26} {len(doc_identifiers):18} {'-':>17} {counts[1]:12}")
        print(f"{'contact details':26} {len(doc_contacts):18} {in_extra[1]:17} {counts[2]:12}")

        if not structured:
            print(
                "\n   migration 003 is not applied, so the structured columns read 0. "
                "The facts are held in extra; see scripts/structure_client_data.py."
            )

        # --------------------------------------------------------- nothing invented
        invented = [
            vendor.name
            for key, vendor in vendors.items()
            if key not in {row.normalized for row in rows}
        ]
        print(f"\nin the database but in no document: {len(invented)}")
        for name in sorted(invented)[:10]:
            print(f"   {name}")
        if len(invented) > 10:
            print(f"   ... and {len(invented) - 10} more")

        # ------------------------------------------------------------------- one company
        if args.vendor:
            trace(db, vendors, rows, args.vendor, structured)

        if args.missing:
            print("\ncompanies in a document and not in the database:")
            for name, absent in sorted(missing_by_file.items()):
                if not absent:
                    continue
                print(f"\n   {name}  ({len(absent)})")
                for key in absent[:15]:
                    original = next((r.name for r in by_file[name] if r.normalized == key), key)
                    print(f"      {original}")
                if len(absent) > 15:
                    print(f"      ... and {len(absent) - 15} more")
    return 0


def trace(db, vendors, rows, needle: str, structured: bool) -> None:
    """Follow one company from the documents to the record, field by field."""
    key = normalise(needle)
    candidates = [k for k in vendors if key in k or k in key]
    print(f"\n=== {needle} ===")
    if not candidates:
        print("   not in the database under that name")
        return

    for match in candidates[:3]:
        vendor = vendors[match]
        said = [row for row in rows if row.normalized == match]
        print(f"\n   record: {vendor.name}   ({len(said)} document row(s))")
        for row in said:
            detail = " · ".join(
                part
                for part in (
                    row.source_file,
                    row.package and f"package: {row.package}",
                    row.country and f"country: {row.country}",
                    row.email,
                    row.sap_vendor_no and f"SAP {row.sap_vendor_no}",
                )
                if part
            )
            print(f"      {detail}")

        print(f"      stored country={vendor.country} city={vendor.hq_city} "
              f"status={getattr(vendor.approval_status, 'value', vendor.approval_status)}")
        print(f"      would structure: {client_records.approvals_for(vendor)} ")
        print(f"      identifiers    : {client_records.identifiers_for(vendor)}")
        print(f"      identity       : {client_records.identity_for(vendor)}")
        if structured:
            held = db.execute(
                text("SELECT project, package FROM vendor_approvals WHERE vendor_id = :v"),
                {"v": vendor.id},
            ).all()
            print(f"      held approvals : {held}")


if __name__ == "__main__":
    raise SystemExit(main())
