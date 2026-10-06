"""AI vendor discovery: what makes it *vendor* discovery.

The engine — Parallel AI search, source capture, per-page Gemma screening, run progress —
lives in :mod:`app.services.discovery` and is shared with pump discovery. This module is
the vendor half: the search objective, the screening prompt, the columns a stored
candidate may write, and the write itself.

A discovered supplier becomes a ``vendors`` row and nothing more. No pump or pump model
is invented for it: that waits for a datasheet.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import insert, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.parallel_search import (
    country_segments,
    pump_type_segments,
    vendor_discovery_objective,
)
from app.core.logging import get_logger
from app.models.ai import ExtractedEntity
from app.models.enums import ReviewDecision, ValueOrigin, VerificationStatus
from app.models.source import ImportBatch, Source
from app.models.vendor import Vendor, VendorContact
from app.services import audit, completeness, dedupe, provenance
from app.services.discovery import DiscoveryKind
from app.services.promotion import (
    PromotionError,
    fold_accents,
    is_usable_subject_name,
    normalize_company_name,
    resolve_vendor,
)

log = get_logger(__name__)

KIND = DiscoveryKind(
    slug="vendor",
    entity_type="vendors",
    noun="supplier",
    screen_label="Screen and profile suppliers",
    run_name="AI vendor discovery",
    build_objective=vendor_discovery_objective,
    system_prompt=prompts.SYSTEM_VENDOR_PROFILE,
    build_user_prompt=prompts.build_vendor_profile_prompt,
    relevance_key="is_oil_gas_pump_vendor",
    subject_keys=("vendor_name",),
    # Vendors sweep by country by default. Sweeping pump types returns the same global
    # OEMs from every angle; the suppliers this platform does not already know are
    # regional, and country is the axis that reaches them.
    sweep_segments=country_segments,
    sweep_scopes={"country": country_segments, "pump_type": pump_type_segments},
)

ENTITY_TYPE = KIND.entity_type
IMPORT_MODE = KIND.import_mode


VENDOR_PROFILE_FIELDS: dict[str, str] = {
    "website": "website",
    "hq_country": "hq_country",
    "hq_city": "hq_city",
    "description": "description",
    "vendor_tier": "vendor_tier",
    "vendor_category": "vendor_category",
    "product_families": "product_families",
    "manufacturing_countries": "manufacturing_countries",
    "annual_revenue_usd": "annual_revenue_usd",
    "revenue_year": "revenue_year",
    "employee_count": "employee_count",
    "credit_rating": "credit_rating",
    "credit_rating_agency": "credit_rating_agency",
    "total_units_supplied": "total_units_supplied",
    "on_time_delivery_pct": "on_time_delivery_pct",
    "fpso_offshore_experience": "fpso_offshore_experience",
}

#: Fields the model may return that describe the vendor but have no column of their own.
#: They are preserved on ``Vendor.extra`` rather than dropped.
VENDOR_EXTRA_FIELDS = ("certifications", "notable_references", "legal_entity_name")

#: Governance columns a supplier's own website may not set.
#:
#: `approval_status` and `sanctions_status` read as the *client's* decision about a
#: supplier - approved to bid, screened against sanctions lists, by whom and until when.
#: What a supplier's page states is its own claim about itself, and the two are not the
#: same thing. Two records in this database show why: one page said the word "approved"
#: and the record became "approved"; another quoted an ISO 9001 certificate, which is a
#: quality certification and not an approval to supply, and that record became "approved"
#: too. Neither had an approver or an expiry, and both sat in the vendor list beside
#: genuine decisions.
#:
#: So the claim is recorded - under `extra.discovery.supplier_claims`, with the quote
#: that carried it, because a supplier saying it is an approved vendor is worth knowing -
#: and the column stays `pending_qualification` until a person qualifies the supplier.
VENDOR_CLAIM_FIELDS = ("approval_status", "sanctions_status")


def blocked_reason(subject: dict, fields: dict) -> str | None:
    """Why storing this candidate would fail, or None. Mirrors `store_candidate`."""
    name = subject.get("vendor_name")
    if not name:
        return "Gemma did not identify a supplier name on this page."
    if not is_usable_subject_name(name):
        return f"{name!r} is not a usable supplier name. Correct it before storing."
    return None


def existing_vendor_for(db: Session, tenant_id: uuid.UUID | None, name: str) -> Vendor | None:
    """The vendor a candidate would merge into, so the UI can say so before storing."""
    if not name:
        return None
    normalized = normalize_company_name(name)
    for scope in (tenant_id, None):
        found = db.scalar(
            select(Vendor).where(
                Vendor.tenant_id == scope,
                Vendor.normalized_name == normalized,
                Vendor.deleted_at.is_(None),
                Vendor.merged_into_vendor_id.is_(None),
            )
        )
        if found is not None:
            return found
    return None


def existing_vendors_for(
    db: Session, tenant_id: uuid.UUID | None, names: Iterable[str]
) -> dict[str, Vendor]:
    """The same lookup as :func:`existing_vendor_for`, for many names in two queries.

    The discovery poll asks this question once per candidate, and the database is remote:
    at a third of a second per round trip, thirty candidates asked one at a time cost
    twenty seconds. Keyed by normalised name; tenant rows win over global ones.
    """
    normalized = {normalize_company_name(name) for name in names if name}
    normalized.discard("")
    if not normalized:
        return {}

    found: dict[str, Vendor] = {}
    # Global scope first so the tenant's own rows overwrite it, matching the
    # (tenant_id, None) precedence of the single-name lookup.
    for scope in (None, tenant_id):
        rows = db.scalars(
            select(Vendor).where(
                Vendor.tenant_id == scope,
                Vendor.normalized_name.in_(normalized),
                Vendor.deleted_at.is_(None),
                Vendor.merged_into_vendor_id.is_(None),
            )
        ).all()
        for vendor in rows:
            found[vendor.normalized_name] = vendor
    return found


def _website_from_source(
    db: Session, entity: ExtractedEntity, vendor_name: str | None = None
) -> str | None:
    """The origin of the page this candidate was read from, if it looks like a company site.

    Aggregators are excluded: reading a supplier off a directory listing does not make
    that directory the supplier's website, and a wrong website on a vendor record sends
    somebody to the wrong company.
    """
    if entity.source_id is None:
        return None
    source = db.get(Source, entity.source_id)
    return website_from_url(source.source_url if source else None, vendor_name)


def _letters(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def domain_name_part(host: str) -> str:
    """The part of a host that names the organisation, without the public suffix.

    `pumpi.com.mk` is Pumpi, `apollo-goessnitz.de` is Apollo Goessnitz, and
    `pumpcatalog.dickow.com` is Dickow. Done by dropping the short trailing labels
    rather than by carrying a public-suffix list, which would be a dependency and a
    monthly update for a judgement that only has to be roughly right.
    """
    labels = [label for label in (host or "").lower().split(".") if label]
    while len(labels) > 1 and len(labels[-1]) <= 3:
        labels.pop()
    # The last remaining label is the registered one; anything to its left is a
    # subdomain the company chose, and `pumpcatalog.dickow.com` is Dickow's.
    return _letters(labels[-1] if labels else "")


def domain_matches_name(host: str, vendor_name: str) -> bool:
    """Whether a domain plausibly belongs to the company named.

    A record built from a page does not make that page's owner the company. The audit
    that prompted this found a Flowserve record whose only captured page was
    `abset.com` - a distributor's catalogue listing Flowserve pumps - and deriving a
    website from it would have put a buyer through to the wrong company, which is the
    same mistake the contact rule exists to prevent.

    Substring either way, because a company writes its domain both shorter than its
    legal name (`dickow.com` for Dickow Pump Co.) and longer (`apollo-goessnitz.de` for
    Apollo). Four characters minimum: below that, coincidence is likelier than ownership.
    """
    # Accents are folded first: "Apollo Gößnitz GmbH" against apollo-goessnitz.de is the
    # same company, and comparing the raw letters drops the ö and ß and matches nothing.
    site = domain_name_part(host)
    name = _letters(fold_accents(vendor_name))
    if len(site) < 4 or len(name) < 4:
        return False
    return site in name or name in site


def website_from_url(url: str | None, vendor_name: str | None = None) -> str | None:
    """A page's own origin, when the page looks like the company's own site.

    Separate from the candidate path because the same judgement is needed when filling
    in a record captured before that path existed - and both must reach the same answer,
    or a backfill would write websites the live path would have refused.

    `vendor_name` is optional only because one caller knows the name later than the
    other; when it is given, a domain that does not look like the company's is refused.
    """
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if not host or not parsed.scheme:
        return None
    if any(part in host for part in AGGREGATOR_HOSTS):
        return None
    if vendor_name and not domain_matches_name(host, vendor_name):
        return None
    return f"https://{host}"


#: Hosts that list companies rather than being one. Not exhaustive - it does not need to
#: be, because the cost of a miss is one derived website a reviewer can correct, and the
#: alternative is deriving nothing at all.
AGGREGATOR_HOSTS = (
    "linkedin",
    "facebook",
    "twitter",
    "x.com",
    "youtube",
    "wikipedia",
    "scribd",
    "slideshare",
    "indiamart",
    "alibaba",
    "made-in-china",
    "tradeindia",
    "exportersindia",
    "thomasnet",
    "globalspec",
    "directindustry",
    "europages",
    "kompass",
    "bloomberg",
    "crunchbase",
    "zoominfo",
    "dnb.com",
    "opencorporates",
    "medium.com",
    "wordpress",
    "blogspot",
)


#: Whether `vendor_contacts` carries the provenance columns yet.
#:
#: Cached per process: it is a catalogue lookup, and the answer only changes when
#: somebody applies a migration, which restarts the service anyway. Until
#: `002_vendor_contact_provenance.sql` is applied there is nowhere to record where a
#: contact came from, so auto-recording is skipped rather than writing an untraceable
#: phone number into a procurement file.
_CONTACT_PROVENANCE_READY: bool | None = None


def contact_provenance_available(db: Session) -> bool:
    global _CONTACT_PROVENANCE_READY
    if _CONTACT_PROVENANCE_READY is None:
        columns = {
            column["name"] for column in sa_inspect(db.get_bind()).get_columns("vendor_contacts")
        }
        _CONTACT_PROVENANCE_READY = {"source_id", "captured_at", "origin"} <= columns
        if not _CONTACT_PROVENANCE_READY:
            log.warning(
                "vendor_discovery.contact_provenance_missing",
                hint=(
                    "Apply db/migrations/002_vendor_contact_provenance.sql as the schema "
                    "owner to record contact details found on a page."
                ),
            )
    return _CONTACT_PROVENANCE_READY


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def phone_key(value: str | None) -> str:
    """What makes two written phone numbers the same line.

    Digits alone are not enough. A British page writes its switchboard
    "+44 (0)1394 462 120": the parenthesised zero is the trunk code you dial *instead
    of* the country code, never part of the international number. Someone who had
    already recorded "+44 1394 462120" by hand would otherwise be offered it a second
    time, and the page would list one company's one telephone twice.

    Only a bracketed zero is dropped, and only there - every other digit is kept, so two
    genuinely different extensions stay different.
    """
    return _digits(re.sub(r"\(\s*0\s*\)", "", value or ""))


#: The columns migration 002 adds. Named here because the application has to read
#: `vendor_contacts` whether or not that migration has been applied yet: the model
#: declares them, and an ORM entity load asks for every mapped column, so a database
#: without them answers "column vendor_contacts.source_id does not exist" - and the
#: vendor profile, which lists contacts, goes with it.
CONTACT_PROVENANCE_COLUMNS = frozenset({"source_id", "captured_at", "origin"})


def contact_rows(db: Session, vendor_id: uuid.UUID) -> list[dict]:
    """A vendor's contacts, read through the columns this database actually has.

    Always the full set of keys, with `None` for anything the schema is missing, so a
    caller never has to know which state the database is in.
    """
    table = VendorContact.__table__
    if contact_provenance_available(db):
        columns = list(table.c)
    else:
        columns = [c for c in table.c if c.name not in CONTACT_PROVENANCE_COLUMNS]

    absent = {name: None for name in CONTACT_PROVENANCE_COLUMNS}
    return [
        {**absent, **dict(row)}
        for row in db.execute(
            select(*columns).where(table.c.vendor_id == vendor_id)
        ).mappings()
    ]


def insert_contact(db: Session, **values) -> uuid.UUID:
    """Write one contact through the columns this database has, and return its id.

    Core rather than the ORM, for the same reason `contact_rows` reads columns: an ORM
    insert sends every mapped column, so a database still waiting for migration 002 is
    told about `source_id` and refuses the row. That would break adding a contact by
    hand - the very button this work was meant to make unnecessary, and the one that has
    to keep working while a person is the only one recording anything.
    """
    if not contact_provenance_available(db):
        values = {
            name: value
            for name, value in values.items()
            if name not in CONTACT_PROVENANCE_COLUMNS
        }
    contact_id = values.setdefault("id", uuid.uuid4())
    db.execute(insert(VendorContact.__table__).values(**values))
    return contact_id


def record_page_contacts(db: Session, vendor: Vendor, source: Source | None) -> int:
    """Record the email addresses and phone numbers a page states for this supplier.

    Only details from the company's *own* domain. A supplier's page routinely lists its
    distributors: one Amarinth page carried `global@mopartners.global` and a Brazilian
    number belonging to a partner, and writing those onto Amarinth would put another
    company's switchboard in this company's file. Off-domain details are still captured
    on the source and offered for a person to accept.

    Each contact records the page it came from, so it is as traceable as every other
    stored value.
    """
    if source is None or not contact_provenance_available(db):
        return 0

    captured = (source.source_metadata or {}).get("content") or {}
    emails = [str(value) for value in captured.get("emails") or []]
    phones = [str(value) for value in captured.get("phones") or []]
    if not emails and not phones:
        return 0

    page_domain = domain_of(source.source_url)
    vendor_domain = domain_of(vendor.website) or page_domain
    if not page_domain or page_domain != vendor_domain:
        return 0

    existing = contact_rows(db, vendor.id)
    known_emails = {(c["email"] or "").lower() for c in existing if c["email"]}
    known_phones = {phone_key(c["phone"]) for c in existing if c["phone"]}

    added = 0
    for address in emails:
        if address.lower() in known_emails:
            continue
        known_emails.add(address.lower())
        insert_contact(
            db,
            vendor_id=vendor.id,
            tenant_id=vendor.tenant_id,
            contact_role="commercial",
            full_name="General enquiries",
            email=address,
            source_id=source.id,
            captured_at=source.captured_at,
            origin=ValueOrigin.AI_EXTRACTION.value,
        )
        added += 1
    for number in phones:
        if phone_key(number) in known_phones:
            continue
        known_phones.add(phone_key(number))
        insert_contact(
            db,
            vendor_id=vendor.id,
            tenant_id=vendor.tenant_id,
            contact_role="commercial",
            full_name="General enquiries",
            phone=number.strip(),
            source_id=source.id,
            captured_at=source.captured_at,
            origin=ValueOrigin.AI_EXTRACTION.value,
        )
        added += 1

    if added:
        log.info(
            "vendor_discovery.contacts_recorded",
            vendor_id=str(vendor.id),
            added=added,
            domain=page_domain,
        )
    return added


def domain_of(url: str | None) -> str | None:
    """The registrable host of a URL, without `www.`, for comparing two pages' owners."""
    if not url:
        return None
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    return host or None


def _target_vendor(db: Session, entity: ExtractedEntity) -> Vendor | None:
    """The vendor this candidate's run was started to enrich, if it named one.

    The link runs through the run config rather than the candidate, because the candidate
    is produced by reading a page and knows nothing about why the run exists.
    """
    batch_id = (entity.payload or {}).get("discovery_batch_id")
    if not batch_id:
        return None
    batch = db.get(ImportBatch, uuid.UUID(str(batch_id)))
    target = (batch.config or {}).get("target_vendor_id") if batch else None
    if not target:
        return None
    vendor = db.get(Vendor, uuid.UUID(str(target)))
    if vendor is None or vendor.deleted_at is not None:
        return None
    # A run must not write across a tenancy, whatever its config says.
    if vendor.tenant_id != entity.tenant_id:
        log.warning(
            "vendor_discovery.target_tenant_mismatch",
            vendor_id=str(vendor.id),
            entity_tenant=str(entity.tenant_id),
        )
        return None
    return vendor


def store_candidate(
    db: Session,
    entity: ExtractedEntity,
    *,
    principal=None,
    edits: dict[str, Any] | None = None,
    unattended: bool = False,
) -> dict[str, Any]:
    """Write one selected candidate into ``vendors``, with provenance for every field.

    Unlike the pump promotion path this creates no pump or pump model: a discovered
    supplier is a vendor record and nothing more until a datasheet arrives for it.

    ``unattended`` is accepted so the runner can store without knowing which kind it
    holds, but it changes nothing here: the usable-name check below is unconditional,
    because a vendor record named "Pumps" is useless whether a person picked it or a
    sweep did.
    """
    del unattended
    if entity.entity_type != ENTITY_TYPE:
        raise PromotionError(f"Candidate {entity.id} is not a vendor candidate")
    if entity.promoted_at is not None:
        raise PromotionError(f"Candidate {entity.id} was already stored")

    payload = entity.payload or {}
    fields: dict[str, Any] = dict(payload.get("fields") or {})
    fields.update(edits or {})
    vendor_name = (edits or {}).get("vendor_name") or (payload.get("subject") or {}).get(
        "vendor_name"
    )

    if not is_usable_subject_name(vendor_name):
        raise PromotionError(
            f"Cannot store a vendor without a usable name (got {vendor_name!r}). "
            "Correct the name before selecting this candidate."
        )

    evidence = {
        name: (span or {}).get("quote", "") for name, span in (entity.evidence_spans or {}).items()
    }

    # A company's own site is the strongest possible statement of its website, and it is
    # almost never written out as text on the page - so the model, told to quote or omit,
    # correctly omits it and the field stays empty forever. Derived from the source URL
    # instead, with the URL as its own evidence and `CALCULATED` as its origin, so the
    # record shows how it was arrived at rather than implying someone read it.
    derived_website = _website_from_source(db, entity, vendor_name)
    derived_fields: set[str] = set()
    if derived_website and not fields.get("website"):
        fields["website"] = derived_website
        evidence["website"] = f"Derived from the captured page URL: {derived_website}"
        derived_fields.add("website")
    for name in edits or {}:
        evidence.setdefault(name, "Value entered by the reviewer during vendor discovery")

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL if edits else ValueOrigin.AI_EXTRACTION,
        confidence_level=entity.confidence_level,
        confidence_score=entity.overall_confidence,
        source_id=entity.source_id,
        ai_job_id=entity.ai_job_id,
        extracted_entity_id=entity.id,
        model_used=entity.ai_job.model if entity.ai_job else None,
        changed_by_user_id=principal.user_id if principal else None,
        tenant_id=entity.tenant_id,
    )

    # A run started to enrich one record fills that record. Resolving by name instead
    # sent an update for "Seal Care" into a new "Seal Care (S) Pte Ltd.", because the
    # company's own site uses its legal name and the trading name is what somebody had
    # typed - so the page that asked for the update stayed empty and a duplicate appeared
    # beside it.
    targeted = _target_vendor(db, entity)
    existing = targeted or existing_vendor_for(db, entity.tenant_id, vendor_name)
    was_new = existing is None
    # Snapshot before anything is applied, so the version carries a real diff. Taken here
    # rather than after `resolve_vendor`, which may itself create the row.
    before = audit.snapshot(existing) if existing is not None else {}
    # `country` and `website` are passed as None on purpose. `resolve_vendor` would set
    # them directly at insert, and the write gate then sees the column already holding
    # the value and records no provenance - leaving two AI-derived fields on the record
    # with no traceable source. Routed through `apply_fields` below instead.
    if targeted is not None:
        vendor = targeted
        # The name the page used is worth keeping, and is how somebody searching for the
        # legal name will find this record. The record's own name is left alone: the
        # person enriching it chose it.
        if vendor_name and vendor_name != vendor.name:
            aliases = list(vendor.aliases or [])
            if vendor_name not in aliases:
                vendor.aliases = [*aliases, vendor_name]
    else:
        vendor = resolve_vendor(
            db,
            tenant_id=entity.tenant_id,
            name=vendor_name,
            country=None,
            website=None,
            context=context,
        )

    # A vendor cannot be inserted without a name, so `resolve_vendor` sets it directly.
    # Record its provenance explicitly, or the record's own identity ends up as the one
    # AI-derived value on it with no traceable source.
    if was_new:
        provenance.apply_field(
            db,
            vendor,
            "name",
            vendor.name,
            context,
            evidence_quote=(
                evidence.get("vendor_name")
                or payload.get("oil_gas_evidence")
                or "Supplier name identified by AI vendor discovery"
            ),
            record_unchanged=True,
        )

    writable = {
        column: fields[key] for key, column in VENDOR_PROFILE_FIELDS.items() if key in fields
    }
    # `country` mirrors `hq_country` on this table. The evidence has to be mirrored with
    # it, or the write gate refuses the copy for having no quote.
    if "hq_country" in writable:
        writable.setdefault("country", writable["hq_country"])
        if "hq_country" in evidence:
            evidence.setdefault("country", evidence["hq_country"])

    # Derived values are applied under their own origin. Writing them as AI_EXTRACTION
    # would claim the model read something it never saw, which is the one thing the
    # provenance trail exists to prevent.
    derived = {name: writable.pop(name) for name in list(derived_fields) if name in writable}

    report = provenance.apply_fields(
        db,
        vendor,
        writable,
        context,
        evidence=evidence,
        confidences=entity.field_confidences or {},
        source_units=payload.get("source_units") or {},
    )
    if derived:
        derived_report = provenance.apply_fields(
            db,
            vendor,
            derived,
            replace(context, origin=ValueOrigin.CALCULATED),
            evidence={name: evidence[name] for name in derived if name in evidence},
        )
        # `apply_fields` returns applied/unchanged/refused. Merging under the caller's
        # names - fields_applied, fields_refused - wrote three keys nothing reads and
        # dropped the derived field from the report entirely.
        for key in ("applied", "unchanged"):
            report[key] = [*report.get(key, []), *derived_report.get(key, [])]
        report["refused"] = {
            **report.get("refused", {}),
            **derived_report.get("refused", {}),
        }

    # Facts with no column of their own are kept rather than discarded, so nothing the
    # model found is lost between the candidate and the record.
    leftovers = {k: fields[k] for k in VENDOR_EXTRA_FIELDS if fields.get(k)}

    # What the supplier says about its own qualification. Kept as a claim with its quote,
    # never written to the governance columns - see `VENDOR_CLAIM_FIELDS`. A claim with
    # nothing quoted behind it is the model's default rather than anything the page said,
    # so it is dropped.
    claims = {
        name: {"value": fields[name], "quote": evidence.get(name)}
        for name in VENDOR_CLAIM_FIELDS
        if fields.get(name) and evidence.get(name)
    }

    # Values the page stated and the write gate refused - almost always for want of a
    # verbatim quote. Kept, because the alternative is a profile full of dashes that
    # reads as "the web had nothing about this supplier" when the truth is "the web said
    # it and we would not write it down untraceably". One vendor had ten fields
    # extracted, two quoted, and eight silently dropped: country, website, category and
    # product families among them.
    refused = {
        name: {"value": fields.get(name), "reason": reason}
        for name, reason in (report.get("refused") or {}).items()
        if name in fields
    }

    if leftovers or refused or claims:
        extra = dict(vendor.extra or {})
        discovery = dict(extra.get("discovery") or {})
        discovery.update(leftovers)
        if claims:
            discovery["supplier_claims"] = claims
        if refused:
            discovery["refused"] = refused
            discovery["refused_at"] = datetime.now(UTC).isoformat()
            discovery["refused_source_id"] = str(entity.source_id) if entity.source_id else None
        extra["discovery"] = discovery
        vendor.extra = extra

    if vendor.verification_status == VerificationStatus.UNVERIFIED and entity.source_id:
        vendor.primary_source_id = vendor.primary_source_id or entity.source_id

    # How much of the profile this record now holds. Recomputed on the way out, so the
    # number never describes an older version of the record than the one on screen.
    completeness.refresh_vendor(db, vendor)

    # A version per run that changed something.
    #
    # `record_versions` claims to hold a snapshot of "every mutation of a vendor", and
    # for the discovery path it held none: the only vendor versions in the database came
    # from manual creates. So a supplier enriched from the web three times had three sets
    # of provenance rows and no way to see what the record looked like before each one.
    #
    # Written only when a field actually changed, because a run that re-reads the same
    # pages and confirms what is already there is not a new version of anything.
    db.flush()
    after = audit.snapshot(vendor)
    changed = audit.diff(before, after)
    if changed:
        audit.record_version(
            db,
            obj=vendor,
            operation="insert" if was_new else "update",
            before=before,
            principal=principal,
            change_reason=(
                "Created by AI vendor discovery"
                if was_new
                else f"Enriched from the web: {', '.join(sorted(changed))}"[:500]
            ),
            ai_job_id=entity.ai_job_id,
        )

    # Record the contact details the page states for this company.
    record_page_contacts(db, vendor, db.get(Source, entity.source_id) if entity.source_id else None)

    # Scan for duplicates, as the manual create path does.
    #
    # It did not, and that is why 75 discovered vendors produced zero duplicate
    # candidates: `dedupe.scan_vendor` was wired into `POST /vendors` and the
    # `/duplicates` endpoint only, so a supplier that arrived through AI discovery was
    # never compared with anything. Two rows for one company could sit in the list
    # indefinitely with nothing flagging them.
    dedupe.scan_vendor(db, vendor)

    entity.review_decision = (
        ReviewDecision.ACCEPTED_WITH_EDITS if edits else ReviewDecision.ACCEPTED
    )
    entity.reviewed_by_user_id = principal.user_id if principal else None
    entity.reviewed_at = datetime.now(UTC)
    entity.promoted_at = datetime.now(UTC)
    entity.target_type = "vendors"
    entity.target_id = vendor.id
    db.flush()

    log.info(
        "vendor_discovery.stored",
        vendor_id=str(vendor.id),
        candidate_id=str(entity.id),
        applied=len(report.get("applied") or []),
    )
    return {
        "vendor_id": str(vendor.id),
        "vendor_name": vendor.name,
        "candidate_id": str(entity.id),
        "fields_applied": report.get("applied") or [],
        "fields_refused": report.get("refused") or {},
    }
