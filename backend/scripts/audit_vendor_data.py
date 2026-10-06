"""Is the vendor data correct, and is it complete? Read-only; writes nothing.

    python -m scripts.audit_vendor_data                  # every live vendor, summary first
    python -m scripts.audit_vendor_data --vendor Amarinth  # one record, in full
    python -m scripts.audit_vendor_data --problems        # only the records with findings
    python -m scripts.audit_vendor_data --strict          # exit 1 if anything is wrong

"Correct" and "complete" are different questions and this answers both separately.

**Complete** is countable: of the fields this platform tracks for a supplier, how many
hold a value, and which ones do not. That is `data_completeness_pct` and the named gaps
behind it - no judgement involved.

**Correct** cannot be answered by looking at a value; it is answered by looking at what
is behind the value. Six checks, each one derived from a mistake actually found in this
database:

* **traceable** - a stored value with no provenance row. Nobody can say where it came
  from, which is the one thing this platform promises never to allow.
* **evidence supports the value** - the quote behind a value has to contain it. The
  record that said "approved" because its page quoted an ISO 9001 certificate would have
  been caught here: the quote is real, and it does not say what the value claims.
* **the website belongs to the company** - a domain that looks nothing like the name is
  usually a distributor's catalogue. One Flowserve record's only page was `abset.com`.
* **the source is the company's own** - a value read off an aggregator is a weaker claim
  than the same value on the manufacturer's site, and worth seeing as such.
* **countries are real** - ISO 3166-1 alpha-2, and `country` mirroring `hq_country`.
* **governance is a person's** - approved with no approver, an approval past its expiry,
  or a status written by the extractor rather than decided by somebody.

A finding is not automatically an error. "No provenance" on a hand-entered record is
expected. The point is that every value can be accounted for, and that the ones that
cannot are visible rather than assumed.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.countries import COUNTRIES
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.models.ai import FieldProvenance
from app.models.enums import ValueOrigin, VendorApprovalStatus
from app.models.source import Source
from app.models.vendor import Vendor
from app.services import completeness, vendor_discovery

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

AI_ORIGINS = {
    ValueOrigin.AI_EXTRACTION,
    ValueOrigin.AI_INFERENCE,
    ValueOrigin.AI_NORMALIZATION,
}

#: Fields whose stored value should appear in its own evidence quote.
#:
#: Not every field can be checked this way. `hq_country` is stored as "GB" from a quote
#: saying "United Kingdom", and `vendor_tier` as `tier_2_oem` from prose - both correct,
#: neither a literal match. These are the ones where the value is the words.
QUOTE_CHECKED = {
    "hq_city",
    "employee_count",
    "annual_revenue_usd",
    "revenue_year",
    "credit_rating",
    "credit_rating_agency",
    "total_units_supplied",
    "vendor_category",
}

#: Values older than this are worth re-reading before anyone relies on them.
STALE_AFTER = timedelta(days=180)


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def quote_supports(value: str, quote: str) -> bool:
    """Whether a quote actually says the value that was stored from it.

    Numbers are compared on their digits: a page writing "1,200 employees" supports the
    stored 1200, and "USD 45 million" supports 45000000 only if the digits are there,
    which they are not - so a converted figure is reported rather than assumed good.
    """
    if not value or not quote:
        return False
    if _squash(value) in _squash(quote):
        return True
    digits = re.sub(r"\D", "", value)
    return bool(digits) and digits in re.sub(r"\D", "", quote)


def audit_vendor(db, vendor: Vendor, contacts: int) -> dict:
    """Every finding for one record, plus how complete it is."""
    findings: list[tuple[str, str]] = []

    rows = db.scalars(
        select(FieldProvenance).where(
            FieldProvenance.entity_type == "vendors",
            FieldProvenance.entity_id == vendor.id,
        )
    ).all()
    by_field = {row.field_name: row for row in rows}

    # ---- traceable ----------------------------------------------------------
    for name in completeness.VENDOR_FIELDS:
        value = getattr(vendor, name, None)
        if name == "vendor_tier":
            tier = getattr(value, "value", value)
            if not tier or tier == "unclassified":
                continue
        elif not completeness.is_recorded(value):
            continue
        if name not in by_field:
            findings.append(("traceable", f"{name} holds a value with no provenance row"))

    # ---- the evidence says what the value says -------------------------------
    for name, row in by_field.items():
        if name not in QUOTE_CHECKED or row.value_origin not in AI_ORIGINS:
            continue
        if not row.evidence_quote:
            findings.append(("evidence", f"{name} was written with no quote"))
        elif not quote_supports(row.value_text or "", row.evidence_quote):
            findings.append(
                (
                    "evidence",
                    f"{name} = {row.value_text!r} is not in its quote "
                    f"{row.evidence_quote[:70]!r}",
                )
            )

    # ---- the website belongs to the company ----------------------------------
    if vendor.website:
        if not vendor.website.startswith(("http://", "https://")):
            # A browser reads a bare host as a relative path, so the link on the profile
            # points inside this application rather than at the supplier.
            findings.append(
                ("website", f"{vendor.website!r} has no https:// and is not a working link")
            )
        host = vendor_discovery.domain_of(vendor.website) or ""
        label = vendor_discovery.domain_name_part(host)
        if any(part in host for part in vendor_discovery.AGGREGATOR_HOSTS):
            findings.append(("website", f"{host} is a directory, not a company site"))
        elif len(label) < 4:
            # `hms.biz` for HMS Group: too short to tell ownership from coincidence, so
            # saying nothing is more honest than either verdict.
            pass
        elif not vendor_discovery.domain_matches_name(host, vendor.name):
            findings.append(
                ("website", f"{host} does not look like a domain belonging to {vendor.name}")
            )

    # ---- what the values were read from --------------------------------------
    source_ids = {row.source_id for row in rows if row.source_id}
    if vendor.primary_source_id:
        source_ids.add(vendor.primary_source_id)
    aggregator_reads = 0
    newest_capture: datetime | None = None
    sources = (
        db.scalars(select(Source).where(Source.id.in_(source_ids))).all() if source_ids else []
    )
    for source in sources:
        host = vendor_discovery.domain_of(source.source_url) or ""
        if any(part in host for part in vendor_discovery.AGGREGATOR_HOSTS):
            aggregator_reads += 1
        if source.captured_at and (newest_capture is None or source.captured_at > newest_capture):
            newest_capture = source.captured_at
    if aggregator_reads:
        findings.append(
            ("source", f"{aggregator_reads} value(s) read from a directory rather than the company")
        )
    if newest_capture and datetime.now(UTC) - newest_capture > STALE_AFTER:
        findings.append(("stale", f"nothing re-read since {newest_capture.date()}"))

    # ---- countries -----------------------------------------------------------
    for name in ("hq_country", "country"):
        code = getattr(vendor, name, None)
        if code and code.upper() not in COUNTRIES:
            findings.append(("country", f"{name} = {code!r} is not an ISO 3166-1 code"))
    if vendor.country and vendor.hq_country and vendor.country != vendor.hq_country:
        findings.append(
            ("country", f"country {vendor.country} and hq_country {vendor.hq_country} disagree")
        )

    # ---- governance ----------------------------------------------------------
    status = getattr(vendor.approval_status, "value", vendor.approval_status)
    approvals = {
        VendorApprovalStatus.APPROVED.value,
        VendorApprovalStatus.CONDITIONALLY_APPROVED.value,
    }
    if status in approvals and vendor.approved_by_user_id is None:
        findings.append(("governance", f"{status} with nobody recorded as having decided it"))
    if vendor.approval_expiry and vendor.approval_expiry < date.today():
        findings.append(("governance", f"approval lapsed on {vendor.approval_expiry}"))
    for name in ("approval_status", "sanctions_status"):
        row = by_field.get(name)
        if row and row.value_origin in AI_ORIGINS:
            findings.append(
                ("governance", f"{name} was written by the extractor, not decided by a person")
            )

    return {
        "vendor": vendor,
        "findings": findings,
        "completeness": completeness.vendor_completeness(vendor, contact_count=contacts),
        "gaps": completeness.vendor_gaps(vendor, contact_count=contacts),
        "provenance_rows": len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", help="audit only vendors whose name contains this")
    parser.add_argument("--problems", action="store_true", help="hide records with no findings")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any finding is reported")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many records")
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        query = select(Vendor).where(Vendor.deleted_at.is_(None)).order_by(Vendor.name)
        if args.vendor:
            query = query.where(Vendor.name.ilike(f"%{args.vendor}%"))
        vendors = list(db.scalars(query).all())
        if args.limit:
            vendors = vendors[: args.limit]

        contacts = completeness.contact_counts(db, [v.id for v in vendors])
        reports = [audit_vendor(db, v, contacts.get(v.id, 0)) for v in vendors]

        kinds: Counter[str] = Counter()
        for report in reports:
            for kind, _ in report["findings"]:
                kinds[kind] += 1

        clean = sum(1 for r in reports if not r["findings"])
        filled = [r["completeness"] for r in reports if r["completeness"] is not None]
        average = sum(filled) / len(filled) if filled else 0

        print(f"\n{len(reports)} vendor(s) audited")
        print(f"   {clean} with no findings, {len(reports) - clean} with something to look at")
        print(f"   average completeness {float(average) * 100:.0f}%")
        if kinds:
            print("\nfindings by kind:")
            for kind, count in kinds.most_common():
                print(f"   {kind:12} {count}")

        print("\n" + "-" * 78)
        for report in reports:
            if args.problems and not report["findings"]:
                continue
            vendor = report["vendor"]
            pct = float(report["completeness"] or 0) * 100
            scope = "shared" if vendor.tenant_id is None else "tenant"
            print(f"\n{vendor.name}  [{scope}]  {pct:.0f}% complete, "
                  f"{report['provenance_rows']} traced field(s)")
            for kind, detail in report["findings"]:
                print(f"    ! {kind}: {detail}")
            if report["gaps"]:
                print(f"    missing: {', '.join(report['gaps'])}")

        problems = sum(kinds.values())

    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
