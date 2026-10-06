"""Ingestion endpoints: uploads, URLs, web search, manual forms, batches, sources."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import ExtractedEntity
from app.models.enums import AuditAction, ConfidenceLevel, DocumentKind, IngestionStatus, SourceType
from app.models.source import CrawlSchedule, Document, ImportBatch, Source
from app.schemas.common import Message, Page
from app.schemas.ingest import (
    CrawlScheduleIn,
    DocumentOut,
    ImportBatchOut,
    ManualSubmissionRequest,
    SourceDetail,
    SourceOut,
    UrlIngestRequest,
    WebSearchIngestRequest,
)
from app.services import audit, ingestion
from app.services.storage import get_storage

router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
async def upload_files(
    principal: CurrentPrincipal,
    db: DbSession,
    files: list[UploadFile] = File(description="PDF, DOCX, XLSX, CSV or HTML"),
    vendor_hint: str | None = Form(default=None),
    vendor_id: uuid.UUID | None = Form(default=None),
    pump_model_id: uuid.UUID | None = Form(default=None),
    document_kind: str | None = Form(default=None),
    confidence_level: str = Form(default=ConfidenceLevel.VENDOR_DECLARED.value),
    auto_extract: bool = Form(default=True),
    auto_promote: bool = Form(default=False),
    batch_name: str | None = Form(default=None),
) -> dict:
    """Batch upload. Each file becomes a source + document, then queues extraction."""
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files supplied")

    tenant_id = principal.require_tenant_id
    batch = ingestion.create_batch(
        db,
        tenant_id=tenant_id,
        name=batch_name or f"Upload of {len(files)} file(s)",
        import_mode="file_upload",
        source_type=SourceType.DOCUMENT,
        total_items=len(files),
        auto_promote=auto_promote,
        created_by_user_id=principal.user_id,
        config={"auto_extract": auto_extract, "vendor_hint": vendor_hint},
    )

    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for upload in files:
        data = await upload.read()
        try:
            source, document = ingestion.register_upload(
                db,
                tenant_id=tenant_id,
                filename=upload.filename or "upload.bin",
                data=data,
                mime_type=upload.content_type,
                vendor_hint=vendor_hint,
                vendor_id=vendor_id,
                pump_model_id=pump_model_id,
                document_kind=DocumentKind(document_kind) if document_kind else None,
                batch=batch,
                user_id=principal.user_id,
                confidence_level=ConfidenceLevel(confidence_level),
            )
        except (ingestion.IngestionError, ValueError) as exc:
            batch.failed_items += 1
            failures.append({"filename": upload.filename or "?", "error": str(exc)})
            continue

        batch.processed_items += 1
        accepted.append(
            {
                "source_id": str(source.id),
                "document_id": str(document.id),
                "filename": document.filename,
                "parsed_chars": source.parsed_text_chars,
                "document_kind": document.document_kind.value,
            }
        )

    batch.status = IngestionStatus.FAILED if not accepted else IngestionStatus.PARSED
    audit.record_audit(
        db,
        action=AuditAction.IMPORT,
        principal=principal,
        entity_type="import_batches",
        entity_id=batch.id,
        entity_label=batch.name,
        summary=f"{len(accepted)} file(s) ingested, {len(failures)} failed",
        context={"failures": failures},
    )
    db.commit()

    queued: list[str] = []
    if auto_extract and accepted:
        from app.workers.tasks import extract_source_task

        for item in accepted:
            task = extract_source_task.delay(
                item["source_id"],
                str(tenant_id),
                str(batch.id),
                str(principal.user_id) if principal.user_id else None,
                auto_promote,
            )
            queued.append(task.id)

    return {
        "batch_id": str(batch.id),
        "accepted": accepted,
        "failures": failures,
        "extraction_tasks": queued,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
    }


@router.post(
    "/urls",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def ingest_urls(payload: UrlIngestRequest, principal: CurrentPrincipal, db: DbSession) -> dict:
    """Queue a list of URLs for fetching, parsing and extraction."""
    tenant_id = principal.require_tenant_id
    batch = ingestion.create_batch(
        db,
        tenant_id=tenant_id,
        name=payload.batch_name or f"URL import of {len(payload.urls)} page(s)",
        import_mode="url_list",
        source_type=SourceType.WEB_PAGE,
        total_items=len(payload.urls),
        auto_promote=payload.auto_promote,
        created_by_user_id=principal.user_id,
        config={
            "auto_extract": payload.auto_extract,
            "follow_document_links": payload.follow_document_links,
            "vendor_hint": payload.vendor_hint,
        },
    )
    audit.record_audit(
        db,
        action=AuditAction.IMPORT,
        principal=principal,
        entity_type="import_batches",
        entity_id=batch.id,
        entity_label=batch.name,
        summary=f"{len(payload.urls)} URL(s) queued for ingestion",
    )
    db.commit()

    from app.workers.tasks import ingest_url_task

    tasks = [
        ingest_url_task.delay(
            str(url),
            str(tenant_id),
            str(batch.id),
            payload.vendor_hint,
            str(principal.user_id) if principal.user_id else None,
            payload.auto_extract,
            payload.auto_promote,
            payload.follow_document_links,
        ).id
        for url in payload.urls
    ]
    return {"batch_id": str(batch.id), "queued": len(tasks), "task_ids": tasks}


@router.post(
    "/web-search",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def ingest_from_web_search(
    payload: WebSearchIngestRequest, principal: CurrentPrincipal, db: DbSession
) -> dict:
    """Discover sources with Parallel AI, then ingest what it returns.

    Every hit is written to ``sources`` before extraction, so a discovery run can be
    audited and replayed exactly as it happened.
    """
    from app.ai import parallel_search

    if not parallel_search.get_parallel_client().configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Parallel AI is not configured. Set PARALLEL_API_KEY to enable web discovery.",
        )

    objective = payload.objective
    queries = list(payload.queries)
    if not objective:
        if payload.recipe == "vendor_intelligence" and payload.vendor_name:
            objective, recipe_queries = parallel_search.vendor_intelligence_objective(
                payload.vendor_name
            )
        elif payload.recipe == "pump_model" and payload.vendor_name and payload.model_code:
            objective, recipe_queries = parallel_search.pump_model_objective(
                payload.vendor_name, payload.model_code
            )
        elif payload.pump_type:
            objective, recipe_queries = parallel_search.vendor_discovery_objective(
                payload.pump_type, payload.country
            )
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Supply an objective, or a recipe with the fields it needs: pump_type for "
                "discovery, vendor_name for intelligence, vendor_name + model_code "
                "for a specific model.",
            )
        queries = queries or recipe_queries

    tenant_id = principal.require_tenant_id
    batch = ingestion.create_batch(
        db,
        tenant_id=tenant_id,
        name=f"Web search: {objective[:120]}",
        import_mode="web_search",
        source_type=SourceType.PARALLEL_SEARCH,
        auto_promote=payload.auto_promote,
        created_by_user_id=principal.user_id,
        config={
            "objective": objective,
            "queries": queries,
            "max_results": payload.max_results,
            "fetch_full_pages": payload.fetch_full_pages,
            "auto_extract": payload.auto_extract,
            "auto_promote": payload.auto_promote,
            "min_confidence_to_promote": payload.min_confidence_to_promote,
            "include_domains": payload.include_domains,
            "exclude_domains": payload.exclude_domains,
        },
    )
    db.commit()

    from app.workers.tasks import web_search_task

    task = web_search_task.delay(
        str(batch.id),
        str(tenant_id),
        str(principal.user_id) if principal.user_id else None,
    )
    return {
        "batch_id": str(batch.id),
        "task_id": task.id,
        "objective": objective,
        "queries": queries,
        "auto_promote": payload.auto_promote,
        "min_confidence_to_promote": payload.min_confidence_to_promote,
        "detail": (
            "Discovery dispatched. Results land in `sources`, then extraction runs; "
            + (
                "high-confidence records are written straight to the database."
                if payload.auto_promote
                else "candidates queue for review at /ai/review-queue."
            )
        ),
    }


@router.post(
    "/manual",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def manual_submission(
    payload: ManualSubmissionRequest, principal: CurrentPrincipal, db: DbSession
) -> dict:
    """Manual data entry, recorded as a source and promoted straight through.

    Human-entered data skips AI review but still gets provenance rows, so it stays as
    traceable as anything the crawler found.
    """
    from app.models.enums import ValueOrigin
    from app.services import comparison, indexing, promotion, provenance, quality, records

    tenant_id = principal.require_tenant_id
    source = ingestion.register_manual_submission(
        db,
        tenant_id=tenant_id,
        title=f"Manual entry: {payload.vendor_name} {payload.model_code or ''}".strip(),
        payload=payload.model_dump(exclude_none=True),
        user_id=principal.user_id,
        submitted_by_organisation=payload.submitted_by_organisation,
        confidence_level=ConfidenceLevel(payload.confidence_level),
    )

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL,
        confidence_level=ConfidenceLevel(payload.confidence_level),
        source_id=source.id,
        changed_by_user_id=principal.user_id,
        tenant_id=tenant_id,
    )
    vendor = promotion.resolve_vendor(
        db,
        tenant_id=tenant_id,
        name=payload.vendor_name,
        country=payload.vendor_country,
        context=context,
    )
    pump = promotion.resolve_pump(
        db,
        tenant_id=tenant_id,
        vendor=vendor,
        name=payload.pump_name,
        fields={"model_code": payload.model_code},
        context=context,
    )
    if payload.pump_type:
        pump.pump_type = payload.pump_type
    if payload.applicable_standard:
        pump.applicable_standard = payload.applicable_standard
    if payload.service_application:
        pump.service_application = payload.service_application

    model = promotion.resolve_pump_model(
        db, tenant_id=tenant_id, pump=pump, model_code=payload.model_code, context=context
    )

    written: dict[str, Any] = {}
    for group in records.SPEC_CLASSES:
        values = getattr(payload, group, None)
        if not values:
            continue
        spec = promotion.open_spec_version(
            db,
            records.SPEC_CLASSES[group],
            tenant_id=tenant_id,
            pump_model=model,
            context=context,
        )
        written[group] = provenance.apply_fields(db, spec, values, context)

    flat = records.flatten_pump_model(db, model.id)
    findings = quality.validate_record("pump_models", flat)
    quality.persist_findings(
        db,
        tenant_id=tenant_id,
        entity_type="pump_models",
        entity_id=model.id,
        findings=findings,
    )
    source.status = IngestionStatus.PROMOTED
    indexing.reindex_pump_model(db, model.id)
    comparison.mark_scores_stale(db, model.id)

    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="pump_models",
        entity_id=model.id,
        entity_label=f"{vendor.name} {model.model_code}",
        summary="Manual submission promoted",
        changes=written,
        context={"source_id": str(source.id)},
    )
    db.commit()
    return {
        "source_id": str(source.id),
        "vendor_id": str(vendor.id),
        "pump_id": str(pump.id),
        "pump_model_id": str(model.id),
        "written": written,
        "quality_flags_raised": len(findings),
    }


@router.get(
    "/batches",
    response_model=Page[ImportBatchOut],
    dependencies=[Depends(require("ingestion", "read"))],
)
def list_batches(
    db: DbSession,
    status_filter: list[str] = Query(default_factory=list, alias="status"),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """The import queue screen."""
    stmt = select(ImportBatch)
    if status_filter:
        stmt = stmt.where(ImportBatch.status.in_(status_filter))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ImportBatch.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[ImportBatchOut](
        items=[
            ImportBatchOut.model_validate(row).model_copy(update={"progress_pct": row.progress_pct})
            for row in rows
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/batches/{batch_id}",
    response_model=ImportBatchOut,
    dependencies=[Depends(require("ingestion", "read"))],
)
def get_batch(batch_id: uuid.UUID, db: DbSession) -> ImportBatchOut:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import batch not found")
    return ImportBatchOut.model_validate(batch).model_copy(
        update={"progress_pct": batch.progress_pct}
    )


@router.get(
    "/sources", response_model=Page[SourceOut], dependencies=[Depends(require("ingestion", "read"))]
)
def list_sources(
    db: DbSession,
    batch_id: uuid.UUID | None = None,
    source_type: list[str] = Query(default_factory=list),
    status_filter: list[str] = Query(default_factory=list, alias="status"),
    q: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(Source).where(Source.deleted_at.is_(None))
    if batch_id:
        stmt = stmt.where(Source.import_batch_id == batch_id)
    if source_type:
        stmt = stmt.where(Source.source_type.in_(source_type))
    if status_filter:
        stmt = stmt.where(Source.status.in_(status_filter))
    if q:
        stmt = stmt.where(Source.title.ilike(f"%{q}%") | Source.source_url.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Source.captured_at.desc()).limit(limit).offset(offset)).all()
    return Page[SourceOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.get(
    "/sources/{source_id}",
    response_model=SourceDetail,
    dependencies=[Depends(require("ingestion", "read"))],
)
def get_source(
    source_id: uuid.UUID,
    db: DbSession,
    include_text: bool = Query(default=True, description="Include the parsed text"),
) -> SourceDetail:
    """Full source record, including the parsed text an extraction was run against."""
    source = db.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")

    entity_count = (
        db.scalar(
            select(func.count())
            .select_from(ExtractedEntity)
            .where(ExtractedEntity.source_id == source.id)
        )
        or 0
    )
    documents = db.scalars(select(Document).where(Document.source_id == source.id)).all()

    detail = SourceDetail.model_validate(source)
    detail.extracted_entity_count = int(entity_count)
    detail.documents = [
        {
            "id": str(doc.id),
            "filename": doc.filename,
            "document_kind": doc.document_kind.value,
            "size_bytes": doc.size_bytes,
        }
        for doc in documents
    ]
    if not include_text:
        detail.parsed_text = None
    return detail


@router.post(
    "/sources/{source_id}/extract",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def reextract_source(
    source_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    groups: list[str] = Query(default_factory=list, description="Field groups; all if omitted"),
) -> dict:
    """Re-run extraction on a stored source - useful after a prompt change."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if not source.parsed_text:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This source has no parsed text. Re-fetch it before extracting.",
        )

    from app.workers.tasks import extract_source_task

    task = extract_source_task.delay(
        str(source.id),
        str(source.tenant_id) if source.tenant_id else None,
        None,
        str(principal.user_id) if principal.user_id else None,
        False,
        groups or None,
    )
    return {"queued": True, "task_id": task.id, "source_id": str(source.id)}


@router.get(
    "/documents/{document_id}/download", dependencies=[Depends(require("document", "read"))]
)
def download_document(document_id: uuid.UUID, db: DbSession) -> dict:
    """Returns a short-lived presigned URL rather than streaming through the API."""
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "url": get_storage().presigned_url(document.storage_key),
        "expires_in_seconds": 900,
    }


@router.get(
    "/documents",
    response_model=Page[DocumentOut],
    dependencies=[Depends(require("document", "read"))],
)
def list_documents(
    db: DbSession,
    vendor_id: uuid.UUID | None = None,
    pump_model_id: uuid.UUID | None = None,
    document_kind: list[str] = Query(default_factory=list),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if vendor_id:
        stmt = stmt.where(Document.vendor_id == vendor_id)
    if pump_model_id:
        stmt = stmt.where(Document.pump_model_id == pump_model_id)
    if document_kind:
        stmt = stmt.where(Document.document_kind.in_(document_kind))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[DocumentOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.get("/schedules", dependencies=[Depends(require("ingestion", "read"))])
def list_schedules(db: DbSession) -> list[dict]:
    """Scheduled crawl targets."""
    rows = db.scalars(select(CrawlSchedule).order_by(CrawlSchedule.name)).all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "target_type": row.target_type,
            "target": row.target,
            "cron_expression": row.cron_expression,
            "max_depth": row.max_depth,
            "max_pages": row.max_pages,
            "auto_extract": row.auto_extract,
            "is_active": row.is_active,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "last_run_status": row.last_run_status,
            "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        }
        for row in rows
    ]


@router.post(
    "/schedules",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def create_schedule(payload: CrawlScheduleIn, principal: CurrentPrincipal, db: DbSession) -> dict:
    schedule = CrawlSchedule(
        tenant_id=principal.require_tenant_id,
        created_by_user_id=principal.user_id,
        **payload.model_dump(),
    )
    db.add(schedule)
    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="crawl_schedules",
        entity_label=payload.name,
        summary=f"Crawl schedule created ({payload.cron_expression})",
    )
    db.commit()
    db.refresh(schedule)
    return {"id": str(schedule.id), "name": schedule.name, "is_active": schedule.is_active}


@router.delete(
    "/schedules/{schedule_id}",
    response_model=Message,
    dependencies=[Depends(require("ingestion", "delete"))],
)
def delete_schedule(schedule_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Message:
    schedule = db.get(CrawlSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    db.delete(schedule)
    audit.record_audit(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        entity_type="crawl_schedules",
        entity_id=schedule_id,
        entity_label=schedule.name,
        summary="Crawl schedule deleted",
    )
    db.commit()
    return Message(detail="Schedule deleted")


@router.post(
    "/schedules/{schedule_id}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def run_schedule_now(schedule_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> dict:
    schedule = db.get(CrawlSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    from app.workers.tasks import run_crawl_schedule_task

    task = run_crawl_schedule_task.delay(
        str(schedule.id), str(principal.user_id) if principal.user_id else None
    )
    return {"queued": True, "task_id": task.id, "schedule_id": str(schedule.id)}
