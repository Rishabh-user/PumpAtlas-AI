"""Move the imported client-document facts out of JSON and into the tables for them.

    python -m scripts.structure_client_data            # dry run, writes nothing
    python -m scripts.structure_client_data --commit
    python -m scripts.structure_client_data --vendor "SULZER" --commit

Requires **migration 003** (the approvals, identifiers and identity columns) and, for the
contacts, **migration 002** (the provenance columns on `vendor_contacts`). Each is
checked separately and skipped with a message rather than failing, because a database can
have one and not the other.

    python scripts/apply_schema.py --url "postgresql://OWNER:...@HOST/DB?sslmode=require" \
        --file db/migrations/002_vendor_contact_provenance.sql
    python scripts/apply_schema.py --url "postgresql://OWNER:...@HOST/DB?sslmode=require" \
        --file db/migrations/003_client_vendor_structure.sql

No document is re-read and no AI is called. Everything written here already exists in
`vendors.extra`, put there by `import_approved_vendors.py`; this is a move, not an
import, so it cannot invent a fact the documents did not state.

`extra` is left intact afterwards. It holds the verbatim source rows, which are the
evidence behind every structured value - removing them to avoid duplication would be
removing the provenance to tidy the record.

Idempotent: a second run writes nothing.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.vendor import Vendor
from app.services import client_records, vendor_discovery

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write; otherwise a dry run")
    parser.add_argument("--vendor", help="only vendors whose name contains this")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many vendors")
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        ready = client_records.structure_available(db)
        contacts_ready = vendor_discovery.contact_provenance_available(db)
        state = lambda flag: "applied" if flag else "NOT APPLIED"  # noqa: E731
        print(f"migration 003 (approvals, identifiers, identity): {state(ready)}")
        print(f"migration 002 (contact provenance):               {state(contacts_ready)}")

        query = select(Vendor).where(Vendor.deleted_at.is_(None)).order_by(Vendor.name)
        if args.vendor:
            query = query.where(Vendor.name.ilike(f"%{args.vendor}%"))
        vendors = list(db.scalars(query).all())
        if args.limit:
            vendors = vendors[: args.limit]

        # ---- pass one: say where each imported value came from ----------------------
        #
        # Needs no migration, and is the prerequisite for ever pointing an AI run at this
        # data: `provenance.apply_field` refuses an AI write over a value whose current
        # provenance is VERIFIED, and with no provenance rows at all there was nothing
        # for that guard to read. A client's signed country could have been replaced by
        # whatever a web page said.
        traced = 0
        for vendor in vendors:
            traced += client_records.record_document_provenance(db, vendor)
        print(f"\nprovenance written for {traced} field(s) across the imported records")

        if not ready:
            print(
                "\nThe rest needs migration 003 - see the command at the top of this file."
            )
            if args.commit:
                db.commit()
                print("committed the provenance")
            else:
                db.rollback()
                print("dry run - nothing written")
            return 0

        # Loaded once for the whole batch: two queries instead of two per vendor, which
        # across 1,684 vendors is the difference between seconds and a quarter of an hour.
        held = client_records.load_held(db, [vendor.id for vendor in vendors])

        totals = {"approvals": 0, "identifiers": 0, "contacts": 0, "fields": 0}
        touched = 0
        examples: list[str] = []

        for vendor in vendors:
            counts = client_records.sync_vendor(db, vendor, held=held)
            if not any(counts.values()):
                continue
            touched += 1
            for key, value in counts.items():
                totals[key] += value
            if len(examples) < 12:
                detail = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
                examples.append(f"   {vendor.name[:44]:44} {detail}")

        print(f"\n{touched} of {len(vendors)} vendor(s) have something to structure")
        for line in examples:
            print(line)
        if touched > len(examples):
            print(f"   ... and {touched - len(examples)} more")

        print("\n   approvals   ", totals["approvals"])
        print("   identifiers ", totals["identifiers"])
        print("   contacts    ", totals["contacts"], "" if contacts_ready else "(blocked on 002)")
        print("   identity    ", totals["fields"], "field(s) on vendors")

        if args.commit:
            db.commit()
            print("\ncommitted")
        else:
            db.rollback()
            print("\ndry run - nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
