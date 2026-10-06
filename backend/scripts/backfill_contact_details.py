"""Record the contact details already sitting in captured pages.

A capture now writes the email addresses and phone numbers a company states on its own
site straight onto the vendor, each carrying the page it came from. Records captured
before that change kept their details only inside the stored page, which is why a vendor
profile could show "No contacts recorded" while the panel underneath listed the
switchboard.

    python -m scripts.backfill_contact_details            # dry run, writes nothing
    python -m scripts.backfill_contact_details --commit   # apply

Requires migration 002, which adds the provenance columns:

    python scripts/apply_schema.py --url "postgresql://OWNER:...@HOST/DB?sslmode=require" \
        --file db/migrations/002_vendor_contact_provenance.sql

What it does, and does not do:

* Reads only the pages that actually produced each record - its primary source plus
  every source its field provenance cites. Not every page ever crawled.
* Records only details from the company's *own* domain, the same rule the live path
  applies. A supplier's page routinely lists its distributors: one Amarinth page carried
  a partner's address and a Brazilian number. Those stay on the profile for a person to
  accept, because no rule can tell whose they are.
* Writes `source_id`, `captured_at` and `origin` on every row, so a backfilled contact
  is exactly as traceable as one recorded during a run.
* Skips anything already held, matching addresses case-insensitively and numbers on the
  dialled digits, so re-running adds nothing.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.ai import FieldProvenance
from app.models.source import Source
from app.models.vendor import Vendor
from app.services import vendor_discovery

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)


def sources_behind(db, vendor: Vendor) -> list[Source]:
    """The pages this record was built from, newest capture last."""
    source_ids = set(
        db.scalars(
            select(FieldProvenance.source_id).where(
                FieldProvenance.entity_type == "vendors",
                FieldProvenance.entity_id == vendor.id,
                FieldProvenance.source_id.isnot(None),
            )
        ).all()
    )
    if vendor.primary_source_id:
        source_ids.add(vendor.primary_source_id)
    if not source_ids:
        return []
    return list(
        db.scalars(
            select(Source)
            .where(Source.id.in_(source_ids))
            .order_by(Source.captured_at.asc().nulls_last())
        ).all()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit", action="store_true", help="write the contacts; otherwise dry run"
    )
    parser.add_argument(
        "--vendor", help="one vendor name, for checking the result before a full run"
    )
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        if not vendor_discovery.contact_provenance_available(db):
            print(
                "vendor_contacts has no provenance columns yet. Apply\n"
                "  db/migrations/002_vendor_contact_provenance.sql\n"
                "as the schema owner first - without them a recorded phone number would "
                "have nothing behind it.",
                file=sys.stderr,
            )
            return 2

        query = select(Vendor).where(Vendor.deleted_at.is_(None))
        if args.vendor:
            query = query.where(Vendor.name.ilike(f"%{args.vendor}%"))
        vendors = list(db.scalars(query.order_by(Vendor.name)).all())

        touched = 0
        recorded = 0
        for vendor in vendors:
            # By id, not by count: the read has no ORDER BY, so "the last n rows" is
            # not a promise the database makes.
            before = {row["id"] for row in vendor_discovery.contact_rows(db, vendor.id)}
            added = 0
            for source in sources_behind(db, vendor):
                added += vendor_discovery.record_page_contacts(db, vendor, source)
            if not added:
                continue

            touched += 1
            recorded += added
            print(f"{vendor.name}  {len(before)} held -> +{added}")
            for row in vendor_discovery.contact_rows(db, vendor.id):
                if row["id"] not in before:
                    print(f"    {row['email'] or row['phone']}")

            if args.commit:
                db.commit()
            else:
                db.rollback()

        print(
            f"\n{recorded} contact(s) across {touched} vendor(s) of {len(vendors)} read"
            + ("" if args.commit else "  (dry run - nothing written)")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
