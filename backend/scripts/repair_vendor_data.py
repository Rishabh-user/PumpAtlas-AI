"""Correct what the vendor table already holds, and fill what can be filled for free.

    python -m scripts.repair_vendor_data            # dry run, writes nothing
    python -m scripts.repair_vendor_data --commit   # apply
    python -m scripts.repair_vendor_data --only qualification --commit

Four passes, each of which fixes something an audit of the live data turned up. None of
them calls an AI provider or fetches a page: every value written here already exists in
the database, and each one is written with the provenance that says where it came from.

**qualification** - `approval_status` is the *client's* decision about a supplier:
approved to bid, by whom, until when. The extractor was allowed to write it, so two
records said "approved" because their own websites said so - one quoting the single word
"approved", the other an ISO 9001 certificate, which is a quality certification and not
an approval to supply. Neither had an approver or an expiry. This resets them to
`pending_qualification`, keeps what the page claimed under
`extra.discovery.supplier_claims` with its quote, and removes the provenance rows that
justified a value no longer held. The extractor can no longer write those columns at all.

**shared_flag** - `is_shared_master` disagreed with `tenant_id` on every shared record:
47 rows sat in the shared master catalogue with the flag reading false, because only the
manual create path ever set it. The flag is now derived from the truth it was meant to
mirror.

**website** - a company's own site is the strongest statement of its website, and it is
almost never written out as text on its pages, so the extractor - told to quote or omit -
correctly omits it. 37 records were built from a page and hold no website. This writes
the page's own origin, with `CALCULATED` as the origin and the URL as its evidence, never
from a directory or a social profile.

**completeness** - `data_completeness_pct` is averaged by the quality dashboard, sorted
on by search and filtered on by `completeness_min`, and nothing ever computed it: it was
NULL on all 77 vendors and all 84 pump models. This fills it in for both, reindexing the
models (which is where a model's figure is now kept current).

Safe to re-run: every pass skips what it has already done.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.ai import FieldProvenance
from app.models.enums import (
    AuditAction,
    SanctionsScreeningStatus,
    ValueOrigin,
    VendorApprovalStatus,
)
from app.models.pump import PumpModel
from app.models.source import Source
from app.models.vendor import Vendor
from app.services import audit, completeness, indexing, provenance, vendor_discovery

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

PASSES = ("qualification", "shared_flag", "website", "website_scheme", "completeness")

#: The value each governance column carries until a person decides otherwise.
GOVERNANCE_DEFAULTS = {
    "approval_status": VendorApprovalStatus.PENDING_QUALIFICATION,
    "sanctions_status": SanctionsScreeningStatus.NOT_SCREENED,
}


def live_vendors(db) -> list[Vendor]:
    return list(
        db.scalars(select(Vendor).where(Vendor.deleted_at.is_(None)).order_by(Vendor.name)).all()
    )


def repair_qualification(db, vendors: list[Vendor]) -> list[str]:
    """Take back the governance statuses the extractor wrote."""
    notes: list[str] = []
    for vendor in vendors:
        rows = db.scalars(
            select(FieldProvenance).where(
                FieldProvenance.entity_type == "vendors",
                FieldProvenance.entity_id == vendor.id,
                FieldProvenance.field_name.in_(GOVERNANCE_DEFAULTS),
            )
        ).all()
        ai_written = [
            row
            for row in rows
            if row.value_origin
            in (ValueOrigin.AI_EXTRACTION, ValueOrigin.AI_INFERENCE, ValueOrigin.AI_NORMALIZATION)
        ]
        if not ai_written:
            continue

        before = audit.snapshot(vendor)
        claims = {}
        for row in ai_written:
            current = getattr(vendor, row.field_name, None)
            current_value = getattr(current, "value", current)
            default = GOVERNANCE_DEFAULTS[row.field_name]
            claims[row.field_name] = {
                "value": current_value,
                "quote": row.evidence_quote,
                "claimed_at": (row.created_at or datetime.now(UTC)).isoformat(),
                "source_id": str(row.source_id) if row.source_id else None,
            }
            if current_value != default.value:
                setattr(vendor, row.field_name, default)
                notes.append(f"{vendor.name}: {row.field_name} {current_value} -> {default.value}")
            # The row justified a value the record no longer holds. Leaving it would
            # make the profile page cite evidence for a status nobody can see.
            db.delete(row)

        extra = dict(vendor.extra or {})
        discovery = dict(extra.get("discovery") or {})
        existing = dict(discovery.get("supplier_claims") or {})
        existing.update(claims)
        discovery["supplier_claims"] = existing
        extra["discovery"] = discovery
        vendor.extra = extra

        db.flush()
        audit.record_audit(
            db,
            action=AuditAction.UPDATE,
            entity_type="vendors",
            entity_id=vendor.id,
            entity_label=vendor.name,
            summary=(
                "Qualification status returned to pending: a supplier's own page is a "
                "claim, not this organisation's approval decision"
            ),
            changes={name: claim["value"] for name, claim in claims.items()},
            tenant_id=vendor.tenant_id,
            actor_type="system",
        )
        audit.record_version(
            db,
            obj=vendor,
            operation="update",
            before=before,
            change_reason="scripts.repair_vendor_data: qualification reset",
        )
    return notes


def repair_shared_flag(db, vendors: list[Vendor]) -> list[str]:
    notes = []
    for vendor in vendors:
        should_be = vendor.tenant_id is None
        if vendor.is_shared_master != should_be:
            vendor.is_shared_master = should_be
            notes.append(f"{vendor.name}: is_shared_master -> {should_be}")
    return notes


def repair_website(db, vendors: list[Vendor]) -> list[str]:
    """Give a record the address of the page it was built from."""
    notes = []
    for vendor in vendors:
        if vendor.website or vendor.primary_source_id is None:
            continue
        source = db.get(Source, vendor.primary_source_id)
        derived = vendor_discovery.website_from_url(
            source.source_url if source else None, vendor.name
        )
        if not derived:
            continue

        before = audit.snapshot(vendor)
        report = provenance.apply_fields(
            db,
            vendor,
            {"website": derived},
            provenance.ProvenanceContext(
                origin=ValueOrigin.CALCULATED,
                confidence_level=vendor.confidence_level,
                source_id=source.id,
                tenant_id=vendor.tenant_id,
                normalization_note="Derived from the URL of the page this record was built from",
            ),
            evidence={"website": f"Derived from the captured page URL: {source.source_url}"},
        )
        if not report.get("applied"):
            continue
        notes.append(f"{vendor.name}: website -> {derived}")
        db.flush()
        audit.record_version(
            db,
            obj=vendor,
            operation="update",
            before=before,
            change_reason="scripts.repair_vendor_data: website derived from the captured page",
        )
    return notes


def repair_website_scheme(db, vendors: list[Vendor]) -> list[str]:
    """Make the stored addresses into links.

    Five records held a bare host - `www.handolpumps.com` - which a browser reads as a
    relative path, so the "Vendor website" button pointed inside this application instead
    of at the supplier. Not a new fact about the company, so it is corrected in place
    rather than written as a new value: the provenance still points at the page that
    stated the address, which is what it did before.
    """
    notes = []
    for vendor in vendors:
        website = (vendor.website or "").strip()
        if not website or website.startswith(("http://", "https://")):
            continue
        fixed = vendor_discovery.website_from_url(f"https://{website.lstrip('/')}")
        if not fixed:
            notes.append(f"{vendor.name}: {website!r} is not a web address - left alone")
            continue
        vendor.website = fixed
        notes.append(f"{vendor.name}: {website} -> {fixed}")
    return notes


def repair_completeness(db, vendors: list[Vendor]) -> list[str]:
    """Fill in the figure the dashboard has always averaged to nothing."""
    values = completeness.refresh_vendors(db, vendors)
    # Stored as a fraction of one; shown here the way a person reads it.
    filled = [
        f"{v.name}: {float(values[v.id]) * 100:.0f}%"
        for v in vendors
        if values.get(v.id) is not None
    ]

    model_ids = list(db.scalars(select(PumpModel.id).where(PumpModel.deleted_at.is_(None))).all())
    for model_id in model_ids:
        indexing.reindex_pump_model(db, model_id)
    filled.append(f"{len(model_ids)} pump model(s) reindexed, each with its own figure")
    return filled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the changes")
    parser.add_argument(
        "--only", choices=PASSES, action="append", help="run only this pass; repeatable"
    )
    args = parser.parse_args()
    wanted = args.only or list(PASSES)

    with tenant_session(None, is_platform_admin=True) as db:
        vendors = live_vendors(db)
        print(f"{len(vendors)} live vendor(s)\n")

        for name, fn in (
            ("qualification", repair_qualification),
            ("shared_flag", repair_shared_flag),
            ("website", repair_website),
            ("website_scheme", repair_website_scheme),
            ("completeness", repair_completeness),
        ):
            if name not in wanted:
                continue
            notes = fn(db, vendors)
            print(f"--- {name}: {len(notes)} change(s) ---")
            for note in notes[:25]:
                print(f"    {note}")
            if len(notes) > 25:
                print(f"    ... and {len(notes) - 25} more")

        if args.commit:
            db.commit()
            print("\ncommitted")
        else:
            db.rollback()
            print("\ndry run - nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
