"""Find the pump models stored under a category name instead of a product name.

    python -m scripts.flag_category_models            # dry run, writes nothing
    python -m scripts.flag_category_models --commit   # raise the flags

An API 610 type code names a configuration, not a product. Thirteen models in this
database are called "OH1", "BB2", "VS6", "API 675" - they came from category landing
pages before the gate that now refuses them, and each one says a manufacturer makes a
pump called "OH1", which is true of every manufacturer and useful to nobody.

They are **flagged, not deleted**. A record captured from a real page usually carries
real specifications - a duty point, a standard, materials - and the only thing wrong with
it is its name. Deleting it throws that away; renaming it needs a name only a person
reading the page can supply. So each one gets an unresolved data-quality flag naming the
problem and the fix, which puts it on the quality dashboard and on the vendor profile
where somebody can act on it.

Re-running replaces this detector's own unresolved flags and leaves every other flag
alone, so it is safe to run repeatedly.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.enums import DataQualityFlagType, FlagSeverity
from app.models.pump import Pump, PumpModel
from app.models.vendor import Vendor
from app.services import designations, quality

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

DETECTED_BY = "designation_check"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the flags")
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        rows = db.execute(
            select(PumpModel, Pump.name, Vendor.name, Vendor.tenant_id)
            .join(Pump, Pump.id == PumpModel.pump_id)
            .join(Vendor, Vendor.id == Pump.vendor_id)
            .where(PumpModel.deleted_at.is_(None))
            .order_by(Vendor.name)
        ).all()

        flagged = 0
        for model, pump_name, vendor_name, tenant_id in rows:
            designation = designations.classify(model.model_code)
            if not designation.is_category_only:
                continue

            flagged += 1
            type_code = designation.api_610_type_code or "the type"
            print(f"   {vendor_name:34} {model.model_code!r}  (product line: {pump_name})")
            quality.persist_findings(
                db,
                tenant_id=tenant_id,
                entity_type="pump_models",
                entity_id=model.id,
                findings=[
                    quality.Finding(
                        flag_type=DataQualityFlagType.SUSPICIOUS_VALUE,
                        severity=FlagSeverity.HIGH,
                        message=(
                            f"{model.model_code!r} is an API 610 configuration, not a model "
                            f"designation. This record came from a page about "
                            f"{type_code} pumps in general, so it does not identify a "
                            f"product {vendor_name} sells."
                        ),
                        field_name="model_code",
                        detected_value=str(model.model_code),
                        suggested_fix=(
                            "Rename it to the designation the manufacturer uses, or remove "
                            "it if the page named no product."
                        ),
                    )
                ],
                detected_by=DETECTED_BY,
            )

        print(f"\n{flagged} of {len(rows)} live pump model(s) named after a category")
        if args.commit:
            db.commit()
            print("flags raised - they appear on the quality dashboard and the vendor profile")
        else:
            db.rollback()
            print("dry run - nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
