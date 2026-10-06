"""AI discovery endpoints, for vendors and for pump models.

Three calls make the flow, and they are identical for both kinds:

1. ``POST /{kind}-discovery`` starts a run and returns immediately.
2. ``GET  /{kind}-discovery/{run_id}`` is polled while it runs, and reports what each
   provider is doing plus the candidates found so far.
3. ``POST /{kind}-discovery/{run_id}/select`` writes the candidates a person picked, and
   marks the rest rejected.

Nothing reaches the system of record without step 3. That is the point of the split:
Parallel AI and Gemma produce candidates, a person decides, and only then does anything
get written.

The prefixes are deliberately ``/vendor-discovery`` and ``/pump-discovery`` rather than
``/vendors/ai-discovery`` and ``/pump-models/ai-discovery``. A static segment under a
collection sits in the shadow of that collection's ``/{id}`` route and resolves correctly
only while the routers happen to be registered in the right order — a trap this codebase
has already been caught by twice, which is why ``/vendor-comparison`` and ``/my-tenant``
are shaped the same way.

One router factory serves both kinds so the two contracts cannot drift; the frontend
drives them with the same component.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.ai.parallel_search import PUMP_TYPE_PHRASES, SERVICE_PHRASES
from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import ExtractedEntity
from app.models.enums import AuditAction, IngestionStatus, ReviewDecision
from app.models.source import ImportBatch, Source
from app.schemas.discovery import (
    MAX_SWEEP_COUNTRIES,
    DiscoveryRun,
    DiscoverySelectRequest,
    DiscoverySelectResponse,
    DiscoveryStartRequest,
)
from app.services import (
    audit,
    designations,
    discovery,
    dispatch,
    indexing,
    promotion,
    pump_discovery,
    vendor_discovery,
)
from app.services.discovery import DiscoveryKind
from app.services.promotion import PromotionError

RUNNING_STATUSES = {
    IngestionStatus.QUEUED,
    IngestionStatus.FETCHING,
    IngestionStatus.PARSING,
    IngestionStatus.PARSED,
    IngestionStatus.EXTRACTING,
}

#: A pump datasheet yields values across four groups at once, so all four are written.
#: Operational and administrative data comes from reference lists and questionnaires
#: rather than a datasheet, so those groups are left for the normal ingestion path.
#:
#: A sweep multiplies pages by the number of segments and every page is one reading-model
#: call, so this is a time and cost ceiling rather than a limit on ambition: the total is
#: capped and the per-segment count trimmed to fit rather than silently accepted, and the
#: frontend shows the projection before the click.
#:
#: Raised from 150 to cover a real vendor sweep. 60 supply countries at 10 pages each is
#: 600 reads; at the 5-90 seconds a page has been observed to take, that is a run measured
#: in hours. It is meant to be started deliberately, left alone, and cancelled when it has
#: found enough - which is why cancel keeps what it found, and why auto-store exists.
MAX_SWEEP_PAGES = 900

PUMP_SPEC_GROUPS = (
    "technical_spec",
    "commercial_spec",
    "dimensional_spec",
    "delivery_spec",
)

#: Candidate fields shown to a reviewer, in this order. The lists mirror what storing
#: would actually write, so the panel is a preview and not a summary.
VENDOR_DISPLAY_FIELDS = (
    "legal_entity_name",
    "website",
    "hq_country",
    "hq_city",
    "vendor_tier",
    "vendor_category",
    "product_families",
    "manufacturing_countries",
    "certifications",
    "approval_status",
    "sanctions_status",
    "annual_revenue_usd",
    "revenue_year",
    "employee_count",
    "credit_rating",
    "credit_rating_agency",
    "total_units_supplied",
    "on_time_delivery_pct",
    "fpso_offshore_experience",
    "notable_references",
    "description",
)

PUMP_DISPLAY_FIELDS = (
    "pump_type",
    "applicable_standard",
    "service_application",
    "handled_fluids",
    "rated_capacity_m3h",
    "min_capacity_m3h",
    "max_capacity_m3h",
    "rated_head_m",
    "max_head_m",
    "npsh_required_m",
    "hydraulic_efficiency_pct",
    "bep_efficiency_pct",
    "rated_power_kw",
    "rated_speed_rpm",
    "stages",
    "orientation",
    "material_class",
    "seal_system_type",
    "seal_piping_plan",
    "area_classification",
    "casing_design_pressure_barg",
    "fluid_temperature_max_c",
    "certifications",
    "nace_mr0175_compliant",
    "base_price_amount",
    "base_price_currency",
    "warranty_months",
    "standard_lead_time_weeks",
    "country_of_origin",
    "dry_weight_kg",
    "operating_weight_kg",
)


def _label(field_name: str) -> str:
    return field_name.replace("_", " ").capitalize()


def build_router(
    kind: DiscoveryKind,
    *,
    display_fields: tuple[str, ...],
    store_candidate,
    existing_map,
    blocked_reason,
    spec_groups: tuple[str, ...] | None = None,
    reindex,
    audit_entity_type: str,
) -> APIRouter:
    """One router per discovery kind. The path shapes are identical by construction."""
    router = APIRouter(prefix=f"/{kind.slug}-discovery", tags=[f"{kind.slug}s"])

    def get_run(db: DbSession, run_id: uuid.UUID) -> ImportBatch:
        batch = db.get(ImportBatch, run_id)
        if batch is None or batch.import_mode != kind.import_mode:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Discovery run not found")
        return batch

    def candidate_out(
        entity: ExtractedEntity,
        source: Source | None,
        existing: tuple[uuid.UUID, str] | None,
    ) -> dict[str, Any]:
        """Render one candidate. Pure: the source row and the duplicate match are
        resolved in bulk by the caller, because each of them is a database round trip
        and this runs once per candidate on every poll."""
        payload = entity.payload or {}
        fields: dict[str, Any] = payload.get("fields") or {}
        confidences = entity.field_confidences or {}
        evidence = entity.evidence_spans or {}
        subject = payload.get("subject") or {}

        families = fields.get("product_families")
        return {
            "id": entity.id,
            "title": subject.get("model_code") or subject.get("vendor_name"),
            "subtitle": (
                subject.get("vendor_name")
                if subject.get("model_code")
                else fields.get("hq_country")
            ),
            "vendor_name": subject.get("vendor_name"),
            "model_code": subject.get("model_code"),
            "pump_name": subject.get("pump_name") or fields.get("pump_name"),
            "website": fields.get("website"),
            "hq_country": fields.get("hq_country") or fields.get("country_of_origin"),
            "hq_city": fields.get("hq_city"),
            "vendor_tier": fields.get("vendor_tier"),
            "pump_type": fields.get("pump_type"),
            "applicable_standard": fields.get("applicable_standard"),
            "product_families": families if isinstance(families, list) else [],
            "overall_confidence": (
                float(entity.overall_confidence) if entity.overall_confidence is not None else None
            ),
            "relevance_reason": payload.get("relevance_reason"),
            "oil_gas_evidence": payload.get("oil_gas_evidence"),
            "field_count": len(fields),
            "fields": [
                {
                    "field_name": name,
                    "label": _label(name),
                    "value": fields[name],
                    "confidence": confidences.get(name),
                    "evidence": (evidence.get(name) or {}).get("quote"),
                }
                for name in display_fields
                if name in fields and fields[name] not in (None, "", [])
            ],
            "unresolved": payload.get("unresolved") or [],
            "source_url": source.source_url if source else None,
            "source_title": source.title if source else None,
            "decision": (
                entity.review_decision.value
                if hasattr(entity.review_decision, "value")
                else str(entity.review_decision)
            ),
            "blocked_reason": (None if entity.promoted_at else blocked_reason(subject, fields)),
            # "OH1 B Series" is stored as the B Series, because OH1 is the configuration
            # and not the name. Said here so a reviewer sees it before the click rather
            # than finding a differently-named record afterwards.
            "stored_as": _stored_as(subject, fields),
            "stored_id": entity.target_id if entity.promoted_at else None,
            "matches_existing_id": existing[0] if existing else None,
            "matches_existing_label": existing[1] if existing else None,
        }

    def _stored_as(subject: dict, fields: dict) -> str | None:
        stated = subject.get("model_code") or fields.get("model_code")
        if not stated:
            return None
        cleaned = designations.product_name(stated)
        return cleaned if cleaned != str(stated).strip() else None

    def render_candidates(db: DbSession, batch: ImportBatch) -> list[dict[str, Any]]:
        """Every candidate for a run, in a fixed number of queries.

        This is the discovery poll's whole cost. The obvious shape - load the
        candidates, then per candidate fetch its source and ask whether a matching
        record already exists - is three round trips each, and against a hosted
        database at a third of a second per round trip thirty candidates took half a
        minute. The poll then piled up faster than it drained and the browser gave up
        with "failed to fetch". So the sources come back with the candidates, and the
        duplicate matches are resolved for all of them at once.
        """
        pairs = discovery.candidates_with_sources(db, kind, batch.id)
        if not pairs:
            return []

        # Only unstored candidates can match something; a stored one *is* the record.
        pending = [entity for entity, _ in pairs if entity.promoted_at is None]
        subjects = [(entity.payload or {}).get("subject") or {} for entity in pending]
        matches = dict(
            zip(
                (entity.id for entity in pending),
                existing_map(db, batch.tenant_id, subjects),
                strict=True,
            )
        )
        return [candidate_out(entity, source, matches.get(entity.id)) for entity, source in pairs]

    def run_out(db: DbSession, batch: ImportBatch, *, include_candidates: bool = True) -> dict:
        config = batch.config or {}
        rendered = render_candidates(db, batch) if include_candidates else []
        # The list view skips rendering candidates but must still report how many there
        # are: a row saying "0 found" when two are waiting reads as a failed run.
        total_candidates, stored_candidates = (
            (len(rendered), sum(1 for c in rendered if c["stored_id"]))
            if include_candidates
            else discovery.candidate_counts(db, kind, batch.id)
        )
        jobs, job_count = discovery.job_summary(db, batch.id)
        return {
            "id": batch.id,
            "kind": kind.slug,
            "sweep": bool(config.get("sweep")),
            "auto_store": bool(config.get("auto_store")),
            "segment_count": len(config.get("segments") or []) or 1,
            "name": batch.name,
            "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
            "objective": config.get("objective"),
            "queries": config.get("queries") or [],
            "query": config.get("query") or config.get("pump_type"),
            "country": config.get("country"),
            "transport": config.get("transport"),
            "is_running": batch.status in RUNNING_STATUSES,
            "cancel_requested": bool(config.get("cancel_requested")),
            "stages": config.get("stages") or discovery.initial_stages(kind),
            "jobs": jobs,
            "job_count": job_count,
            "candidates": rendered,
            "pages_found": batch.total_items,
            "pages_screened": batch.processed_items,
            "pages_failed": batch.failed_items,
            "candidate_count": total_candidates,
            "stored_count": stored_candidates,
            "error_summary": batch.error_summary,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        }

    @router.post(
        "",
        response_model=DiscoveryRun,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require("ingestion", "write"))],
    )
    def start_discovery(
        payload: DiscoveryStartRequest, principal: CurrentPrincipal, db: DbSession
    ) -> dict:
        """Start a run. Returns the run record immediately; poll it for progress."""
        per_search = payload.max_results
        if payload.sweep:
            scope = payload.sweep_scope
            if scope is not None and scope not in kind.sweep_scopes:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{kind.noun.capitalize()} discovery cannot sweep by {scope!r}. "
                    f"Available: {', '.join(sorted(kind.sweep_scopes)) or 'none'}.",
                )
            segment_count = len(
                discovery.plan_sweep(
                    kind, payload.country, scope=scope, countries=payload.countries
                )
            )
            # Trim rather than refuse: the caller asked for breadth, and fewer pages per
            # segment still delivers it. Breadth comes from the segment count.
            per_search = max(1, min(per_search, MAX_SWEEP_PAGES // max(1, segment_count)))

        # Probed before the run exists, so the value is in `config` from the start —
        # the runner owns that column the moment it begins.
        planned_transport = "celery" if dispatch.broker_available() else "in_process"

        batch = discovery.start_run(
            db,
            kind,
            tenant_id=principal.tenant_id,
            query=payload.query,
            country=payload.country,
            objective=payload.objective,
            max_results=per_search,
            user_id=principal.user_id,
            sweep=payload.sweep,
            sweep_scope=payload.sweep_scope,
            countries=payload.countries,
            auto_store=payload.auto_store,
            min_confidence=payload.min_confidence,
            transport=planned_transport,
        )
        audit.record_audit(
            db,
            action=AuditAction.IMPORT,
            principal=principal,
            entity_type="import_batches",
            entity_id=batch.id,
            entity_label=batch.name,
            summary=(
                f"AI {kind.slug} discovery started for "
                f"{payload.query or (batch.config or {}).get('objective')}"
            ),
            context={"objective": (batch.config or {}).get("objective")},
        )
        db.commit()

        from app.workers.tasks import discovery_task

        outcome = dispatch.dispatch(
            celery_task=discovery_task,
            celery_args=(
                kind.slug,
                str(batch.id),
                str(principal.tenant_id) if principal.tenant_id else None,
                str(principal.user_id) if principal.user_id else None,
            ),
            fallback=_run_for_kind(kind),
            fallback_kwargs={"batch_id": batch.id, "user_id": principal.user_id},
            tenant_id=principal.tenant_id,
            name=f"{kind.slug}-discovery",
        )

        # Only needed when the broker answered the probe then refused the publish.
        if outcome["transport"] != planned_transport or outcome["task_id"]:
            discovery.record_transport(db, batch.id, outcome["transport"], outcome["task_id"])
        db.refresh(batch)

        return run_out(db, batch)

    @router.get("/scopes", dependencies=[Depends(require("ingestion", "read"))])
    def scopes() -> dict:
        """What this kind can sweep, and how big each sweep would be.

        Served rather than hardcoded in the frontend: the projection a person sees before
        starting an hours-long run has to come from the same vocabulary the run will use,
        or it lies the moment a pump type or a supply country is added.
        """
        options = []
        for name in sorted(kind.sweep_scopes) or []:
            segments = kind.segments_for(name)
            options.append(
                {
                    "scope": name,
                    "segment_count": len(segments),
                    "examples": [segment.label for segment in segments[:6]],
                    "is_default": kind.sweep_scopes.get(name) is kind.sweep_segments,
                }
            )
        return {
            "kind": kind.slug,
            "scopes": options,
            "max_sweep_pages": MAX_SWEEP_PAGES,
            "max_countries": MAX_SWEEP_COUNTRIES,
            # What the form can compose a query from. Served rather than duplicated in
            # the frontend, because these phrases are what the search provider is
            # actually asked - a paraphrase in the UI would search for something else
            # than the label promised.
            "pump_types": [
                {"value": value, "phrase": phrase} for value, phrase in PUMP_TYPE_PHRASES.items()
            ],
            "services": [
                {"value": value, "phrase": phrase} for value, phrase in SERVICE_PHRASES.items()
            ],
        }

    @router.get(
        "",
        response_model=list[DiscoveryRun],
        dependencies=[Depends(require("ingestion", "read"))],
    )
    def list_runs(db: DbSession, limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
        """Recent runs, newest first — without candidates, so the list stays cheap."""
        batches = db.scalars(
            select(ImportBatch)
            .where(ImportBatch.import_mode == kind.import_mode)
            .order_by(ImportBatch.created_at.desc())
            .limit(limit)
        ).all()
        return [run_out(db, batch, include_candidates=False) for batch in batches]

    @router.get(
        "/{run_id}",
        response_model=DiscoveryRun,
        dependencies=[Depends(require("ingestion", "read"))],
    )
    def get_one(run_id: uuid.UUID, db: DbSession) -> dict:
        """Poll this while the run is in progress.

        The stall check runs here because this is where somebody is waiting. A run whose
        provider call died silently used to keep reporting "in progress" until the next
        API restart; now the person watching it is the one who discovers it, which is
        the same moment they would otherwise start wondering.
        """
        discovery.reap_stalled_runs(db)
        return run_out(db, get_run(db, run_id))

    @router.post(
        "/{run_id}/select",
        response_model=DiscoverySelectResponse,
        dependencies=[Depends(require("vendor", "write"))],
    )
    # Not named `select`: these handlers are closures inside `build_router`, so a
    # handler called `select` shadows SQLAlchemy's `select` for every other handler in
    # the same scope - which turned `list_runs` into a 500.
    def select_candidates(
        run_id: uuid.UUID,
        payload: DiscoverySelectRequest,
        principal: CurrentPrincipal,
        db: DbSession,
    ) -> dict:
        """Store the chosen candidates; mark the others rejected.

        Each candidate is committed on its own. One that cannot be stored — a name the
        model never resolved, say — is reported in ``failed`` and leaves the rest
        untouched, rather than rolling back a batch of good records.
        """
        batch = get_run(db, run_id)
        by_id = {
            entity.id: entity
            for entity in db.scalars(discovery.candidate_query(kind, batch.id)).all()
        }

        stored: list[dict] = []
        rejected: list[uuid.UUID] = []
        failed: dict[str, str] = {}

        for selection in payload.store:
            entity = by_id.get(selection.candidate_id)
            if entity is None:
                failed[str(selection.candidate_id)] = "Candidate does not belong to this run"
                continue
            try:
                kwargs: dict[str, Any] = {"principal": principal, "edits": selection.edits or None}
                if spec_groups is not None:
                    kwargs["spec_groups"] = spec_groups
                report = store_candidate(db, entity, **kwargs)
                reindex(db, report)
                audit.record_audit(
                    db,
                    action=AuditAction.CREATE,
                    principal=principal,
                    entity_type=audit_entity_type,
                    entity_id=uuid.UUID(report[f"{kind.slug}_id"])
                    if f"{kind.slug}_id" in report
                    else None,
                    entity_label=report.get("label") or report.get("vendor_name"),
                    summary=f"{kind.noun.capitalize()} stored from AI discovery",
                    context={
                        "run_id": str(batch.id),
                        "candidate_id": str(entity.id),
                        "fields_applied": report["fields_applied"],
                    },
                )
                db.commit()
                stored.append(
                    {
                        "id": report.get("vendor_id")
                        if kind.slug == "vendor"
                        else report.get("pump_model_id"),
                        "label": report.get("label") or report.get("vendor_name") or "",
                        "candidate_id": str(entity.id),
                        "fields_applied": report["fields_applied"],
                        "fields_refused": report["fields_refused"],
                    }
                )
            except (PromotionError, ValueError) as exc:
                db.rollback()
                failed[str(selection.candidate_id)] = str(exc)

        for candidate_id in payload.reject:
            entity = by_id.get(candidate_id)
            if entity is None:
                failed[str(candidate_id)] = "Candidate does not belong to this run"
                continue
            discovery.reject_candidate(db, entity, principal=principal)
            rejected.append(candidate_id)

        if stored or rejected:
            batch.promoted_items = (batch.promoted_items or 0) + len(stored)
            batch.needs_review_items = max(
                0, (batch.needs_review_items or 0) - len(stored) - len(rejected)
            )
            if batch.needs_review_items == 0 and batch.status == IngestionStatus.NEEDS_REVIEW:
                batch.status = IngestionStatus.PROMOTED
            db.commit()

        return {"stored": stored, "rejected": rejected, "failed": failed}

    @router.post(
        "/{run_id}/cancel",
        response_model=DiscoveryRun,
        dependencies=[Depends(require("ingestion", "write"))],
    )
    def cancel(run_id: uuid.UUID, db: DbSession) -> dict:
        """Ask a running discovery to stop at its next checkpoint.

        Cooperative rather than forced: the loop notices between segments and between
        pages, so the candidates already found stay reviewable.
        """
        batch = get_run(db, run_id)
        if batch.status in RUNNING_STATUSES:
            discovery.request_cancel(db, batch)
            db.refresh(batch)
        return run_out(db, batch)

    @router.post(
        "/{run_id}/reject-all",
        response_model=DiscoverySelectResponse,
        dependencies=[Depends(require("vendor", "write"))],
    )
    def reject_all(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> dict:
        """Discard every undecided candidate in a run."""
        batch = get_run(db, run_id)
        rejected: list[uuid.UUID] = []
        for entity in db.scalars(discovery.candidate_query(kind, batch.id)).all():
            if entity.review_decision != ReviewDecision.PENDING or entity.promoted_at:
                continue
            discovery.reject_candidate(db, entity, principal=principal)
            rejected.append(entity.id)
        batch.needs_review_items = 0
        db.commit()
        return {"stored": [], "rejected": rejected, "failed": {}}

    return router


def _run_for_kind(kind: DiscoveryKind):
    """Bind the kind for the in-process fallback, which passes only ids."""

    def run(db, *, batch_id, user_id):
        return discovery.run_discovery(db, kind, batch_id, user_id)

    return run


# ------------------------------------------------------------------- the two routers


def _vendor_existing(db, tenant_id, subjects) -> list[tuple[uuid.UUID, str] | None]:
    """Which vendors these candidates would merge into, one result per subject."""
    names = [subject.get("vendor_name") or "" for subject in subjects]
    found = vendor_discovery.existing_vendors_for(db, tenant_id, names)
    resolved: list[tuple[uuid.UUID, str] | None] = []
    for name in names:
        vendor = found.get(promotion.normalize_company_name(name)) if name else None
        resolved.append((vendor.id, vendor.name) if vendor else None)
    return resolved


def _pump_existing(db, tenant_id, subjects) -> list[tuple[uuid.UUID, str] | None]:
    """Which pump models these candidates would enrich, one result per subject."""
    pairs = [(subject.get("vendor_name"), subject.get("model_code")) for subject in subjects]
    found = pump_discovery.existing_models_for(db, tenant_id, pairs)
    resolved: list[tuple[uuid.UUID, str] | None] = []
    for vendor_name, model_code in pairs:
        model = None
        if vendor_name and model_code:
            model = found.get(
                (
                    promotion.normalize_company_name(vendor_name),
                    promotion.normalize_model_code(model_code),
                )
            )
        resolved.append((model.id, model.model_code) if model else None)
    return resolved


def _reindex_vendor(db, report) -> None:
    indexing.reindex_vendor(db, uuid.UUID(report["vendor_id"]))


def _reindex_pump(db, report) -> None:
    indexing.reindex_pump_model(db, uuid.UUID(report["pump_model_id"]))


vendor_router = build_router(
    vendor_discovery.KIND,
    display_fields=VENDOR_DISPLAY_FIELDS,
    store_candidate=vendor_discovery.store_candidate,
    existing_map=_vendor_existing,
    blocked_reason=vendor_discovery.blocked_reason,
    reindex=_reindex_vendor,
    audit_entity_type="vendors",
)

pump_router = build_router(
    pump_discovery.KIND,
    display_fields=PUMP_DISPLAY_FIELDS,
    store_candidate=pump_discovery.store_candidate,
    existing_map=_pump_existing,
    blocked_reason=pump_discovery.blocked_reason,
    spec_groups=PUMP_SPEC_GROUPS,
    reindex=_reindex_pump,
    audit_entity_type="pump_models",
)

ROUTERS = {"vendor": vendor_router, "pump": pump_router}
