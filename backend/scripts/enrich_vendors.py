"""Ask the web to fill the gaps in the client's verified supplier records.

    python -m scripts.enrich_vendors                          # what it would do, and the cost
    python -m scripts.enrich_vendors --limit 5 --commit       # read the web for five
    python -m scripts.enrich_vendors --scope approved --limit 25 --commit
    python -m scripts.enrich_vendors --vendor "SULZER LTD" --commit

A client's documents establish who a supplier is and what it is approved for. They say
almost nothing else: of 1,643 imported records, 3 carry a website and none carry a
description, certifications or offshore references. Those are exactly the questions a web
search can answer, and this runs the same targeted enrichment the "Update this record
from the web" button runs, one record at a time.

**It cannot overwrite what the client stated.** `provenance.apply_field` refuses an AI
write against a field whose current provenance is VERIFIED, so a signed country or
product list stays as the document has it while the empty fields beside it fill in. That
protection depends on the imported values *having* provenance - run
`scripts.structure_client_data --commit` first, which writes it. This script checks and
refuses to start otherwise, because without it an enrichment run can replace a client's
facts with a web page's guesses.

Costs real money. Each record is one web search plus one model call per page read, so
twenty-five records at six pages is twenty-five searches and about a hundred and fifty
model calls. Nothing runs without `--commit`, and `--limit` defaults to five.

Runs execute in this process. There is no Redis here, so closing the terminal stops the
work - which is why this is a script you watch rather than a job you queue.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import func, select

from app.ai.parallel_search import vendor_intelligence_objective
from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.ai import FieldProvenance
from app.models.enums import ConfidenceLevel
from app.models.vendor import Vendor
from app.services import completeness, discovery, vendor_discovery

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

#: What a record is missing that the web can usually answer. Deliberately not the
#: financial fields: a company website rarely states revenue, and asking for it produces
#: a run that reads six pages and writes nothing.
WANTED = ("website", "hq_city", "description", "product_families")


def gaps(vendor: Vendor) -> list[str]:
    return [name for name in WANTED if not completeness.is_recorded(getattr(vendor, name, None))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="actually read the web")
    parser.add_argument(
        "--scope",
        choices=("verified", "approved", "all"),
        default="verified",
        help="verified: records a client document established (default). "
        "approved: only those on an approved suppliers list. all: every vendor with gaps.",
    )
    parser.add_argument("--vendor", help="one company, by name")
    parser.add_argument("--limit", type=int, default=5, help="how many records to enrich")
    parser.add_argument("--pages", type=int, default=6, help="pages to read per record")
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        # Without provenance on the imported values, an AI write would replace them.
        # Proven: before the provenance pass a web page moved a supplier from Singapore
        # to Zimbabwe; after it, the same write is refused.
        # Counted on the imported records specifically. Counting provenance across all
        # vendors would pass on the strength of the AI-discovered ones, which is the
        # opposite of the question: it is the *client's* values that need protecting.
        unprotected = db.scalar(
            select(func.count())
            .select_from(Vendor)
            .where(
                Vendor.deleted_at.is_(None),
                Vendor.extra.op("?")("data_owner"),
                ~select(FieldProvenance.id)
                .where(
                    FieldProvenance.entity_type == "vendors",
                    FieldProvenance.entity_id == Vendor.id,
                )
                .exists(),
            )
        )
        if unprotected:
            print(
                f"Refusing to start: {unprotected} imported record(s) carry no field "
                "provenance, so nothing stops a web page overwriting what the client's "
                "own documents state.\n"
                "Run `python -m scripts.structure_client_data --commit` first."
            )
            return 2

        query = select(Vendor).where(Vendor.deleted_at.is_(None))
        if args.vendor:
            query = query.where(Vendor.name.ilike(f"%{args.vendor}%"))
        elif args.scope == "verified":
            query = query.where(Vendor.confidence_level == ConfidenceLevel.VERIFIED)
        elif args.scope == "approved":
            query = query.where(Vendor.approval_status == "approved")

        candidates = [
            vendor for vendor in db.scalars(query.order_by(Vendor.name)).all() if gaps(vendor)
        ]
        chosen = candidates[: args.limit]

        print(f"{len(candidates)} record(s) in scope {args.scope!r} have gaps the web may fill")
        print(f"enriching {len(chosen)} of them, {args.pages} page(s) each\n")
        for vendor in chosen:
            print(f"   {vendor.name[:46]:46} missing: {', '.join(gaps(vendor))}")

        searches = len(chosen)
        calls = len(chosen) * args.pages
        print(f"\nthat is about {searches} web search(es) and {calls} model call(s)")

        if not args.commit:
            print("\ndry run - nothing read, nothing written. Add --commit to run it.")
            return 0

        done = 0
        for index, vendor in enumerate(chosen, 1):
            started = time.perf_counter()
            objective, queries = vendor_intelligence_objective(vendor.name)
            batch = discovery.start_run(
                db,
                vendor_discovery.KIND,
                tenant_id=vendor.tenant_id,
                query=vendor.name,
                country=vendor.hq_country,
                objective=objective,
                queries=queries,
                max_results=args.pages,
                user_id=None,
                target_vendor_id=vendor.id,
                auto_store=True,
                transport="in_process",
            )
            db.commit()
            print(f"\n[{index}/{len(chosen)}] {vendor.name[:44]} - run {batch.id}")
            try:
                discovery.run_discovery(db, vendor_discovery.KIND, batch.id, None)
            except Exception as exc:  # noqa: BLE001 - one bad record must not stop the batch
                print(f"   failed: {type(exc).__name__}: {str(exc)[:120]}")
                db.rollback()
                continue

            db.expire(vendor)
            remaining = gaps(vendor)
            filled = [name for name in WANTED if name not in remaining]
            print(
                f"   {time.perf_counter() - started:.0f}s · now holds: "
                f"{', '.join(filled) or 'nothing new'}"
                + (f" · still missing: {', '.join(remaining)}" if remaining else "")
            )
            done += 1

        print(f"\n{done} record(s) enriched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
