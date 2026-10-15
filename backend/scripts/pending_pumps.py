"""Which pump records are still waiting for data, and what each one is waiting for.

    python -m scripts.pending_pumps                 # the whole picture, worst first
    python -m scripts.pending_pumps --kind product  # only the ones enrichment can fill
    python -m scripts.pending_pumps --vendor LUBOR  # one manufacturer

Read-only; writes nothing.

"Pending" is **four** states, and only one of them is answered by looking for a datasheet.
This script used to report two, which meant it recommended a datasheet hunt for 78 of 160
records that have no datasheet to find - a web search and a model call per page, each
time, returning nothing.

**A thin record** has a real designation and empty specification groups: a product page
named the product and said nothing about what it costs, how long it takes or how it
performs. `POST /pump-models/{id}/enrich` - the "Find datasheet" button - hunts for the
datasheet and writes what it can quote. This is the only group where that works.

**A scope entry** - "ONGC KG-DWN-98/2 approved - Process Pumps" - is a line off an
approved-suppliers list. It says a vendor may supply a *category* on a project. There is
no such product, so no datasheet exists and none ever will. These are pump models only
because the importer had nowhere else to put them; migration 003 adds the
`vendor_approvals` table where they belong.

**A placeholder** - "Bornerman unspecified line (unspecified variant)" - is a row that
exists so a vendor had somewhere to hang, with a designation the resolver invented. The
action is a pump discovery seeded with the manufacturer's name, to find what it sells.

**A bare type code** - "OH6", "VS1" - is an API 610 configuration, not a model. Hundreds
of manufacturers build an OH6. `scripts.flag_category_models` is the action.

The percentage is `data_completeness_pct`, which is only populated once
`scripts.repair_vendor_data` has run; until then it reads as unknown and the group
columns are the thing to look at.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

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
from app.services import completeness, designations

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
    """Which spec groups each model has a current row for, in six queries not six per model."""
    held: dict = {}
    for group, spec_cls in GROUPS.items():
        for (model_id,) in db.execute(
            select(spec_cls.pump_model_id).where(spec_cls.is_current.is_(True)).distinct()
        ).all():
            held.setdefault(model_id, set()).add(group)
    return held


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=[kind.value for kind in designations.Searchability],
        help="show only one kind: product, scope_entry, placeholder or type_code",
    )
    parser.add_argument(
        "--placeholders",
        action="store_true",
        help="the older spelling of --kind placeholder",
    )
    parser.add_argument("--vendor", help="only this manufacturer")
    parser.add_argument("--limit", type=int, default=40, help="rows to print")
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        query = (
            select(PumpModel, Pump.name, Vendor.name)
            .join(Pump, Pump.id == PumpModel.pump_id)
            .join(Vendor, Vendor.id == Pump.vendor_id)
            .where(PumpModel.deleted_at.is_(None))
        )
        if args.vendor:
            query = query.where(Vendor.name.ilike(f"%{args.vendor}%"))
        rows = db.execute(query).all()
        held = held_groups(db)

        # Every record lands in exactly one bucket, and a record holding every group is
        # not pending whatever kind of name it carries.
        buckets: dict[designations.Searchability, list] = {
            kind: [] for kind in designations.Searchability
        }
        complete = []
        for model, pump_name, vendor_name in rows:
            groups = held.get(model.id, set())
            missing = [name for name in GROUPS if name not in groups]
            record = (vendor_name, model.model_code, pump_name, missing, model)
            if not missing:
                complete.append(record)
                continue
            buckets[designations.searchability(model.model_code)].append(record)

        pending = sum(len(items) for items in buckets.values())
        enrichable = len(buckets[designations.Searchability.PRODUCT])
        print(f"\n{len(rows)} live pump model(s)")
        print(f"   {len(complete)} holding every specification group")
        print(f"   {pending} pending, of which:")
        for kind, items in buckets.items():
            print(f"      {len(items):4}  {kind.value}")
        print(
            f"\nOnly the {enrichable} product record(s) can be filled by looking for a "
            f"datasheet. The other {pending - enrichable} name a category, a type, or "
            "nothing at all."
        )

        print("\ngroup coverage:")
        everything = [*complete, *(r for items in buckets.values() for r in items)]
        for group in GROUPS:
            have = sum(1 for _, _, _, missing, _ in everything if group not in missing)
            print(f"   {group:15} {have:3} of {len(rows)}")

        if args.placeholders:  # the older spelling, still honoured
            wanted = [designations.Searchability.PLACEHOLDER]
        elif args.kind:
            wanted = [designations.Searchability(args.kind)]
        else:
            wanted = list(designations.Searchability)

        for kind in wanted:
            items = buckets[kind]
            print(f"\n--- {kind.value} ({len(items)}) ---")
            print(f"    {kind.action}\n")
            for vendor_name, code, _pump, missing, model in sorted(
                items, key=lambda item: (-len(item[3]), item[0])
            )[: args.limit]:
                pct = (
                    f"{float(model.data_completeness_pct) * 100:.0f}%"
                    if model.data_completeness_pct is not None
                    else "  ? "
                )
                # The missing-group list is only actionable for a real product; for the
                # rest it just restates that an approval line has no duty point.
                shown = (
                    f"missing: {', '.join(missing)}"
                    if kind is designations.Searchability.PRODUCT
                    else ""
                )
                print(f"   {pct:>5}  {vendor_name:26} {str(code)[:34]:34} {shown}".rstrip())
            if len(items) > args.limit:
                print(f"   ... and {len(items) - args.limit} more")


        print(
            f"\ntracked fields per model: {completeness.MODEL_TRACKED} "
            f"({completeness.TRACKED_SPEC_FIELDS} across the six specification groups)"
        )
        unknown = sum(
            1
            for items in buckets.values()
            for _, _, _, _, model in items
            if model.data_completeness_pct is None
        )
        if unknown:
            print(
                f"{unknown} record(s) have no completeness figure yet - run "
                "`python -m scripts.repair_vendor_data --commit` to fill it in."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
