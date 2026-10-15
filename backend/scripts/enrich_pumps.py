"""Hunt for the datasheets behind the pump models, and write what they can be quoted on.

    python -m scripts.enrich_pumps                          # what it would do, and the cost
    python -m scripts.enrich_pumps --limit 5 --commit       # read the web for five
    python -m scripts.enrich_pumps --vendor Sulzer --commit
    python -m scripts.enrich_pumps --group commercial --limit 10 --commit

The "Find datasheet" button does exactly this for one record. There was no way to do it
for a hundred, which mattered because a hundred is the actual number: a product page
names the pump and says nothing about its duty point, what it costs or how long it takes
to deliver. Across this database that reads as technical specifications on 72 of 160
models, and commercial specifications on **none**.

**It only runs against records that have a product to look for.** Of 160 models, 65 are
approved-suppliers lines ("ONGC KG-DWN-98/2 approved - Process Pumps"), 15 are resolver
placeholders and 13 are bare API type codes. None of those name a product, so a datasheet
hunt against them spends a search and a model call per page and comes back with nothing.
`designations.searchability` is what separates them, and `scripts.pending_pumps` prints
the same split with the action for each kind.

**It cannot overwrite a verified value.** `provenance.apply_field` refuses an AI write
against a field whose current provenance is VERIFIED, so anything a client document or a
reviewer established stays as it is while the empty fields beside it fill in.

Costs real money. Each record is one web search plus one model call per page read, so ten
records at six pages is ten searches and about sixty model calls. Nothing runs without
``--commit``, and ``--limit`` defaults to five.

Runs execute in this process. There is no Redis here, so closing the terminal stops the
work - which is why this is a script you watch rather than a job you queue.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import select

from app.ai.parallel_search import pump_model_objective
from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.pump import Pump, PumpModel
from app.models.specs import (
    AdministrativeSpec,
    CommercialSpec,
    DeliverySpec,
    DimensionalSpec,
    OperationalSpec,
    TechnicalSpec,
)
from app.models.vendor import Vendor
from app.services import designations, discovery, pump_discovery

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

GROUPS = {
    "technical": TechnicalSpec,
    "commercial": CommercialSpec,
    "dimensional": DimensionalSpec,
    "delivery": DeliverySpec,
    "operational": OperationalSpec,
    "administrative": AdministrativeSpec,
}


def held_groups(db) -> dict:
    """Which specification groups each model already holds, in six queries not six per model."""
    held: dict = {}
    for group, spec_cls in GROUPS.items():
        for (model_id,) in db.execute(
            select(spec_cls.pump_model_id).where(spec_cls.is_current.is_(True)).distinct()
        ).all():
            held.setdefault(model_id, set()).add(group)
    return held


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="actually read the web")
    parser.add_argument("--vendor", help="one manufacturer, by name")
    parser.add_argument(
        "--group",
        choices=sorted(GROUPS),
        help="only records missing this specification group",
    )
    parser.add_argument("--limit", type=int, default=5, help="how many records to enrich")
    parser.add_argument("--pages", type=int, default=6, help="pages to read per record")
    parser.add_argument(
        "--include-unsearchable",
        action="store_true",
        help=(
            "run against scope entries, placeholders and bare type codes too. These have "
            "no product to find a datasheet for; this exists to prove that, not to be used."
        ),
    )
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        rows = db.execute(
            select(PumpModel, Vendor)
            .join(Pump, Pump.id == PumpModel.pump_id)
            .join(Vendor, Vendor.id == Pump.vendor_id)
            .where(PumpModel.deleted_at.is_(None))
        ).all()
        if args.vendor:
            rows = [r for r in rows if args.vendor.lower() in (r[1].name or "").lower()]

        held = held_groups(db)
        skipped: dict[str, int] = {}
        candidates = []
        for model, vendor in rows:
            missing = [name for name in GROUPS if name not in held.get(model.id, set())]
            if not missing:
                continue
            if args.group and args.group not in missing:
                continue
            kind = designations.searchability(model.model_code)
            if not kind.enrichable and not args.include_unsearchable:
                skipped[kind.value] = skipped.get(kind.value, 0) + 1
                continue
            candidates.append((model, vendor, missing, kind))

        # Emptiest first: a record missing six groups has more to gain from one search
        # than one missing a single group.
        candidates.sort(key=lambda item: (-len(item[2]), item[1].name or ""))
        chosen = candidates[: args.limit]

        print(f"{len(rows)} live pump model(s)")
        if skipped:
            total = sum(skipped.values())
            detail = ", ".join(f"{n} {kind}" for kind, n in sorted(skipped.items()))
            print(f"   {total} skipped - no product to search for ({detail})")
        label = (
            "with a missing group, searchable or not"
            if args.include_unsearchable
            else "with a real designation and a missing group"
        )
        print(f"   {len(candidates)} {label}")
        print(f"\nenriching {len(chosen)} of them, {args.pages} page(s) each\n")
        for model, vendor, missing, _kind in chosen:
            designation = designations.product_name(model.model_code) or model.model_code
            print(
                f"   {vendor.name[:24]:24} {designation[:28]:28} "
                f"missing: {', '.join(missing)}"
            )

        print(
            f"\nthat is about {len(chosen)} web search(es) and "
            f"{len(chosen) * args.pages} model call(s)"
        )

        if not args.commit:
            print("\ndry run - nothing read, nothing written. Add --commit to run it.")
            return 0

        done = 0
        for index, (model, vendor, missing, _kind) in enumerate(chosen, 1):
            started = time.perf_counter()
            designation = designations.product_name(model.model_code) or model.model_code
            objective, queries = pump_model_objective(vendor.name, designation)
            batch = discovery.start_run(
                db,
                pump_discovery.KIND,
                tenant_id=model.tenant_id,
                query=f"{vendor.name} {designation}",
                country=vendor.hq_country,
                objective=objective,
                queries=queries,
                max_results=args.pages,
                user_id=None,
                # Naming this record as the target is what stops a datasheet that spells
                # the designation differently creating a second model beside this one.
                target_pump_model_id=model.id,
                auto_store=True,
                transport="in_process",
            )
            db.commit()
            print(
                f"\n[{index}/{len(chosen)}] {vendor.name[:30]} "
                f"{designation[:26]} - run {batch.id}"
            )
            try:
                discovery.run_discovery(db, pump_discovery.KIND, batch.id, None)
            except Exception as exc:  # noqa: BLE001 - one bad record must not stop the batch
                print(f"   failed: {type(exc).__name__}: {str(exc)[:120]}")
                db.rollback()
                continue

            # Re-read rather than trust the run's own report: what matters is what the
            # database holds afterwards, which is what the profile page will show.
            now_held = held_groups(db).get(model.id, set())
            gained = [name for name in missing if name in now_held]
            still = [name for name in missing if name not in now_held]
            print(
                f"   {time.perf_counter() - started:.0f}s · gained: "
                f"{', '.join(gained) or 'nothing'}"
                + (f" · still missing: {', '.join(still)}" if still else "")
            )
            done += 1

        print(f"\n{done} record(s) enriched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
