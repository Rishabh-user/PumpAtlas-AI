"""Which pump records are still waiting for data, and what each one is waiting for.

    python -m scripts.pending_pumps                 # the whole picture, worst first
    python -m scripts.pending_pumps --placeholders  # only the records with no product
    python -m scripts.pending_pumps --vendor LUBOR  # one manufacturer

Read-only; writes nothing.

"Pending" is two different states, and they need different actions:

**A placeholder** - "Bornerman unspecified line (unspecified variant)" - is a row that
exists so a vendor had somewhere to hang. The page that produced it named a manufacturer
and no product, so `resolve_pump_model` inserted a variant with a made-up designation.
There is no datasheet to look for, because there is no model. The action is a pump
discovery run seeded with the manufacturer's name, which finds what it actually sells;
the placeholder is then removed or renamed.

**A thin record** has a real designation and empty specification groups. Across this
database that is most of them: a product page names the product and states nothing about
what it costs, how long it takes or how it performs. The action is
`POST /pump-models/{id}/enrich` - the "Find datasheet" button on the profile - which
hunts for the datasheet and writes what it can quote.

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
from app.services import completeness

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

PLACEHOLDER = "unspecified"


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
    parser.add_argument("--placeholders", action="store_true", help="only rows with no product")
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

        placeholders, thin, complete = [], [], []
        for model, pump_name, vendor_name in rows:
            groups = held.get(model.id, set())
            missing = [name for name in GROUPS if name not in groups]
            record = (vendor_name, model.model_code, pump_name, missing, model)
            if PLACEHOLDER in (model.model_code or "").lower():
                placeholders.append(record)
            elif missing:
                thin.append(record)
            else:
                complete.append(record)

        print(f"\n{len(rows)} live pump model(s)")
        print(f"   {len(placeholders)} placeholder(s) - no product was named on the page")
        print(f"   {len(thin)} with a real designation and empty specification group(s)")
        print(f"   {len(complete)} holding every group")

        print("\ngroup coverage:")
        for group in GROUPS:
            have = sum(
                1
                for _, _, _, missing, _ in [*placeholders, *thin, *complete]
                if group not in missing
            )
            print(f"   {group:15} {have:3} of {len(rows)}")

        if not args.placeholders:
            print(f"\n--- thin records, emptiest first ({len(thin)}) ---")
            print("    POST /pump-models/{id}/enrich, or the Find datasheet button\n")
            for vendor_name, code, _pump, missing, model in sorted(
                thin, key=lambda item: (-len(item[3]), item[0])
            )[: args.limit]:
                pct = (
                    f"{float(model.data_completeness_pct) * 100:.0f}%"
                    if model.data_completeness_pct is not None
                    else "  ? "
                )
                print(
                    f"   {pct:>5}  {vendor_name:26} {str(code)[:34]:34} "
                    f"missing: {', '.join(missing)}"
                )

        print(f"\n--- placeholders ({len(placeholders)}) ---")
        print("    Run a pump discovery seeded with the manufacturer's name; these have")
        print("    no designation to search for.\n")
        for vendor_name, code, _pump, _missing, _model in sorted(placeholders)[: args.limit]:
            print(f"   {vendor_name:26} {code}")

        print(
            f"\ntracked fields per model: {completeness.MODEL_TRACKED} "
            f"({completeness.TRACKED_SPEC_FIELDS} across the six specification groups)"
        )
        unknown = sum(
            1
            for _, _, _, _, model in [*thin, *placeholders]
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
