"""Background tasks.

Each task opens its own tenant-scoped session (``tenant_session``) so row level
security applies to workers exactly as it does to API requests. Nothing here trusts a
caller-supplied tenant id beyond binding the session to it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.core.db import tenant_session
from app.models.enums import AiJobStatus, IngestionStatus, SourceType
from app.models.source import CrawlSchedule, ImportBatch, Source
from app.services import extraction, indexing, ingestion, promotion
from app.workers.celery_app import celery_app

log = get_task_logger(__name__)


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


@celery_app.task(name="pumpatlas.ingest_url", bind=True, max_retries=3, default_retry_delay=60)
def ingest_url_task(
    self,
    url: str,
    tenant_id: str | None,
    batch_id: str | None = None,
    vendor_hint: str | None = None,
    user_id: str | None = None,
    auto_extract: bool = True,
    auto_promote: bool = False,
    follow_document_links: bool = False,
) -> dict:
    """Fetch one URL, register it as a source, then optionally extract."""
    with tenant_session(_uuid(tenant_id)) as db:
        batch = db.get(ImportBatch, _uuid(batch_id)) if batch_id else None
        if batch and batch.status == IngestionStatus.QUEUED:
            batch.status = IngestionStatus.FETCHING
            batch.started_at = batch.started_at or datetime.now(UTC)

        try:
            source = ingestion.register_url(
                db,
                tenant_id=_uuid(tenant_id),
                url=url,
                vendor_hint=vendor_hint,
                batch=batch,
                user_id=_uuid(user_id),
            )
        except ingestion.IngestionError as exc:
            if batch:
                batch.failed_items += 1
                batch.error_summary = str(exc)[:2000]
            log.warning("ingest_url.failed url=%s error=%s", url, exc)
            return {"url": url, "status": "failed", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - network flakiness is worth retrying
            if batch:
                batch.failed_items += 1
            log.warning("ingest_url.error url=%s error=%s", url, exc)
            raise self.retry(exc=exc) from exc

        if batch:
            batch.processed_items += 1

        source_id = str(source.id)
        followed: list[str] = []
        if follow_document_links:
            followed = ingestion.extract_document_links(source)

    # Queue follow-up work outside the transaction so a slow AI call cannot hold locks.
    if follow_document_links:
        for link in followed:
            ingest_url_task.delay(
                link, tenant_id, batch_id, vendor_hint, user_id, auto_extract, auto_promote, False
            )
    if auto_extract:
        extract_source_task.delay(source_id, tenant_id, batch_id, user_id, auto_promote)

    return {
        "url": url,
        "status": "ingested",
        "source_id": source_id,
        "document_links_followed": len(followed),
    }


@celery_app.task(name="pumpatlas.extract_source", bind=True, max_retries=2, default_retry_delay=120)
def extract_source_task(
    self,
    source_id: str,
    tenant_id: str | None,
    batch_id: str | None = None,
    user_id: str | None = None,
    auto_promote: bool = False,
    groups: list[str] | None = None,
) -> dict:
    """Run Gemma extraction over a stored source and queue what it produced."""
    promoted_models: list[str] = []
    with tenant_session(_uuid(tenant_id)) as db:
        source = db.get(Source, uuid.UUID(source_id))
        if source is None:
            return {"source_id": source_id, "status": "missing"}
        if not source.parsed_text:
            source.status = IngestionStatus.NEEDS_REVIEW
            source.error_message = "No parsed text available for extraction"
            return {"source_id": source_id, "status": "no_text"}

        batch = db.get(ImportBatch, _uuid(batch_id)) if batch_id else None
        try:
            entities = extraction.extract_from_source(
                db,
                source,
                groups=groups,
                user_id=_uuid(user_id),
                import_batch_id=_uuid(batch_id),
                celery_task_id=self.request.id,
            )
        except Exception as exc:  # noqa: BLE001
            source.status = IngestionStatus.FAILED
            source.error_message = str(exc)[:2000]
            source.retry_count += 1
            log.warning("extract_source.error source=%s error=%s", source_id, exc)
            if source.retry_count <= 2:
                raise self.retry(exc=exc) from exc
            return {"source_id": source_id, "status": "failed", "error": str(exc)}

        # The batch may set its own bar; fall back to the platform default.
        threshold = float(
            (batch.config or {}).get("min_confidence_to_promote", extraction.AUTO_PROMOTE_THRESHOLD)
            if batch
            else extraction.AUTO_PROMOTE_THRESHOLD
        )
        needs_review = 0
        for entity in entities:
            confident = (
                entity.overall_confidence is not None
                and float(entity.overall_confidence) >= threshold
            )
            if auto_promote and confident:
                try:
                    report = promotion.promote_extracted_entity(db, entity, unattended=True)
                    promoted_models.append(report["pump_model_id"])
                except promotion.PromotionError as exc:
                    # A candidate that cannot be promoted is a review task, not an error.
                    entity.review_notes = f"Auto-promotion declined: {exc}"
                    needs_review += 1
            else:
                needs_review += 1

        if batch:
            batch.needs_review_items += needs_review
            batch.promoted_items += len(promoted_models)
            batch.status = (
                IngestionStatus.NEEDS_REVIEW if needs_review else IngestionStatus.PROMOTED
            )
            if batch.processed_items >= batch.total_items and batch.total_items:
                batch.finished_at = datetime.now(UTC)

        source.status = (
            IngestionStatus.PROMOTED
            if promoted_models and not needs_review
            else IngestionStatus.EXTRACTED
            if entities
            else IngestionStatus.NEEDS_REVIEW
        )
        result = {
            "source_id": source_id,
            "status": "extracted",
            "candidates": len(entities),
            "auto_promoted": len(promoted_models),
            "needs_review": needs_review,
        }

    for pump_model_id in set(promoted_models):
        reindex_pump_model_task.delay(pump_model_id, tenant_id)
        ai_quality_check_task.delay(pump_model_id, tenant_id, user_id)

    return result


@celery_app.task(name="pumpatlas.web_search", bind=True, max_retries=2, default_retry_delay=90)
def web_search_task(self, batch_id: str, tenant_id: str | None, user_id: str | None = None) -> dict:
    """Run a Parallel AI search, store each hit as a source, then queue extraction."""
    from app.ai.parallel_search import ParallelSearchClient, SearchUnavailableError
    from app.models.enums import AiJobType

    fetch_urls: list[str] = []
    source_ids: list[str] = []

    with tenant_session(_uuid(tenant_id)) as db:
        batch = db.get(ImportBatch, uuid.UUID(batch_id))
        if batch is None:
            return {"batch_id": batch_id, "status": "missing"}

        config = batch.config or {}
        batch.status = IngestionStatus.FETCHING
        batch.started_at = datetime.now(UTC)

        job = extraction.start_job(
            db,
            tenant_id=_uuid(tenant_id),
            job_type=AiJobType.WEB_SEARCH,
            import_batch_id=batch.id,
            prompt_name="parallel_search",
            provider="parallel",
            request_payload=config,
            user_id=_uuid(user_id),
            celery_task_id=self.request.id,
        )

        try:
            run = ParallelSearchClient().search(
                config.get("objective", ""),
                config.get("queries") or None,
                max_results=config.get("max_results", 10),
                include_domains=config.get("include_domains") or None,
                exclude_domains=config.get("exclude_domains") or None,
            )
        except SearchUnavailableError as exc:
            extraction.finish_job(db, job, status=AiJobStatus.FAILED, error=str(exc))
            batch.status = IngestionStatus.FAILED
            batch.error_summary = str(exc)[:2000]
            log.warning("web_search.failed batch=%s error=%s", batch_id, exc)
            return {"batch_id": batch_id, "status": "failed", "error": str(exc)}

        job.status = AiJobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        job.latency_ms = run.latency_ms
        job.response_payload = {
            "search_id": run.search_id,
            "result_count": len(run.results),
            "urls": [r.url for r in run.results],
        }

        batch.total_items = len(run.results)
        for result in run.results:
            source = ingestion.register_search_result(
                db,
                tenant_id=_uuid(tenant_id),
                url=result.url,
                title=result.title,
                excerpt=result.combined_excerpt,
                search_id=run.search_id,
                rank=result.rank,
                batch=batch,
                user_id=_uuid(user_id),
            )
            batch.processed_items += 1
            source_ids.append(str(source.id))
            if config.get("fetch_full_pages", True):
                fetch_urls.append(result.url)

        batch.status = IngestionStatus.PARSED
        summary = {
            "batch_id": batch_id,
            "status": "searched",
            "results": len(source_ids),
            "search_id": run.search_id,
        }

    # A search excerpt is often 100-200 characters, which is not enough to extract a
    # specification from, so fetching the page is the default path.
    auto_promote = bool(config.get("auto_promote", False))
    for url in fetch_urls:
        ingest_url_task.delay(url, tenant_id, batch_id, None, user_id, True, auto_promote, False)
    if not fetch_urls and config.get("auto_extract", True):
        for source_id in source_ids:
            extract_source_task.delay(source_id, tenant_id, batch_id, user_id, auto_promote)

    summary["auto_promote"] = auto_promote
    return summary


@celery_app.task(name="pumpatlas.enrich_pump_model")
def enrich_pump_model_task(
    pump_model_id: str,
    tenant_id: str | None,
    tasks: list[str] | None = None,
    run_web_search: bool = False,
    user_id: str | None = None,
) -> dict:
    """AI-assisted enrichment: find gaps, propose values, flag contradictions.

    Suggestions are written to ``ai_suggestions`` for human approval. Nothing is
    applied to the system of record here.
    """
    import json

    from app.ai import prompts
    from app.ai.openrouter import AiResponseError, AiUnavailableError, OpenRouterClient
    from app.models.ai import AiSuggestion
    from app.models.enums import AiJobType, ConfidenceLevel
    from app.services import quality, records

    requested = set(tasks or ["detect_missing_fields", "quality_check"])
    outcome: dict[str, object] = {"pump_model_id": pump_model_id, "tasks": sorted(requested)}
    search_hints: list[str] = []

    with tenant_session(_uuid(tenant_id)) as db:
        record = records.flatten_pump_model(db, uuid.UUID(pump_model_id))
        if not record:
            return {"pump_model_id": pump_model_id, "status": "missing"}

        if "quality_check" in requested:
            findings = quality.validate_record("pump_models", record)
            quality.persist_findings(
                db,
                tenant_id=_uuid(tenant_id),
                entity_type="pump_models",
                entity_id=uuid.UUID(pump_model_id),
                findings=findings,
            )
            outcome["validator_flags"] = len(findings)

        client = OpenRouterClient()
        if "detect_missing_fields" in requested and client.configured:
            from app.schemas.specs import ALL_TRACKED_FIELDS

            present = {k: v for k, v in record.items() if v not in (None, "", [], {})}
            missing = [f for f in ALL_TRACKED_FIELDS if f not in present]
            job = extraction.start_job(
                db,
                tenant_id=_uuid(tenant_id),
                job_type=AiJobType.DETECT_MISSING_FIELDS,
                subject_type="pump_models",
                subject_id=uuid.UUID(pump_model_id),
                prompt_name="detect_missing_fields",
                request_payload={"present": len(present), "missing": len(missing)},
                model=client.model,
                user_id=_uuid(user_id),
            )
            payload = json.dumps(
                {
                    "record": records.to_jsonable(present),
                    "absent_fields": missing[:250],
                },
                indent=2,
                default=str,
            )
            try:
                result = client.complete(prompts.SYSTEM_MISSING_FIELDS, payload)
            except (AiUnavailableError, AiResponseError) as exc:
                extraction.finish_job(db, job, status=AiJobStatus.FAILED, error=str(exc))
                outcome["missing_field_analysis"] = f"unavailable: {exc}"
            else:
                extraction.finish_job(db, job, result=result)
                entries = (result.data or {}).get("missing") or []
                created = 0
                for entry in entries[:25]:
                    if not isinstance(entry, dict) or not entry.get("field_name"):
                        continue
                    db.add(
                        AiSuggestion(
                            tenant_id=_uuid(tenant_id),
                            entity_type="pump_models",
                            entity_id=uuid.UUID(pump_model_id),
                            field_name=str(entry["field_name"])[:120],
                            suggestion_kind="fill_missing",
                            current_value=None,
                            suggested_value=None,
                            suggested_value_json={
                                "importance": entry.get("importance"),
                                "likely_source": entry.get("likely_source"),
                            },
                            rationale=entry.get("why"),
                            confidence_level=ConfidenceLevel.AI_EXTRACTED,
                            ai_job_id=job.id,
                        )
                    )
                    created += 1
                    if entry.get("importance") in {"critical", "high"}:
                        search_hints.append(str(entry["field_name"]))
                outcome["missing_field_suggestions"] = created

        if "summarize_vendor" in requested and record.get("vendor_id"):
            summarise_vendor_task.delay(record["vendor_id"], tenant_id, user_id)

    if run_web_search and search_hints:
        # Chase the important gaps on the open web rather than guessing at them.
        with tenant_session(_uuid(tenant_id)) as db:
            record = records.flatten_pump_model(db, uuid.UUID(pump_model_id))
            batch = ingestion.create_batch(
                db,
                tenant_id=_uuid(tenant_id),
                name=f"Gap-filling search: {record.get('vendor_name')} {record.get('model_code')}",
                import_mode="web_search",
                source_type=SourceType.PARALLEL_SEARCH,
                created_by_user_id=_uuid(user_id),
                config={
                    "objective": (
                        f"Find these missing specifications for the "
                        f"{record.get('vendor_name')} {record.get('model_code')} pump: "
                        f"{', '.join(search_hints[:12])}"
                    ),
                    "queries": [
                        f"{record.get('vendor_name')} {record.get('model_code')} datasheet",
                        f"{record.get('vendor_name')} {record.get('model_code')} "
                        f"{search_hints[0].replace('_', ' ')}",
                    ],
                    "max_results": 8,
                    "fetch_full_pages": True,
                    "auto_extract": True,
                },
            )
            batch_id = str(batch.id)
        web_search_task.delay(batch_id, tenant_id, user_id)
        outcome["gap_filling_batch_id"] = batch_id

    return outcome


@celery_app.task(name="pumpatlas.ai_quality_check")
def ai_quality_check_task(
    pump_model_id: str, tenant_id: str | None, user_id: str | None = None
) -> dict:
    """Gemma reviews a promoted record for the problems a range check cannot see."""
    from app.services import quality, records

    with tenant_session(_uuid(tenant_id)) as db:
        record = records.flatten_pump_model(db, uuid.UUID(pump_model_id))
        if not record:
            return {"pump_model_id": pump_model_id, "status": "missing"}
        flags = quality.run_ai_quality_check(
            db,
            tenant_id=_uuid(tenant_id),
            entity_type="pump_models",
            entity_id=uuid.UUID(pump_model_id),
            record=records.to_jsonable(record),
            user_id=_uuid(user_id),
        )
        return {"pump_model_id": pump_model_id, "ai_flags": len(flags)}


@celery_app.task(name="pumpatlas.summarise_vendor")
def summarise_vendor_task(
    vendor_id: str, tenant_id: str | None, user_id: str | None = None
) -> dict:
    """Regenerate the vendor briefing from facts already held in the database."""
    from app.models.vendor import Vendor
    from app.services import records

    with tenant_session(_uuid(tenant_id)) as db:
        vendor = db.get(Vendor, uuid.UUID(vendor_id))
        if vendor is None:
            return {"vendor_id": vendor_id, "status": "missing"}

        facts = records.to_jsonable(
            {
                "name": vendor.name,
                "country": vendor.country or vendor.hq_country,
                "vendor_tier": vendor.vendor_tier,
                "approval_status": vendor.approval_status,
                "sanctions_status": vendor.sanctions_status,
                "manufacturing_countries": vendor.manufacturing_countries,
                "product_families": vendor.product_families,
                "annual_revenue_usd": vendor.annual_revenue_usd,
                "employee_count": vendor.employee_count,
                "credit_rating": vendor.credit_rating,
                "bonding_capacity_usd": vendor.bonding_capacity_usd,
                "on_time_delivery_pct": vendor.on_time_delivery_pct,
                "total_units_supplied": vendor.total_units_supplied,
                "fpso_offshore_experience": vendor.fpso_offshore_experience,
                "approval_expiry": vendor.approval_expiry,
                "data_completeness_pct": vendor.data_completeness_pct,
            }
        )
        try:
            data, job = extraction.summarise_vendor(
                db,
                tenant_id=_uuid(tenant_id),
                vendor_id=vendor.id,
                facts=facts,
                user_id=_uuid(user_id),
            )
        except Exception as exc:  # noqa: BLE001 - provider failure must not lose the record
            log.warning("summarise_vendor.failed vendor=%s error=%s", vendor_id, exc)
            return {"vendor_id": vendor_id, "status": "failed", "error": str(exc)}

        summary = data.get("summary")
        if summary:
            vendor.ai_summary = summary
            vendor.ai_summary_generated_at = datetime.now(UTC)
        return {
            "vendor_id": vendor_id,
            "status": "summarised",
            "ai_job_id": str(job.id),
            "watch_items": data.get("watch_items", []),
            "missing_critical_data": data.get("missing_critical_data", []),
        }


@celery_app.task(name="pumpatlas.reindex_pump_model")
def reindex_pump_model_task(pump_model_id: str, tenant_id: str | None) -> dict:
    with tenant_session(_uuid(tenant_id)) as db:
        row = indexing.reindex_pump_model(db, uuid.UUID(pump_model_id))
        return {"pump_model_id": pump_model_id, "indexed": row is not None}


@celery_app.task(name="pumpatlas.recompute_scores")
def recompute_scores_task(pump_model_ids: list[str], tenant_id: str | None) -> dict:
    from app.services import comparison

    with tenant_session(_uuid(tenant_id)) as db:
        count = comparison.recompute_scores(db, [uuid.UUID(i) for i in pump_model_ids])
        return {"scored": count}


@celery_app.task(name="pumpatlas.run_crawl_schedule")
def run_crawl_schedule_task(schedule_id: str, user_id: str | None = None) -> dict:
    """Execute one scheduled crawl target."""
    urls: list[str] = []
    batch_id: str | None = None
    tenant_id: str | None = None
    parallel_query: str | None = None

    with tenant_session(None, is_platform_admin=True) as db:
        schedule = db.get(CrawlSchedule, uuid.UUID(schedule_id))
        if schedule is None or not schedule.is_active:
            return {"schedule_id": schedule_id, "status": "inactive_or_missing"}

        tenant_id = str(schedule.tenant_id) if schedule.tenant_id else None
        schedule.last_run_at = datetime.now(UTC)
        schedule.last_run_status = "running"

        batch = ingestion.create_batch(
            db,
            tenant_id=schedule.tenant_id,
            name=f"Scheduled crawl: {schedule.name}",
            import_mode="scheduled_crawl",
            source_type=SourceType.WEB_PAGE,
            created_by_user_id=schedule.created_by_user_id or _uuid(user_id),
            config={
                "schedule_id": schedule_id,
                "target_type": schedule.target_type,
                "max_pages": schedule.max_pages,
                "max_depth": schedule.max_depth,
            },
        )
        batch_id = str(batch.id)

        if schedule.target_type == "parallel_query":
            parallel_query = schedule.target
            batch.import_mode = "web_search"
            batch.source_type = SourceType.PARALLEL_SEARCH
            batch.config = {
                **batch.config,
                "objective": schedule.target,
                "max_results": min(schedule.max_pages, 25),
                "fetch_full_pages": True,
                "auto_extract": schedule.auto_extract,
            }
        elif schedule.target_type == "sitemap":
            urls = _urls_from_sitemap(schedule.target, schedule.max_pages)
            batch.total_items = len(urls)
        else:
            urls = [schedule.target]
            batch.total_items = 1

        schedule.last_run_status = "dispatched"

    if parallel_query:
        web_search_task.delay(batch_id, tenant_id, user_id)
        return {"schedule_id": schedule_id, "status": "search_dispatched", "batch_id": batch_id}

    for url in urls:
        ingest_url_task.delay(url, tenant_id, batch_id, None, user_id, True, False, False)
    return {
        "schedule_id": schedule_id,
        "status": "dispatched",
        "batch_id": batch_id,
        "urls": len(urls),
    }


def _urls_from_sitemap(sitemap_url: str, limit: int) -> list[str]:
    """Pull page URLs out of a sitemap, preferring anything that looks like a datasheet."""
    import httpx
    from bs4 import BeautifulSoup

    from app.core.config import settings

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(sitemap_url, headers={"User-Agent": settings.CRAWL_USER_AGENT})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("sitemap.fetch_failed url=%s error=%s", sitemap_url, exc)
        return []

    soup = BeautifulSoup(response.text, "xml")
    found = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
    interesting = [
        url
        for url in found
        if any(
            token in url.lower()
            for token in ("pump", "product", "datasheet", "download", "catalog", "api-610")
        )
    ]
    return (interesting or found)[:limit]


@celery_app.task(name="pumpatlas.dispatch_due_crawls")
def dispatch_due_crawls() -> dict:
    """Beat task: fire any schedule whose next run has come due."""
    now = datetime.now(UTC)
    dispatched: list[str] = []
    with tenant_session(None, is_platform_admin=True) as db:
        due = db.scalars(
            select(CrawlSchedule).where(
                CrawlSchedule.is_active.is_(True),
                (CrawlSchedule.next_run_at.is_(None)) | (CrawlSchedule.next_run_at <= now),
            )
        ).all()
        for schedule in due:
            schedule.next_run_at = _next_run(schedule.cron_expression, now)
            dispatched.append(str(schedule.id))

    for schedule_id in dispatched:
        run_crawl_schedule_task.delay(schedule_id)
    return {"dispatched": len(dispatched), "schedule_ids": dispatched}


def _next_run(cron_expression: str, after: datetime) -> datetime:
    """Approximate next-run time.

    Beat fires this dispatcher every 15 minutes, so a coarse estimate is enough: the
    goal is only to stop a schedule firing twice in the same window. A full cron parser
    (croniter) can replace this without touching callers.
    """
    from datetime import timedelta

    fields = cron_expression.split()
    if len(fields) == 5 and fields[2] == "*" and fields[4] != "*":
        return after + timedelta(days=7)
    if len(fields) == 5 and fields[2] != "*":
        return after + timedelta(days=30)
    return after + timedelta(days=1)


@celery_app.task(name="pumpatlas.nightly_maintenance")
def nightly_maintenance() -> dict:
    """Rebuild stale index rows and rescore anything marked stale."""
    from app.models.ai import ConfidenceScore
    from app.models.pump import PumpModel
    from app.models.tenant import Tenant
    from app.services import comparison

    reindexed = 0
    rescored = 0
    with tenant_session(None, is_platform_admin=True) as db:
        tenant_ids = db.scalars(select(Tenant.id).where(Tenant.deleted_at.is_(None))).all()

    for tenant_id in tenant_ids:
        with tenant_session(tenant_id) as db:
            reindexed += indexing.reindex_all(db, tenant_id)
            stale = db.scalars(
                select(ConfidenceScore.entity_id)
                .where(
                    ConfidenceScore.is_stale.is_(True),
                    ConfidenceScore.entity_type == "pump_models",
                )
                .distinct()
                .limit(500)
            ).all()
            rescored += comparison.recompute_scores(db, list(stale))

    # Shared master data lives outside any tenant, so it needs its own pass.
    with tenant_session(None, is_platform_admin=True) as db:
        shared = db.scalars(
            select(PumpModel.id).where(
                PumpModel.tenant_id.is_(None), PumpModel.deleted_at.is_(None)
            )
        ).all()
        for pump_model_id in shared:
            indexing.reindex_pump_model(db, pump_model_id)
        reindexed += len(shared)

    log.info("nightly_maintenance reindexed=%s rescored=%s", reindexed, rescored)
    return {"reindexed": reindexed, "rescored": rescored, "tenants": len(tenant_ids)}


@celery_app.task(name="pumpatlas.discovery", bind=True, max_retries=1)
def discovery_task(
    self, kind_slug: str, batch_id: str, tenant_id: str | None, user_id: str | None = None
) -> dict:
    """Run one AI discovery: Parallel AI search, then Gemma screening per page.

    The orchestration lives in the service so the same code runs here and in the
    in-process fallback used when no broker is configured. The kind arrives as a slug
    because a Celery argument has to survive JSON.
    """
    from app.services import discovery, pump_discovery, vendor_discovery

    kinds = {
        vendor_discovery.KIND.slug: vendor_discovery.KIND,
        pump_discovery.KIND.slug: pump_discovery.KIND,
    }
    kind = kinds.get(kind_slug)
    if kind is None:
        return {"batch_id": batch_id, "status": "unknown_kind", "kind": kind_slug}

    with tenant_session(_uuid(tenant_id)) as db:
        return discovery.run_discovery(db, kind, uuid.UUID(batch_id), _uuid(user_id))
