"""Promotion: turn reviewed AI candidates into system-of-record rows.

This is the only path from ``extracted_entities`` into ``vendors`` / ``pumps`` /
``pump_models`` / the six spec tables. It:

* resolves or creates the subject (vendor -> pump -> pump model),
* opens a **new spec version** rather than mutating the current one,
* writes every field through ``provenance.apply_field`` so each value keeps its source,
  evidence quote, model and confidence,
* records an audit entry and a row snapshot.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ai import ExtractedEntity, FieldProvenance
from app.models.enums import (
    AuditAction,
    ConfidenceLevel,
    ReviewDecision,
    ValueOrigin,
    VerificationStatus,
)
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
from app.services import audit, designations, provenance

log = get_logger(__name__)

SPEC_MODEL_BY_ENTITY = {
    "technical_spec": TechnicalSpec,
    "commercial_spec": CommercialSpec,
    "dimensional_spec": DimensionalSpec,
    "delivery_spec": DeliverySpec,
    "operational_spec": OperationalSpec,
    "administrative_spec": AdministrativeSpec,
}

VENDOR_FIELDS = {"vendor_name", "vendor_country", "vendor_website"}
PUMP_FIELDS = {
    "pump_name",
    "product_family",
    "pump_type",
    "pump_type_raw",
    "applicable_standard",
    "standard_edition",
    "service_application",
    "handled_fluids",
    "is_discontinued",
    "description",
}
PUMP_MODEL_FIELDS = {
    "model_code",
    "size_designation",
    "frame_size",
    "stages",
    "orientation",
    "generation",
    "tag_number",
    "project_reference",
}

#: Legal-form suffixes stripped before two company names are compared.
#:
#: Must stay the same set as the alternation in `pumpatlas_normalize_company_name`
#: (db/functions.sql). The database normalises on insert and this normalises on the write
#: path, so a suffix in one list and not the other gives the same company two different
#: keys - which is a duplicate nothing will ever match up. `test_normalisation.py` reads
#: the SQL and compares the two.
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(gmbh|ag|s\.?p\.?a|s\.?a\.?s|s\.?a|srl|s\.?r\.?l|bv|b\.v|nv|n\.v|ltd|limited|"
    r"llc|inc|incorporated|corp|corporation|co|company|plc|pte|pty|kk|oy|ab|as|a/s|jsc|"
    r"ooo|pjsc|holdings?|group|international|industries|manufacturing)\b",
    re.IGNORECASE,
)


class PromotionError(RuntimeError):
    pass


class WeakSubjectError(PromotionError):
    """The extraction did not identify its subject well enough to store unattended.

    Raised only when ``require_usable_subject`` is set, which auto-promotion does and
    human-reviewed promotion does not - a reviewer who has looked at the page and chosen
    to accept it may legitimately want a placeholder record.
    """


MIN_SUBJECT_ALNUM = 3

#: What a record is called when the page named a manufacturer and no product.
#:
#: `resolve_pump` and `resolve_pump_model` invent these so a vendor has somewhere to hang
#: - the row exists to carry a relationship, not to describe a pump. Both templates live
#: here so anything asking "is this a real designation?" reads the same answer, rather
#: than matching on a string that has drifted.
UNSPECIFIED_LINE = "{vendor} unspecified line"
UNSPECIFIED_VARIANT = "{pump} (unspecified variant)"

_PLACEHOLDER_MARKERS = ("unspecified line", "unspecified variant")


def is_placeholder_designation(value: str | None) -> bool:
    """Whether this name was invented by the resolver rather than read off a page.

    It matters wherever something is about to act on the name. Searching the web for the
    "Bornerman unspecified line (unspecified variant)" datasheet reads two pages, finds
    nothing, and reports that the record could not be filled - when the truth is that
    there was never a product to look for.
    """
    text = (value or "").lower()
    return any(marker in text for marker in _PLACEHOLDER_MARKERS)


def is_usable_subject_name(raw: str | None) -> bool:
    """Reject names that carry no identifying information.

    Extracting a marketing page unattended produces subjects like ``"610"`` (the
    standard number mistaken for a product name) and ``"1"``. Promoting those creates
    records nobody can act on and which then have to be found and merged away, so an
    unattended run is better off leaving the candidate in the review queue.
    """
    if not raw:
        return False
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw)
    if len(cleaned) < MIN_SUBJECT_ALNUM:
        return False
    # A purely numeric name is a standard, a size or a page fragment - never a product.
    return not cleaned.isdigit()


#: Letters `unaccent` transliterates but Unicode decomposition does not.
#:
#: NFKD splits an accented letter into a base plus a combining mark, which covers é, ü,
#: ç and most of the Latin range. It does nothing for letters that are not composed:
#: ß, ø, æ, ł and friends are single code points with no decomposition, and dropping
#: them is how "Gößnitz" became "g nitz".
_TRANSLITERATE = {
    "ß": "ss",
    "ø": "o",
    "Ø": "O",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ð": "d",
    "Ð": "D",
    "þ": "th",
    "Þ": "TH",
    "ı": "i",
    "İ": "I",
    "ĸ": "k",
    "ŋ": "n",
}


def fold_accents(value: str) -> str:
    """Transliterate accented *letters* to ASCII, the way ``unaccent`` does.

    Letters only, deliberately. NFKD is a compatibility decomposition, so it also expands
    symbols - it turns "™" into "TM", which would have made
    "Trillium Flow Technologies™" normalise to `...technologiestm` here and
    `...technologies` in the database. Symbols are left alone and the caller's
    `[^a-z0-9]` pass drops them, which is what the SQL function effectively does.

    One known difference remains, and it predates this: `unaccent` maps "®" to "R", so
    "Pumps ® Ltd" is `pumps r` in the database and `pumps` here. It is recorded in
    `test_normalisation.py` rather than guessed at, because matching `unaccent`'s whole
    rule table for symbols nobody puts in a company name is not worth the risk of getting
    a letter wrong.
    """
    folded: list[str] = []
    for char in value:
        if char in _TRANSLITERATE:
            folded.append(_TRANSLITERATE[char])
            continue
        # Letters and number-like forms: "u" with an umlaut, and "1/2" written as a
        # single character. Not symbols - NFKD turns "(TM)" into "TM" while `unaccent`
        # drops it.
        is_number_form = unicodedata.category(char).startswith("N")
        if char.isascii() or not (char.isalpha() or is_number_form):
            folded.append(char)
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        folded.append(stripped)
    return "".join(folded)


def normalize_company_name(raw: str) -> str:
    """Mirror of ``pumpatlas_normalize_company_name`` in db/functions.sql.

    It was not a mirror. The SQL function calls ``unaccent``, which transliterates, while
    this stripped every character outside ``[a-z0-9]`` - so "Apollo Gößnitz GmbH"
    normalised to "apollo g nitz" here and "apollo gossnitz" in the database. The write
    path uses this one, so any supplier with an accent in its name got a normalised key
    that matched nothing: two records for one company, and a duplicate scanner that could
    not see they were the same.

    German, Nordic, Turkish and Spanish names are ordinary in Oil & Gas pump supply, so
    this was not an edge case.
    """
    folded = fold_accents(raw or "").lower()
    lowered = _LEGAL_SUFFIX_RE.sub(" ", folded)
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def normalize_model_code(raw: str) -> str:
    """The key two spellings of one model have to share.

    The type code is dropped first, so "OH1 B Series" and "B Series" resolve to the same
    model instead of becoming two records of the same pump - which is how one Amarinth
    product could be captured twice from two pages of the same site.
    """
    return re.sub(r"[^a-z0-9]+", "", designations.product_name(raw).lower())


def resolve_vendor(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    name: str,
    country: str | None = None,
    website: str | None = None,
    context: provenance.ProvenanceContext | None = None,
    allow_shared_master: bool = True,
) -> Vendor:
    """Find an existing vendor by normalised name, else create one."""
    if not name or not name.strip():
        raise PromotionError("Cannot resolve a vendor without a name")

    normalized = normalize_company_name(name)
    tenant_scopes = [tenant_id, None] if allow_shared_master else [tenant_id]
    for scope in tenant_scopes:
        existing = db.scalar(
            select(Vendor).where(
                Vendor.tenant_id == scope,
                Vendor.normalized_name == normalized,
                Vendor.deleted_at.is_(None),
                Vendor.merged_into_vendor_id.is_(None),
            )
        )
        if existing is not None:
            return existing

    vendor = Vendor(
        tenant_id=tenant_id,
        name=name.strip()[:255],
        normalized_name=normalized[:255],
        country=(country or "").upper()[:2] or None,
        hq_country=(country or "").upper()[:2] or None,
        website=website,
        confidence_level=context.confidence_level if context else ConfidenceLevel.UNKNOWN,
        verification_status=VerificationStatus.UNVERIFIED,
        primary_source_id=context.source_id if context else None,
        created_by_user_id=context.changed_by_user_id if context else None,
    )
    db.add(vendor)
    db.flush()
    log.info("promotion.vendor_created", vendor_id=str(vendor.id), name=vendor.name)
    return vendor


def resolve_pump(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    vendor: Vendor,
    name: str | None,
    fields: dict[str, Any],
    context: provenance.ProvenanceContext | None = None,
    require_usable_subject: bool = False,
) -> Pump:
    """Find or create the product line this record belongs to."""
    pump_name = (name or fields.get("product_family") or fields.get("model_code") or "").strip()
    if not is_usable_subject_name(pump_name):
        if require_usable_subject:
            raise WeakSubjectError(
                f"extraction gave no usable product name (got {pump_name!r}); leaving it "
                "for review rather than creating a record nobody can act on"
            )
        pump_name = UNSPECIFIED_LINE.format(vendor=vendor.name)
    normalized = normalize_company_name(pump_name) or normalize_model_code(pump_name)

    existing = db.scalar(
        select(Pump).where(
            Pump.tenant_id == tenant_id,
            Pump.vendor_id == vendor.id,
            Pump.normalized_name == normalized,
            Pump.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing

    pump = Pump(
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        name=pump_name[:255],
        normalized_name=normalized[:255],
        confidence_level=context.confidence_level if context else ConfidenceLevel.UNKNOWN,
        primary_source_id=context.source_id if context else None,
        created_by_user_id=context.changed_by_user_id if context else None,
    )
    db.add(pump)
    db.flush()
    log.info("promotion.pump_created", pump_id=str(pump.id), name=pump.name)
    return pump


def resolve_pump_model(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    pump: Pump,
    model_code: str | None,
    context: provenance.ProvenanceContext | None = None,
) -> PumpModel:
    code = (model_code or "").strip() or UNSPECIFIED_VARIANT.format(pump=pump.name)
    existing_models = db.scalars(
        select(PumpModel).where(
            PumpModel.tenant_id == tenant_id,
            PumpModel.pump_id == pump.id,
            PumpModel.deleted_at.is_(None),
        )
    ).all()
    target = normalize_model_code(code)
    for candidate in existing_models:
        if normalize_model_code(candidate.model_code) == target:
            return candidate

    model = PumpModel(
        tenant_id=tenant_id,
        pump_id=pump.id,
        model_code=code[:160],
        confidence_level=context.confidence_level if context else ConfidenceLevel.UNKNOWN,
        primary_source_id=context.source_id if context else None,
        created_by_user_id=context.changed_by_user_id if context else None,
    )
    db.add(model)
    db.flush()
    log.info("promotion.pump_model_created", pump_model_id=str(model.id), code=model.model_code)
    return model


# Columns that describe the version row itself, never the pump. Never carried forward.
VERSION_METADATA_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "pump_model_id",
        "created_at",
        "updated_at",
        "version",
        "is_current",
        "superseded_at",
        "source_id",
        "ai_job_id",
        "created_by_user_id",
        "data_submission_date",
    }
)


def open_spec_version(
    db: Session,
    spec_cls: type,
    *,
    tenant_id: uuid.UUID | None,
    pump_model: PumpModel,
    context: provenance.ProvenanceContext,
    carry_forward: bool = True,
) -> Any:
    """Create the next version row for a spec table.

    ``carry_forward`` copies the previous current version's values, and their
    ``field_provenance`` rows, onto the new version. Both halves matter:

    * Without the values, promoting an extraction of three fields would open a version
      containing only those three and retire one holding twenty - silent data loss on
      the current view of the record.
    * Without the provenance, a carried-forward value would arrive with no lineage, and
      "where did this number come from?" would stop working the moment anything else on
      the record was edited.

    The DB trigger ``trg_<table>_supersede`` retires the previous row, so history is
    preserved without the application having to remember to do it.
    """
    previous = db.scalar(
        select(spec_cls)
        .where(spec_cls.pump_model_id == pump_model.id, spec_cls.is_current.is_(True))
        .order_by(spec_cls.version.desc())
        .limit(1)
    )
    current_version = (
        db.scalar(
            select(func.coalesce(func.max(spec_cls.version), 0)).where(
                spec_cls.pump_model_id == pump_model.id
            )
        )
        or 0
    )
    spec = spec_cls(
        tenant_id=tenant_id,
        pump_model_id=pump_model.id,
        version=current_version + 1,
        is_current=True,
        source_id=context.source_id,
        ai_job_id=context.ai_job_id,
        created_by_user_id=context.changed_by_user_id,
        confidence_level=context.confidence_level,
        verification_status=VerificationStatus.UNVERIFIED,
        data_submission_date=datetime.now(UTC).date(),
    )
    if spec_cls is AdministrativeSpec:
        spec.vendor_id = pump_model.pump.vendor_id

    if carry_forward and previous is not None:
        for column in spec_cls.__table__.columns:
            if column.name in VERSION_METADATA_COLUMNS:
                continue
            setattr(spec, column.name, getattr(previous, column.name))
        # The new row is a different entity_id, so keep the version metadata this
        # constructor set rather than the copied values.
        spec.verification_status = previous.verification_status

    db.add(spec)
    db.flush()

    if carry_forward and previous is not None:
        _carry_forward_provenance(db, spec_cls.__tablename__, previous.id, spec.id)
        db.flush()
    return spec


def _carry_forward_provenance(
    db: Session, entity_type: str, from_entity_id: uuid.UUID, to_entity_id: uuid.UUID
) -> int:
    """Copy the current provenance rows from one spec version to the next.

    The value has not changed, so its lineage - source, evidence quote, model,
    confidence - is still the true answer and is preserved verbatim.
    """
    rows = db.scalars(
        select(FieldProvenance).where(
            FieldProvenance.entity_type == entity_type,
            FieldProvenance.entity_id == from_entity_id,
            FieldProvenance.is_current.is_(True),
        )
    ).all()
    for row in rows:
        db.add(
            FieldProvenance(
                tenant_id=row.tenant_id,
                entity_type=entity_type,
                entity_id=to_entity_id,
                field_name=row.field_name,
                value_text=row.value_text,
                previous_value_text=row.previous_value_text,
                value_origin=row.value_origin,
                confidence_level=row.confidence_level,
                confidence_score=row.confidence_score,
                source_id=row.source_id,
                document_id=row.document_id,
                ai_job_id=row.ai_job_id,
                extracted_entity_id=row.extracted_entity_id,
                model_used=row.model_used,
                evidence_quote=row.evidence_quote,
                evidence_locator=row.evidence_locator,
                original_value=row.original_value,
                original_unit=row.original_unit,
                normalization_note=row.normalization_note,
                changed_by_user_id=row.changed_by_user_id,
                is_current=True,
            )
        )
    return len(rows)


def write_spec_groups(
    db: Session,
    *,
    entity: ExtractedEntity,
    pump_model: PumpModel,
    context: provenance.ProvenanceContext,
    fields: dict[str, Any],
    evidence: dict[str, str],
    spec_groups: Sequence[str] | None = None,
    source_units: dict[str, Any] | None = None,
    principal=None,
    change_reason: str = "AI extraction promoted",
    skip_fields_with_a_value: bool = False,
    fields_with_a_value: dict[str, set[str]] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Write each specification field into the spec table that owns it.

    Shared by promotion and by the backfill that recovers values an earlier defect
    dropped, so the two cannot disagree about how a specification value is written -
    which version row it lands in, what provenance it carries, or what the audit trail
    says. A backfill that wrote values differently from the live path would be worse than
    the gap it repairs.

    ``spec_groups`` restricts which tables may be written; None offers all of them.
    Inferring the group from ``entity.entity_type`` instead was silent data loss: the
    entity type both real flows produce is "pump_model", which is not a key in
    SPEC_MODEL_BY_ENTITY, so nothing was requested, no version row was opened and every
    extracted specification value was discarded on accept. The record still looked
    plausible afterwards - it kept its vendor and pump-level fields - and only the six
    empty spec panels gave it away.

    Offering every group is safe because no column name is shared by two spec models, so
    each field lands in exactly one table, and a group with nothing writable in it is
    skipped rather than opening an empty version row - "nothing writable" including a
    group whose every field is refused for want of an evidence quote, which is otherwise
    only discovered once the row has been opened.

    ``skip_fields_with_a_value`` leaves alone any field the current version already has,
    so a repair cannot overwrite something recorded since. Answering that question costs
    one query per spec table per model, which a bulk repair cannot afford against a
    remote database; ``fields_with_a_value`` lets such a caller resolve the answer for
    every model in one query per table up front and pass it in, as
    ``{spec_table_name: {field, ...}}``. Omitting it falls back to querying per model.

    Returns the last spec row written (or None) and the per-table outcome report.
    """
    requested = (
        [SPEC_MODEL_BY_ENTITY[name] for name in spec_groups if name in SPEC_MODEL_BY_ENTITY]
        if spec_groups is not None
        else list(SPEC_MODEL_BY_ENTITY.values())
    )

    spec = None
    outcomes: dict[str, Any] = {}
    identity_fields = VENDOR_FIELDS | PUMP_FIELDS | PUMP_MODEL_FIELDS
    for spec_cls in requested:
        candidate_fields = {
            name: value
            for name, value in fields.items()
            if name not in identity_fields and hasattr(spec_cls, name)
        }
        if skip_fields_with_a_value and candidate_fields:
            if fields_with_a_value is not None:
                taken = fields_with_a_value.get(spec_cls.__tablename__) or frozenset()
                candidate_fields = {
                    name: value for name, value in candidate_fields.items() if name not in taken
                }
            else:
                current = db.scalar(
                    select(spec_cls).where(
                        spec_cls.pump_model_id == pump_model.id,
                        spec_cls.is_current.is_(True),
                    )
                )
                if current is not None:
                    candidate_fields = {
                        name: value
                        for name, value in candidate_fields.items()
                        if getattr(current, name, None) is None
                    }
        # A value with nothing to back it is refused wherever it is aimed, so find those
        # here rather than after a row has been opened for them. Opening one anyway
        # retires the current version and replaces it with an identical copy - a version
        # in the history and an entry in the audit trail that record no change at all.
        # A None carries nothing to write either, and apply_fields skips it.
        withheld = {}
        for name, value in list(candidate_fields.items()):
            if value is None:
                del candidate_fields[name]
            elif context.requires_evidence and not (evidence or {}).get(name):
                withheld[name] = provenance.missing_evidence_reason(name)
                del candidate_fields[name]

        # An empty group would open a new version row carrying nothing, which pollutes
        # the version history and the completeness score.
        if not candidate_fields:
            if withheld:
                outcomes[spec_cls.__tablename__] = {
                    "applied": [],
                    "unchanged": [],
                    "refused": withheld,
                }
            continue

        spec = open_spec_version(
            db, spec_cls, tenant_id=entity.tenant_id, pump_model=pump_model, context=context
        )
        spec.source_units = source_units
        outcome = provenance.apply_fields(
            db,
            spec,
            candidate_fields,
            context,
            evidence=evidence,
            confidences=entity.field_confidences or {},
            source_units=source_units,
        )
        outcome["refused"].update(withheld)
        outcomes[spec.__tablename__] = outcome
        audit.record_version(
            db,
            obj=spec,
            operation="insert",
            principal=principal,
            change_reason=change_reason,
            ai_job_id=entity.ai_job_id,
        )
    return spec, outcomes


def promote_extracted_entity(
    db: Session,
    entity: ExtractedEntity,
    *,
    principal=None,
    reviewer_edits: dict[str, Any] | None = None,
    overwrite_verified: bool = False,
    decision: ReviewDecision = ReviewDecision.ACCEPTED,
    unattended: bool = False,
    spec_groups: Sequence[str] | None = None,
    target_pump_model: PumpModel | None = None,
) -> dict[str, Any]:
    """Write one reviewed candidate into the system of record.

    ``target_pump_model`` is the record an enrichment run was started from. Given one,
    the vendor, product line and model are that record's rather than whatever the page
    happened to call them - a datasheet writing "HZC-200" for the model recorded as
    "HZC" fills the record the user asked about instead of creating a second one beside
    it.

    ``unattended`` tightens the bar for auto-promotion: a candidate whose subject the
    model failed to identify is left in the review queue instead of becoming a record
    named "610" that somebody has to find and merge away later.

    ``spec_groups`` names which spec tables may be written. Leaving it None - as the AI
    review queue does - offers every group and lets each field land in the table that
    owns it, which is the only way not to drop values: one captured datasheet yields
    technical, commercial, dimensional and delivery figures at once. Pass a subset only
    to deliberately restrict what a caller is allowed to write.
    """
    if entity.promoted_at is not None:
        raise PromotionError(f"Extracted entity {entity.id} was already promoted")

    payload = entity.payload or {}
    fields: dict[str, Any] = dict(payload.get("fields") or {})
    fields.update(reviewer_edits or {})
    subject = payload.get("subject") or {}
    evidence = {
        name: (span or {}).get("quote", "") for name, span in (entity.evidence_spans or {}).items()
    }
    # A reviewer's own correction is human-origin evidence.
    for name in reviewer_edits or {}:
        evidence.setdefault(name, "Value entered by reviewer during AI review")

    origin = (
        ValueOrigin.MANUAL
        if decision == ReviewDecision.ACCEPTED_WITH_EDITS and reviewer_edits
        else ValueOrigin.AI_EXTRACTION
    )
    context = provenance.ProvenanceContext(
        origin=origin,
        confidence_level=entity.confidence_level,
        confidence_score=entity.overall_confidence,
        source_id=entity.source_id,
        ai_job_id=entity.ai_job_id,
        extracted_entity_id=entity.id,
        model_used=entity.ai_job.model if entity.ai_job else None,
        changed_by_user_id=principal.user_id if principal else None,
        tenant_id=entity.tenant_id,
    )

    # A reviewer's correction outranks the extraction. It did not: the subject was read
    # first and only fell back to `fields`, where the edits land - so correcting a
    # manufacturer or a model code in the review screen changed nothing, and the record
    # was written with the value the reviewer had just rejected. `pump_name` was read
    # from `fields` and did work, which is why it went unnoticed.
    edits = reviewer_edits or {}
    vendor_name = (
        edits.get("vendor_name") or subject.get("vendor_name") or fields.get("vendor_name")
    )
    if unattended and not is_usable_subject_name(vendor_name):
        raise WeakSubjectError(
            f"extraction gave no usable vendor name (got {vendor_name!r}); leaving it " "for review"
        )
    # What the page called the product, and what of that is its category. A page titled
    # "OH1 B Series" is about the B Series; OH1 is the API 610 configuration it is built
    # in, which is a fact about the pump and not part of its name.
    stated_code = edits.get("model_code") or subject.get("model_code") or fields.get("model_code")
    designation = designations.classify(stated_code)
    if designation.is_category_only:
        # Refused on the way in, not only warned about in the queue. `blocked_reason`
        # tells a reviewer before the click; this is what stops the click, and what stops
        # a sweep storing it with nobody watching. A reviewer who knows the real
        # designation types it in, and that edit now wins.
        raise WeakSubjectError(
            f"{stated_code!r} is a pump type, not a model designation. This page names a "
            "category rather than a product - correct the model code to store it."
        )

    if not vendor_name:
        raise PromotionError(
            "Cannot promote without a vendor: the extraction did not identify a supplier. "
            "Assign one in the AI review screen first."
        )

    if target_pump_model is not None:
        # An enrichment run knows which record it exists to fill. Resolving by name
        # instead would let a datasheet writing "HZC-200" create a second model beside
        # the "HZC" the user was looking at, which would stay as empty as before.
        pump_model = target_pump_model
        pump = db.get(Pump, pump_model.pump_id)
        vendor = db.get(Vendor, pump.vendor_id) if pump else None
        if pump is None or vendor is None:
            raise PromotionError(
                f"Pump model {pump_model.id} has no product line or vendor to write to"
            )
    else:
        vendor = resolve_vendor(
            db,
            tenant_id=entity.tenant_id,
            name=vendor_name,
            country=fields.get("vendor_country"),
            website=fields.get("vendor_website"),
            context=context,
        )
        pump = resolve_pump(
            db,
            tenant_id=entity.tenant_id,
            vendor=vendor,
            name=edits.get("pump_name") or fields.get("pump_name"),
            fields=fields,
            context=context,
            require_usable_subject=unattended,
        )
        pump_model = resolve_pump_model(
            db,
            tenant_id=entity.tenant_id,
            pump=pump,
            model_code=designation.product_name or stated_code,
            context=context,
        )

    report: dict[str, Any] = {
        "vendor_id": str(vendor.id),
        "pump_id": str(pump.id),
        "pump_model_id": str(pump_model.id),
        "targets": {},
    }
    source_units = payload.get("source_units") or {}

    def _write(target: Any, values: dict[str, Any]) -> None:
        outcome = provenance.apply_fields(
            db,
            target,
            values,
            context,
            evidence=evidence,
            confidences=entity.field_confidences or {},
            source_units=source_units,
        )
        report["targets"][target.__tablename__] = outcome

    # Vendor-level identity fields arrive under vendor_* names in the extraction.
    _write(
        vendor,
        {"country": fields.get("vendor_country"), "website": fields.get("vendor_website")},
    )
    # A classification that contradicts the designation on the page. One LUBOR candidate
    # was titled "API 610 VS6 Vertical Suspended Pump" and came back classified OH6 -
    # overhung, which is the opposite arrangement to vertically suspended. Both cannot be
    # true, and the designation is the manufacturer's own word for the product while the
    # classification is the reading model's opinion of it, so the opinion is refused.
    # `pump_type` is then derived from the designation below, with the designation as its
    # evidence, which is the traceable version of the same answer.
    contradiction: dict[str, str] = {}
    stated_type = designation.pump_type
    if stated_type and fields.get("pump_type") and fields["pump_type"] != stated_type:
        contradiction["pump_type"] = (
            f"{fields['pump_type']!r} contradicts the designation {stated_code!r}, which "
            f"states {designation.api_610_type_code}"
        )
        fields = {name: value for name, value in fields.items() if name != "pump_type"}

    _write(pump, {k: v for k, v in fields.items() if k in PUMP_FIELDS and k != "pump_name"})
    if contradiction:
        report["targets"]["pumps"].setdefault("refused", {}).update(contradiction)
    _write(
        pump_model,
        {k: v for k, v in fields.items() if k in PUMP_MODEL_FIELDS and k != "model_code"},
    )

    # The type and the standard the designation carried, when the extraction did not
    # state them itself. Written as CALCULATED with the designation as their evidence:
    # the page did not say "this is an OH1 pump" in those words, it named the product
    # "OH1 B Series", and the record should show that this was read off the name rather
    # than quoted from the text.
    #
    # `pump_type` and `applicable_standard` only. The type also has a home on the
    # technical spec (`api_610_type_code`), and putting it there means opening a spec
    # version for a value nobody quoted - so it stays where search and the profile
    # already read it from.
    derived_from_name = {
        name: value
        for name, value in (
            ("pump_type", designation.pump_type),
            ("applicable_standard", designation.applicable_standard),
        )
        if value and not fields.get(name) and getattr(pump, name, None) is None
    }
    if derived_from_name:
        note = f"Read from the designation stated on the page: {stated_code!r}"
        report["targets"].setdefault("pumps_derived", {})
        report["targets"]["pumps_derived"] = provenance.apply_fields(
            db,
            pump,
            derived_from_name,
            replace(context, origin=ValueOrigin.CALCULATED),
            evidence={name: note for name in derived_from_name},
        )

    spec, spec_outcomes = write_spec_groups(
        db,
        entity=entity,
        pump_model=pump_model,
        context=context,
        fields=fields,
        evidence=evidence,
        spec_groups=spec_groups,
        source_units=source_units,
        principal=principal,
    )
    report["targets"].update(spec_outcomes)

    entity.review_decision = decision
    entity.reviewed_by_user_id = principal.user_id if principal else None
    entity.reviewed_at = datetime.now(UTC)
    entity.reviewer_edits = reviewer_edits or {}
    entity.target_type = spec.__tablename__ if spec is not None else "pump_model"
    entity.target_id = spec.id if spec is not None else pump_model.id
    entity.promoted_at = datetime.now(UTC)

    audit.record_audit(
        db,
        action=AuditAction.AI_SUGGESTION_APPLIED,
        principal=principal,
        entity_type=entity.target_type,
        entity_id=entity.target_id,
        entity_label=f"{vendor.name} / {pump.name} / {pump_model.model_code}",
        summary=f"Promoted AI extraction from source {entity.source_id}",
        changes=report["targets"],
        context={"extracted_entity_id": str(entity.id), "ai_job_id": str(entity.ai_job_id)},
        tenant_id=entity.tenant_id,
    )
    db.flush()
    log.info("promotion.completed", entity_id=str(entity.id), report=report["targets"])
    return report
