"""AI pump discovery: what makes it *pump* discovery.

The engine — Parallel AI search, source capture, per-page Gemma screening, run progress —
lives in :mod:`app.services.discovery` and is shared with vendor discovery. This module
is the pump half: the search objective, the screening prompt, and the write.

Storing a pump candidate is a bigger act than storing a vendor. A model does not exist
in isolation: it needs a manufacturer and a product line above it, and its specification
belongs in the six versioned spec tables rather than on one row. That whole path already
exists as :func:`app.services.promotion.promote_extracted_entity`, which is what the AI
review queue uses, so discovery delegates to it rather than growing a second promotion
path that could drift from the first.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.parallel_search import pump_discovery_objective, pump_type_segments
from app.core.logging import get_logger
from app.models.ai import ExtractedEntity
from app.models.enums import ReviewDecision
from app.models.pump import Pump, PumpModel
from app.models.source import ImportBatch
from app.models.vendor import Vendor
from app.services import designations, promotion
from app.services.discovery import DiscoveryKind
from app.services.promotion import (
    PromotionError,
    is_usable_subject_name,
    normalize_model_code,
)

log = get_logger(__name__)

KIND = DiscoveryKind(
    slug="pump",
    # The candidate carries identity plus several spec groups, which is exactly what the
    # existing extraction contract calls a `pump_model` candidate. Reusing that name is
    # what lets `promote_extracted_entity` handle it unchanged.
    entity_type="pump_model",
    noun="pump model",
    screen_label="Screen and profile pump models",
    run_name="AI pump discovery",
    build_objective=pump_discovery_objective,
    system_prompt=prompts.SYSTEM_PUMP_PROFILE,
    build_user_prompt=prompts.build_pump_profile_prompt,
    relevance_key="is_oil_gas_pump_model",
    subject_keys=("vendor_name", "model_code", "pump_name"),
    sweep_segments=pump_type_segments,
    sweep_scopes={"pump_type": pump_type_segments},
    off_subject=lambda subject, fields: category_page_reason(
        subject.get("model_code") or fields.get("model_code")
    ),
)

ENTITY_TYPE = KIND.entity_type
IMPORT_MODE = KIND.import_mode

#: Reviewer edits are accepted only for the subject fields and the spec fields the
#: extraction contract already knows. Anything else is ignored rather than written.
EDITABLE_SUBJECT_FIELDS = ("vendor_name", "model_code", "pump_name")


#: Kept as the name other modules import. The judgement moved to `designations`, which
#: reads a code as words: an exact-match set caught "OH1" and let "API 610 OH1" through,
#: and both were in the review queue on the same screen.
TYPE_DESIGNATIONS = designations.API_TYPE_CODES | designations.STANDARD_CODES


def category_page_reason(model_code: str | None) -> str | None:
    """Why this page should not have become a candidate, or None.

    Separate from `blocked_reason`, and narrower on purpose. `blocked_reason` also
    reports a candidate with no manufacturer or no designation at all - which a reviewer
    can fix by typing one in, so those belong in the queue. This is the case a reviewer
    cannot fix: the page names a category, and there is no product on it to name.
    """
    designation = designations.classify(model_code)
    if not designation.is_category_only:
        return None
    return (
        f"{str(model_code).strip()!r} is a pump type, not a model designation - this "
        "page describes a category of pump rather than a product."
    )


def blocked_reason(subject: dict, fields: dict) -> str | None:
    """Why storing this candidate would fail, or None. Mirrors `store_candidate`.

    A pump model needs a manufacturer and its own designation. Both are things Gemma
    routinely cannot find on a category landing page, and `promote_extracted_entity`
    refuses the write - so the reviewer is told before the click rather than after.
    """
    vendor_name = subject.get("vendor_name")
    if not vendor_name:
        return "Gemma did not identify a manufacturer on this page."
    if not is_usable_subject_name(vendor_name):
        return f"{vendor_name!r} is not a usable manufacturer name."

    model_code = subject.get("model_code")
    if not model_code:
        return "Gemma did not find a model designation on this page."
    if not is_usable_subject_name(model_code):
        return f"{model_code!r} is not a usable model code."

    designation = designations.classify(model_code)
    if designation.is_category_only:
        return (
            f"{model_code!r} is a pump type, not a model designation. This page names a "
            "category rather than a product."
        )
    # "OH1 B Series" is the B Series; the type code comes off, and what is left has to
    # stand on its own the same way the raw code did.
    if designation.product_name != str(model_code).strip():
        if not is_usable_subject_name(designation.product_name):
            return (
                f"{model_code!r} is a pump type with nothing else to it - "
                f"{designation.product_name!r} does not name a product."
            )
    return None


def existing_models_for(
    db: Session,
    tenant_id: uuid.UUID | None,
    pairs: Iterable[tuple[str | None, str | None]],
) -> dict[tuple[str, str], PumpModel]:
    """The pump models these candidates would enrich, resolved in three queries.

    So the UI can say "this would enrich an existing model" before anyone clicks
    store. Asked one candidate at a time this is the most expensive question in the
    discovery poll - it resolves a vendor and then loads every model that vendor has,
    against a remote database - so thirty candidates cost a hundred round trips. Here
    the vendors resolve in two queries, their models in one, and the code comparison
    happens in Python exactly as :func:`resolve_pump_model` does it.

    Keyed by ``(normalised vendor name, normalised model code)``.
    """
    wanted: set[tuple[str, str]] = set()
    for vendor_name, model_code in pairs:
        if not vendor_name or not model_code:
            continue
        key = (promotion.normalize_company_name(vendor_name), normalize_model_code(model_code))
        if all(key):
            wanted.add(key)
    if not wanted:
        return {}

    # Global scope first so the tenant's own vendors overwrite it, matching the
    # (tenant_id, None) precedence of the single-candidate lookup.
    vendors: dict[str, uuid.UUID] = {}
    for scope in (None, tenant_id):
        rows = db.scalars(
            select(Vendor).where(
                Vendor.tenant_id == scope,
                Vendor.normalized_name.in_({vendor for vendor, _ in wanted}),
                Vendor.deleted_at.is_(None),
                Vendor.merged_into_vendor_id.is_(None),
            )
        ).all()
        for vendor in rows:
            vendors[vendor.normalized_name] = vendor.id
    if not vendors:
        return {}

    by_vendor_id = {vendor_id: name for name, vendor_id in vendors.items()}
    rows = db.execute(
        select(Pump.vendor_id, PumpModel)
        .join(Pump, Pump.id == PumpModel.pump_id)
        .where(Pump.vendor_id.in_(by_vendor_id), PumpModel.deleted_at.is_(None))
    ).all()

    found: dict[tuple[str, str], PumpModel] = {}
    for vendor_id, model in rows:
        key = (by_vendor_id[vendor_id], normalize_model_code(model.model_code))
        if key in wanted:
            found.setdefault(key, model)
    return found


def _target_model(db: Session, entity: ExtractedEntity) -> PumpModel | None:
    """The model this candidate's run was started to fill in, if it named one.

    The link runs through the run config rather than the candidate, because the candidate
    is produced by reading a page and knows nothing about why the run exists.

    Without this, a datasheet found for the "HZC" would be resolved by name - and a
    datasheet page that writes the designation differently ("HZC-200", "HZC Series")
    creates a second model beside the one the run was started from, leaving the record
    the user was looking at as empty as before.
    """
    batch_id = (entity.payload or {}).get("discovery_batch_id")
    if not batch_id:
        return None
    batch = db.get(ImportBatch, uuid.UUID(str(batch_id)))
    target = (batch.config or {}).get("target_pump_model_id") if batch else None
    if not target:
        return None
    model = db.get(PumpModel, uuid.UUID(str(target)))
    if model is None or model.deleted_at is not None:
        return None
    # A run must not write across a tenancy, whatever its config says.
    if model.tenant_id != entity.tenant_id:
        log.warning(
            "pump_discovery.target_tenant_mismatch",
            pump_model_id=str(model.id),
            entity_tenant=str(entity.tenant_id),
        )
        return None
    return model


def store_candidate(
    db: Session,
    entity: ExtractedEntity,
    *,
    principal=None,
    edits: dict[str, Any] | None = None,
    spec_groups: Sequence[str] | None = None,
    unattended: bool = False,
) -> dict[str, Any]:
    """Write one selected candidate into the system of record.

    Delegates to the shared promotion service, which resolves the vendor, the pump and
    the pump model, then writes each spec group as a new version with field-level
    provenance.

    ``unattended`` is False when a person picked this candidate - a weak subject name is
    reported back rather than silently skipped - and True when a sweep stored it, where
    the name has to stand on its own: a page about "BB3 pumps" names a category, and
    promoting that unattended would create a model called "BB3".
    """
    if entity.entity_type != ENTITY_TYPE:
        raise PromotionError(f"Candidate {entity.id} is not a pump candidate")
    if entity.promoted_at is not None:
        raise PromotionError(f"Candidate {entity.id} was already stored")

    report = promotion.promote_extracted_entity(
        db,
        entity,
        principal=principal,
        reviewer_edits=edits or None,
        decision=(ReviewDecision.ACCEPTED_WITH_EDITS if edits else ReviewDecision.ACCEPTED),
        unattended=unattended,
        spec_groups=spec_groups,
        target_pump_model=_target_model(db, entity),
    )

    model = db.get(PumpModel, uuid.UUID(report["pump_model_id"]))
    vendor = db.get(Vendor, uuid.UUID(report["vendor_id"]))

    # The promotion report is keyed by table; flatten it into the same shape vendor
    # discovery returns so one UI can render either.
    applied: list[str] = []
    refused: dict[str, str] = {}
    for table, outcome in (report.get("targets") or {}).items():
        for field_name in outcome.get("applied") or []:
            applied.append(f"{table}.{field_name}")
        for field_name, reason in (outcome.get("refused") or {}).items():
            refused[f"{table}.{field_name}"] = reason

    log.info(
        "pump_discovery.stored",
        pump_model_id=report["pump_model_id"],
        candidate_id=str(entity.id),
        applied=len(applied),
    )
    return {
        "pump_model_id": report["pump_model_id"],
        "pump_id": report["pump_id"],
        "vendor_id": report["vendor_id"],
        "label": " ".join(
            part
            for part in ((vendor.name if vendor else None), (model.model_code if model else None))
            if part
        )
        or "Pump model",
        "candidate_id": str(entity.id),
        "fields_applied": applied,
        "fields_refused": refused,
    }
