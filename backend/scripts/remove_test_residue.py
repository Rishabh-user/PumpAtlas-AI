"""Remove the records the live integration tests leave behind.

``tests/test_live_integration.py`` proves tenant isolation by creating two throwaway
tenants and writing a vendor into each, and proves versioning by writing pump records
with generated names. It never cleaned up, so a database that has run those tests shows
rows like *"Confidential Rival Vendor rival-epc-0e90c3"* and *"Ruhrpumpen c973f8 GmbH"*
in the vendor list, indistinguishable to a reader from real supply-chain data.

    python -m scripts.remove_test_residue            # dry run, writes nothing
    python -m scripts.remove_test_residue --commit   # apply

What it does, and does not do:

* Soft-deletes, exactly as ``DELETE /vendors/{id}`` does: sets ``deleted_at``, writes an
  audit row and reindexes. Every list and search filters on ``deleted_at``, so the rows
  leave the UI while the audit history of them existing stays intact. A record that
  quietly vanishes from a system of record is worse than one marked as removed.
* Suspends the two test tenants rather than deleting them, which is what the platform's
  own tenant endpoint does for the same reason.
* Matches on name patterns that only the tests generate, never on "not AI-extracted".
  Those are different questions: a hand-entered vendor is legitimate data, and deleting
  by origin would take the real ones with the fake.

Safe to re-run: anything already soft-deleted is skipped.
"""

from __future__ import annotations

import argparse
import re
import sys

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.enums import AuditAction, TenantStatus
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.models.tenant import Tenant
from app.models.user import User
from app.models.vendor import Vendor
from app.services import audit, indexing

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

#: Names only the live tests produce.
#:
#: `test_live_integration.py` builds each throwaway tenant as `rival-epc-<6 hex>` and
#: names its vendor after it; `sample_payload` defaults to "Sulzer Pumps Ltd"; the
#: versioning tests append 6 hex characters to a manufacturer name to keep runs unique.
#: The hex suffix is what makes these safe to match on - a real record does not carry one.
TEST_VENDOR_PATTERNS = (
    re.compile(r"^Confidential Rival Vendor rival-epc-[0-9a-f]{6}$"),
    re.compile(r"^Sulzer Pumps Ltd$"),
    re.compile(r"^\w[\w.\- ]* [0-9a-f]{6} (GmbH|Ltd|Inc|AS|SA|BV)$"),
)

#: Tenants the isolation tests create. Never a real client: the slug carries the suffix.
TEST_TENANT_PATTERN = re.compile(r"^rival-epc-[0-9a-f]{6}$")


def is_test_vendor(name: str) -> bool:
    return any(pattern.match(name or "") for pattern in TEST_VENDOR_PATTERNS)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.remove_test_residue")
    parser.add_argument(
        "--commit", action="store_true", help="apply the removals (otherwise dry run)"
    )
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        tenants = {tenant.id: tenant for tenant in db.scalars(select(Tenant)).all()}

        vendors = [
            vendor
            for vendor in db.scalars(
                select(Vendor).where(Vendor.deleted_at.is_(None)).order_by(Vendor.created_at)
            ).all()
            if is_test_vendor(vendor.name)
        ]
        test_tenants = [
            tenant
            for tenant in tenants.values()
            if TEST_TENANT_PATTERN.match(tenant.slug or "")
            and tenant.status is not TenantStatus.SUSPENDED
        ]

        if not vendors and not test_tenants:
            print("No test vendors or tenants found; checking the search index anyway.")

        removed_models = 0
        removed_pumps = 0
        for vendor in vendors:
            owner = tenants.get(vendor.tenant_id)
            pumps = db.scalars(
                select(Pump).where(Pump.vendor_id == vendor.id, Pump.deleted_at.is_(None))
            ).all()
            models = (
                db.scalars(
                    select(PumpModel).where(
                        PumpModel.pump_id.in_([pump.id for pump in pumps]),
                        PumpModel.deleted_at.is_(None),
                    )
                ).all()
                if pumps
                else []
            )
            print(
                f"{'remove' if args.commit else 'would remove'}: {vendor.name}"
                f"  [tenant {owner.slug if owner else 'shared'},"
                f" {len(pumps)} pump(s), {len(models)} model(s),"
                f" {getattr(vendor.confidence_level, 'value', '-')}]"
            )
            for model in models:
                print(f"      model {model.model_code}")

            if not args.commit:
                continue

            # Children first, so nothing is left pointing at a removed parent.
            for model in models:
                model.deleted_at = func.now()
                removed_models += 1
            for pump in pumps:
                pump.deleted_at = func.now()
                removed_pumps += 1
            db.flush()
            # Per model, not just the vendor: `reindex_pump_model` is what drops a search
            # row for a deleted model, and `reindex_vendor` refreshes the ones that
            # remain. Reindexing only the vendor left the deleted models searchable.
            for model in models:
                indexing.reindex_pump_model(db, model.id)
            vendor.deleted_at = func.now()
            audit.record_audit(
                db,
                action=AuditAction.DELETE,
                entity_type="vendors",
                entity_id=vendor.id,
                entity_label=vendor.name,
                summary="Removed as live-integration-test residue",
                tenant_id=vendor.tenant_id,
                context={"pumps": len(pumps), "models": len(models)},
                actor_type="system",
            )
            db.flush()
            # Drops it from search: the index filters on `deleted_at`.
            indexing.reindex_vendor(db, vendor.id)

        for tenant in test_tenants:
            users = db.scalars(select(User).where(User.tenant_id == tenant.id)).all()
            print(
                f"{'suspend' if args.commit else 'would suspend'}: tenant {tenant.slug}"
                f"  [{len(users)} user(s)]"
            )
            if not args.commit:
                continue
            tenant.status = TenantStatus.SUSPENDED
            for user in users:
                user.is_active = False
            audit.record_audit(
                db,
                action=AuditAction.TENANT_CHANGE,
                entity_type="tenants",
                entity_id=tenant.id,
                entity_label=tenant.name,
                summary="Test tenant suspended and its users deactivated as test residue",
                tenant_id=tenant.id,
                actor_type="system",
            )

        # Repair pass: a search row whose pump model is gone or soft-deleted. Standalone
        # because an earlier removal that reindexed only the vendor stranded rows like
        # "Confidential Rival Vendor ... SECRET-836697", still fully searchable.
        stranded = [
            row
            for row in db.scalars(select(SearchIndex)).all()
            if (model := db.get(PumpModel, row.pump_model_id)) is None
            or model.deleted_at is not None
        ]
        for row in stranded:
            print(
                f"{'drop' if args.commit else 'would drop'} stale search row: " f"{row.label[:70]}"
            )
            if args.commit:
                indexing.reindex_pump_model(db, row.pump_model_id)

        if args.commit:
            db.commit()
            print(
                f"\nRemoved {len(vendors)} vendor(s), {removed_pumps} pump(s), "
                f"{removed_models} model(s); suspended {len(test_tenants)} tenant(s)."
            )
            print("Soft deleted, so the audit history of them is intact.")
        else:
            print("\nDRY RUN - nothing written (pass --commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
