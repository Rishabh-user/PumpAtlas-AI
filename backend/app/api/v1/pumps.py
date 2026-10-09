"""Pump, pump model and spec endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select

from app.ai.parallel_search import pump_model_objective, vendor_range_objective
from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import DataQualityFlag
from app.models.audit import RecordVersion
from app.models.enums import AuditAction, ValueOrigin, VerificationStatus
from app.models.pump import Pump, PumpModel
from app.models.source import Document, Source
from app.models.vendor import Vendor
from app.schemas.common import Message, Page, ProvenanceEntry
from app.schemas.comparison import RecordVersionOut
from app.schemas.entities import (
    PumpCreate,
    PumpIn,
    PumpModelCreate,
    PumpModelIn,
    PumpModelOut,
    PumpOut,
    PumpProfile,
)
from app.schemas.specs import SPEC_REGISTRY
from app.services import (
    audit,
    client_records,
    comparison,
    dedupe,
    designations,
    discovery,
    dispatch,
    indexing,
    provenance,
    pump_discovery,
    quality,
    records,
)
from app.services import search as search_service
from app.services.promotion import (
    is_placeholder_designation,
    normalize_company_name,
    normalize_model_code,
    open_spec_version,
)

router = APIRouter(tags=["pumps"])

SPEC_GROUPS = tuple(SPEC_REGISTRY)


def _get_pump(db: DbSession, pump_id: uuid.UUID) -> Pump:
    pump = db.get(Pump, pump_id)
    if pump is None or pump.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pump not found")
    return pump


def _get_model(db: DbSession, pump_model_id: uuid.UUID) -> PumpModel:
    model = db.get(PumpModel, pump_model_id)
    if model is None or model.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pump model not found")
    return model


@router.get("/pumps", response_model=Page[PumpOut], dependencies=[Depends(require("pump", "read"))])
def list_pumps(
    db: DbSession,
    vendor_id: uuid.UUID | None = None,
    pump_type: list[str] = Query(default_factory=list),
    standard: list[str] = Query(default_factory=list),
    q: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(Pump).where(Pump.deleted_at.is_(None), Pump.merged_into_pump_id.is_(None))
    if vendor_id:
        stmt = stmt.where(Pump.vendor_id == vendor_id)
    if pump_type:
        stmt = stmt.where(Pump.pump_type.in_(pump_type))
    if standard:
        stmt = stmt.where(Pump.applicable_standard.in_(standard))
    if q:
        stmt = stmt.where(Pump.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Pump.name).limit(limit).offset(offset)).all()
    return Page[PumpOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.post(
    "/pumps",
    response_model=PumpOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("pump", "write"))],
)
def create_pump(payload: PumpCreate, principal: CurrentPrincipal, db: DbSession) -> Pump:
    vendor = db.get(Vendor, payload.vendor_id)
    if vendor is None or vendor.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")

    pump = Pump(
        tenant_id=vendor.tenant_id if vendor.tenant_id else principal.tenant_id,
        vendor_id=vendor.id,
        name=payload.name,
        normalized_name=normalize_company_name(payload.name) or payload.name.lower(),
        product_family=payload.product_family,
        service_application=payload.service_application,
        description=payload.description,
        created_by_user_id=principal.user_id,
    )
    if payload.pump_type:
        pump.pump_type = payload.pump_type
    if payload.applicable_standard:
        pump.applicable_standard = payload.applicable_standard
    db.add(pump)
    db.flush()
    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="pumps",
        entity_id=pump.id,
        entity_label=f"{vendor.name} {pump.name}",
        summary="Pump created",
    )
    audit.record_version(db, obj=pump, operation="insert", principal=principal)
    db.commit()
    db.refresh(pump)
    return pump


@router.patch(
    "/pumps/{pump_id}", response_model=PumpOut, dependencies=[Depends(require("pump", "write"))]
)
def update_pump(
    pump_id: uuid.UUID, payload: PumpIn, principal: CurrentPrincipal, db: DbSession
) -> Pump:
    pump = _get_pump(db, pump_id)
    before = audit.snapshot(pump)
    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied")

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL,
        confidence_level=pump.confidence_level,
        changed_by_user_id=principal.user_id,
        tenant_id=pump.tenant_id,
    )
    report = provenance.apply_fields(db, pump, values, context)
    if "name" in report["applied"]:
        pump.normalized_name = normalize_company_name(pump.name) or pump.name.lower()

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="pumps",
        entity_id=pump.id,
        entity_label=pump.name,
        summary=f"Updated {len(report['applied'])} field(s)",
        changes=audit.diff(before, audit.snapshot(pump)),
    )
    audit.record_version(db, obj=pump, operation="update", before=before, principal=principal)
    for model in db.scalars(
        select(PumpModel).where(PumpModel.pump_id == pump.id, PumpModel.deleted_at.is_(None))
    ).all():
        indexing.reindex_pump_model(db, model.id)
    db.commit()
    db.refresh(pump)
    return pump


@router.get(
    "/pump-models",
    response_model=Page[PumpModelOut],
    dependencies=[Depends(require("pump", "read"))],
)
def list_pump_models(
    db: DbSession,
    pump_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(PumpModel).where(PumpModel.deleted_at.is_(None))
    if pump_id:
        stmt = stmt.where(PumpModel.pump_id == pump_id)
    if vendor_id:
        stmt = stmt.join(Pump, Pump.id == PumpModel.pump_id).where(Pump.vendor_id == vendor_id)
    if q:
        stmt = stmt.where(PumpModel.model_code.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(PumpModel.model_code).limit(limit).offset(offset)).all()
    return Page[PumpModelOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.post(
    "/pump-models",
    response_model=PumpModelOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("pump", "write"))],
)
def create_pump_model(
    payload: PumpModelCreate, principal: CurrentPrincipal, db: DbSession
) -> PumpModel:
    pump = _get_pump(db, payload.pump_id)
    target = normalize_model_code(payload.model_code)
    for existing in db.scalars(
        select(PumpModel).where(PumpModel.pump_id == pump.id, PumpModel.deleted_at.is_(None))
    ).all():
        if normalize_model_code(existing.model_code) == target:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Model code '{existing.model_code}' already exists with id {existing.id}",
            )

    model = PumpModel(
        tenant_id=pump.tenant_id,
        pump_id=pump.id,
        model_code=payload.model_code,
        size_designation=payload.size_designation,
        stages=payload.stages,
        orientation=payload.orientation,
        tag_number=payload.tag_number,
        project_reference=payload.project_reference,
        created_by_user_id=principal.user_id,
    )
    db.add(model)
    db.flush()
    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="pump_models",
        entity_id=model.id,
        entity_label=model.model_code,
        summary="Pump model created",
    )
    audit.record_version(db, obj=model, operation="insert", principal=principal)
    indexing.reindex_pump_model(db, model.id)
    dedupe.scan_pump_model(db, model)
    db.commit()
    db.refresh(model)
    return model


@router.post(
    "/pump-models/{pump_model_id}/enrich",
    dependencies=[Depends(require("pump", "write"))],
)
def enrich_pump_model(
    pump_model_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    max_results: int = Query(default=6, ge=1, le=25),
    auto_apply: bool = Query(
        default=True,
        description=(
            "Write confident values onto this model as each page is read. The run names "
            "this record as its target, so there is no ambiguity about where the values "
            "land; turn it off to review them in the AI queue first."
        ),
    ),
) -> dict:
    """Fill in this pump model from the web.

    A model discovered from a product page is a designation and a pump type: the page
    named the product and said what it is for, and nothing about what it costs, how long
    it takes to deliver, what it weighs or how it performs. Across this database that
    shows as technical specifications on 64 of 84 models and commercial specifications on
    none - which is why a profile can read "Not recorded" against every panel while the
    record is badged AI extracted.

    This asks the question a datasheet answers - rated capacity, head, NPSHr, efficiency,
    speed, materials, seal plan, weights, dimensions, lead time - reads each page it
    finds, and applies what it can quote. Every value carries a verbatim quote and the
    page it came from.

    The run names this record as its target, so a datasheet that writes the designation
    differently fills this model rather than creating a second one beside it.
    """
    model = _get_model(db, pump_model_id)
    pump = _get_pump(db, model.pump_id)
    vendor = db.get(Vendor, pump.vendor_id)
    if vendor is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This model has no manufacturer, so there is nothing specific to search for.",
        )

    # A placeholder - "Bornerman unspecified line (unspecified variant)" - has no
    # designation to search for, and asking the web for its datasheet is asking for a
    # product that does not exist: the first run against one read two pages, found
    # nothing and reported the record could not be filled. So the question changes to the
    # one that can be answered - what does this manufacturer actually sell - and the
    # answers become models of their own rather than values written onto a row that
    # stands for nothing.
    placeholder = is_placeholder_designation(model.model_code)
    designation = designations.product_name(model.model_code) or model.model_code
    if placeholder:
        objective, queries = vendor_range_objective(vendor.name)
        query = vendor.name
    else:
        objective, queries = pump_model_objective(vendor.name, designation)
        query = f"{vendor.name} {designation}"

    batch = discovery.start_run(
        db,
        pump_discovery.KIND,
        tenant_id=model.tenant_id,
        query=query,
        country=vendor.hq_country,
        objective=objective,
        queries=queries,
        max_results=max_results,
        user_id=principal.user_id,
        # Never onto a placeholder: a real model found for this manufacturer is its own
        # record, and forcing it onto this row would name Bornerman's actual pump
        # "Bornerman unspecified line (unspecified variant)".
        target_pump_model_id=None if placeholder else model.id,
        auto_store=auto_apply,
        transport="celery" if dispatch.broker_available() else "in_process",
    )
    audit.record_audit(
        db,
        action=AuditAction.IMPORT,
        principal=principal,
        entity_type="pump_models",
        entity_id=model.id,
        entity_label=f"{vendor.name} {model.model_code}",
        summary="Pump model enrichment started from the web",
        context={"objective": objective, "queries": queries, "auto_apply": auto_apply},
    )
    db.commit()

    from app.workers.tasks import discovery_task

    outcome = dispatch.dispatch(
        celery_task=discovery_task,
        celery_args=(
            pump_discovery.KIND.slug,
            str(batch.id),
            str(model.tenant_id) if model.tenant_id else None,
            str(principal.user_id) if principal.user_id else None,
        ),
        fallback=_enrichment_runner(),
        fallback_kwargs={"batch_id": batch.id, "user_id": principal.user_id},
        tenant_id=model.tenant_id,
        name="pump-enrichment",
    )
    discovery.record_transport(db, batch.id, outcome["transport"], outcome["task_id"])
    db.commit()

    return {
        "run_id": str(batch.id),
        "pump_model_id": str(model.id),
        "queries": queries,
        "transport": outcome.get("transport"),
        # So the screen can watch it with the panel that already knows how.
        "watch": f"/pump-discovery/{batch.id}",
        "auto_apply": auto_apply,
        # Which question was asked, so the screen can say where the answers will land.
        "strategy": "product_range" if placeholder else "datasheet",
    }


def _enrichment_runner():
    """Bind the pump kind for the in-process fallback, which passes only ids."""

    def run(db, *, batch_id, user_id):
        return discovery.run_discovery(db, pump_discovery.KIND, batch_id, user_id)

    return run


@router.get(
    "/pump-models/{pump_model_id}",
    response_model=PumpProfile,
    dependencies=[Depends(require("pump", "read"))],
)
def pump_profile(
    pump_model_id: uuid.UUID,
    db: DbSession,
    include_similar: bool = Query(default=True),
) -> PumpProfile:
    """The pump profile page in one call: specs, scores, flags, provenance, sources."""
    model = _get_model(db, pump_model_id)
    pump = _get_pump(db, model.pump_id)
    vendor = db.get(Vendor, pump.vendor_id)
    specs = records.current_specs(db, pump_model_id)

    spec_payload: dict[str, Any] = {}
    for group, spec in specs.items():
        if spec is None:
            spec_payload[group] = None
            continue
        spec_payload[group] = records.to_jsonable(
            {c.name: getattr(spec, c.name) for c in spec.__table__.columns}
        )

    # The six spec rows are already loaded; reuse them for scoring and provenance
    # rather than re-querying them twice more.
    flat_record = records.flatten_pump_model(db, pump_model_id, specs=specs)
    cards, _ = comparison.score_pump_model(
        db, pump_model_id, None, persist=False, record=flat_record
    )
    flags = db.scalars(
        select(DataQualityFlag)
        .where(
            DataQualityFlag.entity_id.in_([model.id, pump.id, pump.vendor_id]),
            DataQualityFlag.is_resolved.is_(False),
        )
        .limit(100)
    ).all()

    documents = db.scalars(
        select(Document)
        .where(Document.pump_model_id == model.id)
        .order_by(Document.created_at.desc())
        .limit(50)
    ).all()

    source_ids = {spec.source_id for spec in specs.values() if spec is not None and spec.source_id}
    if model.primary_source_id:
        source_ids.add(model.primary_source_id)
    sources = (
        db.scalars(select(Source).where(Source.id.in_(source_ids))).all() if source_ids else []
    )

    return PumpProfile(
        pump_model=records.to_jsonable(
            {c.name: getattr(model, c.name) for c in model.__table__.columns}
        ),
        pump=records.to_jsonable({c.name: getattr(pump, c.name) for c in pump.__table__.columns}),
        vendor=records.to_jsonable(
            {c.name: getattr(vendor, c.name) for c in client_records.vendor_columns(db)}
        )
        if vendor
        else {},
        specs=spec_payload,
        scorecards=[
            {
                "kind": card.kind.value,
                "score": card.score,
                "grade": card.grade,
                "fields_evaluated": card.fields_evaluated,
                "fields_missing": card.fields_missing,
                "disqualified": card.disqualified,
                "disqualification_reason": card.disqualification_reason,
                "breakdown": records.to_jsonable(card.breakdown()),
            }
            for card in cards.values()
        ],
        open_flags=[
            {
                "id": str(flag.id),
                "entity_type": flag.entity_type,
                "field_name": flag.field_name,
                "flag_type": flag.flag_type.value,
                "severity": flag.severity.value,
                "message": flag.message,
                "suggested_fix": flag.suggested_fix,
            }
            for flag in flags
        ],
        provenance_summary=records.provenance_summary(
            db, records.provenance_targets_for_pump_model(db, model.id, specs=specs)
        ),
        documents=[
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "document_kind": doc.document_kind.value,
                "size_bytes": doc.size_bytes,
                "page_count": doc.page_count,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in documents
        ],
        sources=[
            {
                "id": str(src.id),
                "title": src.title,
                "source_type": src.source_type.value,
                "source_url": src.source_url,
                "captured_at": src.captured_at.isoformat() if src.captured_at else None,
                "confidence_level": src.confidence_level.value,
                "is_authoritative": src.is_authoritative,
            }
            for src in sources
        ],
        similar=(
            search_service.find_similar_pump_models(db, pump_model_id, limit=6)
            if include_similar
            else []
        ),
    )


@router.patch(
    "/pump-models/{pump_model_id}",
    response_model=PumpModelOut,
    dependencies=[Depends(require("pump", "write"))],
)
def update_pump_model(
    pump_model_id: uuid.UUID,
    payload: PumpModelIn,
    principal: CurrentPrincipal,
    db: DbSession,
) -> PumpModel:
    model = _get_model(db, pump_model_id)
    before = audit.snapshot(model)
    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied")

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL,
        confidence_level=model.confidence_level,
        changed_by_user_id=principal.user_id,
        tenant_id=model.tenant_id,
    )
    report = provenance.apply_fields(db, model, values, context)
    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="pump_models",
        entity_id=model.id,
        entity_label=model.model_code,
        summary=f"Updated {len(report['applied'])} field(s)",
        changes=audit.diff(before, audit.snapshot(model)),
    )
    audit.record_version(db, obj=model, operation="update", before=before, principal=principal)
    indexing.reindex_pump_model(db, model.id)
    comparison.mark_scores_stale(db, model.id)
    db.commit()
    db.refresh(model)
    return model


@router.get(
    "/pump-models/{pump_model_id}/specs/{group}", dependencies=[Depends(require("pump", "read"))]
)
def get_spec(
    pump_model_id: uuid.UUID,
    db: DbSession,
    group: str = Path(description=f"One of: {', '.join(SPEC_GROUPS)}"),
    version: int | None = Query(default=None, description="Omit for the current version"),
) -> dict:
    """Read one spec group. Older versions stay readable for change tracking."""
    if group not in SPEC_REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown spec group '{group}'")
    _get_model(db, pump_model_id)
    spec_cls, read_schema, _ = SPEC_REGISTRY[group]

    stmt = select(spec_cls).where(spec_cls.pump_model_id == pump_model_id)
    stmt = (
        stmt.where(spec_cls.version == version)
        if version is not None
        else stmt.where(spec_cls.is_current.is_(True))
    )
    spec = db.scalar(stmt.order_by(spec_cls.version.desc()).limit(1))
    if spec is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No {group} spec recorded for this pump model"
            + (f" at version {version}" if version else ""),
        )
    return {
        "group": group,
        "version": spec.version,
        "is_current": spec.is_current,
        "data": read_schema.model_validate(spec).model_dump(),
    }


@router.put(
    "/pump-models/{pump_model_id}/specs/{group}", dependencies=[Depends(require("pump", "write"))]
)
def upsert_spec(
    pump_model_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    group: str = Path(description=f"One of: {', '.join(SPEC_GROUPS)}"),
    payload: dict = Body(description="Spec fields to write"),
    mark_verified: bool = Query(default=False, description="Record these values as human-verified"),
) -> dict:
    """Write a spec group as a **new version**. The previous version is retired, not lost."""
    if group not in SPEC_REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown spec group '{group}'")
    if not principal.can(f"{group}_spec", "write"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Role does not permit writing {group} specs"
        )

    model = _get_model(db, pump_model_id)
    spec_cls, read_schema, write_schema = SPEC_REGISTRY[group]
    try:
        validated = write_schema.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    values = validated.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No spec fields supplied")

    from app.models.enums import ConfidenceLevel

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL,
        confidence_level=(
            ConfidenceLevel.VERIFIED if mark_verified else ConfidenceLevel.VENDOR_DECLARED
        ),
        changed_by_user_id=principal.user_id,
        tenant_id=model.tenant_id,
    )
    spec = open_spec_version(
        db, spec_cls, tenant_id=model.tenant_id, pump_model=model, context=context
    )
    # open_spec_version already carried the previous version's values and their
    # provenance forward, so a PUT of one field is not a data-loss event.
    report = provenance.apply_fields(db, spec, values, context)
    if mark_verified:
        spec.verification_status = VerificationStatus.VERIFIED

    flat = records.flatten_pump_model(db, model.id)
    findings = quality.validate_record(spec_cls.__tablename__, flat)
    quality.persist_findings(
        db,
        tenant_id=model.tenant_id,
        entity_type="pump_models",
        entity_id=model.id,
        findings=findings,
    )

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type=spec_cls.__tablename__,
        entity_id=spec.id,
        entity_label=f"{model.model_code} {group} v{spec.version}",
        summary=f"Wrote {len(report['applied'])} field(s) as version {spec.version}",
        changes={"applied": report["applied"], "refused": report["refused"]},
    )
    audit.record_version(db, obj=spec, operation="insert", principal=principal)
    indexing.reindex_pump_model(db, model.id)
    comparison.mark_scores_stale(db, model.id)
    db.commit()
    db.refresh(spec)
    return {
        "group": group,
        "version": spec.version,
        "applied": report["applied"],
        "unchanged": report["unchanged"],
        "refused": report["refused"],
        "quality_flags_raised": len(findings),
        "data": read_schema.model_validate(spec).model_dump(exclude_none=True),
    }


@router.get(
    "/pump-models/{pump_model_id}/specs/{group}/versions",
    dependencies=[Depends(require("pump", "read"))],
)
def spec_versions(
    pump_model_id: uuid.UUID,
    db: DbSession,
    group: str = Path(description=f"One of: {', '.join(SPEC_GROUPS)}"),
) -> list[dict]:
    """Version history for one spec group - the change-tracking view."""
    if group not in SPEC_REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown spec group '{group}'")
    _get_model(db, pump_model_id)
    spec_cls, _, _ = SPEC_REGISTRY[group]
    rows = db.scalars(
        select(spec_cls)
        .where(spec_cls.pump_model_id == pump_model_id)
        .order_by(spec_cls.version.desc())
    ).all()
    return [
        {
            "version": row.version,
            "is_current": row.is_current,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "superseded_at": row.superseded_at.isoformat() if row.superseded_at else None,
            "confidence_level": row.confidence_level.value,
            "verification_status": row.verification_status.value,
            "source_id": str(row.source_id) if row.source_id else None,
            "ai_job_id": str(row.ai_job_id) if row.ai_job_id else None,
            "created_by_user_id": (str(row.created_by_user_id) if row.created_by_user_id else None),
        }
        for row in rows
    ]


@router.get(
    "/pump-models/{pump_model_id}/provenance",
    response_model=list[ProvenanceEntry],
    dependencies=[Depends(require("pump", "read"))],
)
def pump_model_provenance(
    pump_model_id: uuid.UUID,
    db: DbSession,
    field_name: str | None = Query(default=None),
    entity_type: str = Query(
        default="pump_models",
        description="pump_models | technical_specs | commercial_specs | ...",
    ),
) -> list:
    """Where every value came from. This is the answer to an audit question."""
    model = _get_model(db, pump_model_id)
    if entity_type == "pump_models":
        return provenance.field_history(db, "pump_models", model.id, field_name)

    spec_group = entity_type.removesuffix("_specs")
    if spec_group not in SPEC_REGISTRY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown entity type '{entity_type}'")
    spec_cls, _, _ = SPEC_REGISTRY[spec_group]
    spec = db.scalar(
        select(spec_cls).where(spec_cls.pump_model_id == model.id, spec_cls.is_current.is_(True))
    )
    if spec is None:
        return []
    return provenance.field_history(db, spec_cls.__tablename__, spec.id, field_name)


@router.get(
    "/pump-models/{pump_model_id}/history",
    response_model=list[RecordVersionOut],
    dependencies=[Depends(require("pump", "read"))],
)
def pump_model_history(
    pump_model_id: uuid.UUID,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=500),
) -> list:
    """Row-level snapshots for this model and its specs, newest first."""
    model = _get_model(db, pump_model_id)
    spec_ids = [model.id]
    for spec_cls, _, _ in SPEC_REGISTRY.values():
        spec_ids.extend(
            db.scalars(select(spec_cls.id).where(spec_cls.pump_model_id == model.id)).all()
        )
    return list(
        db.scalars(
            select(RecordVersion)
            .where(RecordVersion.entity_id.in_(spec_ids))
            .order_by(RecordVersion.created_at.desc())
            .limit(limit)
        ).all()
    )


@router.post(
    "/pump-models/{pump_model_id}/verify",
    response_model=Message,
    dependencies=[Depends(require("technical_spec", "approve"))],
)
def verify_pump_model(
    pump_model_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    verification_method: str = Query(
        default="document review", description="How the record was verified"
    ),
) -> Message:
    """Mark a record human-verified. Protects its fields from being overwritten by AI."""
    from datetime import UTC, datetime

    from app.models.enums import ConfidenceLevel

    model = _get_model(db, pump_model_id)
    model.verification_status = VerificationStatus.VERIFIED
    model.confidence_level = ConfidenceLevel.VERIFIED
    model.last_reviewed_at = datetime.now(UTC)

    for spec in records.current_specs(db, pump_model_id).values():
        if spec is not None:
            spec.verification_status = VerificationStatus.VERIFIED
            spec.confidence_level = ConfidenceLevel.VERIFIED

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="pump_models",
        entity_id=model.id,
        entity_label=model.model_code,
        summary=f"Record verified ({verification_method})",
        context={"verification_method": verification_method},
    )
    indexing.reindex_pump_model(db, model.id)
    db.commit()
    return Message(
        detail="Record marked verified. AI enrichment will no longer overwrite these fields."
    )


@router.delete(
    "/pump-models/{pump_model_id}",
    response_model=Message,
    dependencies=[Depends(require("pump", "delete"))],
)
def delete_pump_model(
    pump_model_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> Message:
    model = _get_model(db, pump_model_id)
    model.deleted_at = func.now()
    audit.record_audit(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        entity_type="pump_models",
        entity_id=model.id,
        entity_label=model.model_code,
        summary="Pump model soft deleted",
    )
    indexing.reindex_pump_model(db, model.id)
    db.commit()
    return Message(detail="Pump model deleted")
