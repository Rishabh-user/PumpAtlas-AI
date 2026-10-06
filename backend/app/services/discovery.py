"""AI web discovery: the engine both vendor and pump discovery run on.

Two providers, in sequence, with distinct jobs:

* **Parallel AI** orchestrates the web search and returns ranked pages with excerpts. It
  decides *where to look*.
* **Gemma** (via OpenRouter) reads each captured page and decides two things: whether the
  page is really about Oil & Gas pumps, and what the record's profile is. It decides
  *what the page says*.

Neither writes to the system of record. Every hit lands in ``sources`` first, every
profile lands in ``extracted_entities`` as a candidate, and a candidate only becomes a
real row when a person selects it — at which point every field is written through
``provenance.apply_fields`` so the value can be traced back to the page it came from.

The run itself is an ``import_batches`` row, so discovery reuses the same tenant
isolation, progress accounting and audit trail as every other ingestion path.

What differs between vendor and pump discovery is only: the Parallel objective, the
Gemma prompt, the key the model answers the relevance question with, and where a
selected candidate gets stored. That is what :class:`DiscoveryKind` carries; everything
else below is shared.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.ai import providers
from app.ai.openrouter import AiResponseError
from app.ai.parallel_search import SearchUnavailableError
from app.core.config import settings
from app.core.logging import get_logger
from app.models.ai import AiJob, ExtractedEntity
from app.models.enums import (
    AiJobStatus,
    AiJobType,
    ConfidenceLevel,
    IngestionStatus,
    ReviewDecision,
    SourceType,
)
from app.models.source import ImportBatch, Source
from app.services import ai_settings, extraction, ingestion, promotion

log = get_logger(__name__)

#: How each provider is named on screen. The stage detail and the job list both show it,
#: so a run says which AI did the work rather than naming whichever one it used to be.
_PROVIDER_LABELS = {
    "parallel": "Parallel AI",
    "openai": "OpenAI",
    "anthropic": "Claude",
    "openrouter": "Gemma",
}

#: A page shorter than this carries no profile worth a provider call.
MIN_PAGE_CHARS = 120


@dataclass(frozen=True)
class DiscoveryKind:
    """Everything that differs between discovering vendors and discovering pumps."""

    slug: str
    """``"vendor"`` or ``"pump"`` — used in log lines and the run's import mode."""

    entity_type: str
    """``extracted_entities.entity_type`` for candidates of this kind."""

    noun: str
    """Singular noun for progress text, e.g. "supplier" or "pump model"."""

    screen_label: str
    """Stage label for the Gemma pass."""

    run_name: str
    """Prefix for the run's display name."""

    build_objective: Callable[[str, str | None], tuple[str, list[str]]]
    """``(query, country) -> (objective, seed queries)`` for Parallel AI."""

    system_prompt: str
    """Gemma's system prompt: the screening decision plus the extraction contract."""

    build_user_prompt: Callable[..., str]
    """``(text, source_url=, source_title=) -> str``."""

    relevance_key: str
    """Boolean key in Gemma's JSON that answers "is this in scope?"."""

    subject_keys: tuple[str, ...]
    """Payload keys copied into ``payload["subject"]`` from the model's response."""

    sweep_segments: Callable[..., list[Any]]
    """The default sweep axis: ``(country_or_codes) -> [SweepSegment]``."""

    off_subject: Callable[[dict, dict], str | None] | None = None
    """``(subject, fields) -> reason`` for a page the model kept and should not have.

    The screening question is "is this page about a pump model?", and Gemma answers it
    from the page's own title. A manufacturer's category page - "API 610 VS6 Vertical
    Suspended Pumps" - is genuinely about pump models, so the honest answer is yes, and
    the candidate that comes back is designated "VS6": a configuration hundreds of
    manufacturers build, not a product anybody can quote for.

    A rule catches that where a prompt cannot. Pages ruled out here are recorded on the
    source with their reason, exactly as the ones Gemma rules out are, so they are
    counted as screened out rather than arriving in the review queue as candidates that
    can be looked at and never stored.
    """

    sweep_scopes: dict[str, Callable[..., list[Any]]] = field(default_factory=dict)
    """Every axis this kind can sweep along, by name.

    Vendors can sweep two ways and the difference matters. Sweeping pump types asks the
    same question 23 ways and gets the same global OEMs back; sweeping countries reaches
    the regional packagers and foundries that are the actual gap in the record. Pumps
    have only the one axis, because a pump model is identified by its duty, not its
    postcode.
    """

    @property
    def import_mode(self) -> str:
        return f"{self.slug}_discovery"

    def segments_for(
        self,
        scope: str | None = None,
        country: str | None = None,
        countries: Any = None,
    ) -> list[Any]:
        """Segments for one sweep axis, falling back to this kind's default axis.

        Every builder takes the same two arguments and ignores what it does not need, so
        this does not have to know which axis it selected.
        """
        builder = self.sweep_scopes.get(scope or "", self.sweep_segments)
        return builder(country, countries)


# ------------------------------------------------------------------ run bookkeeping


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stage(key: str, provider: str | None, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "provider": provider,
        "label": label,
        "status": "pending",
        "detail": None,
        "done": 0,
        "total": None,
        "started_at": None,
        "finished_at": None,
    }


def resolved_providers(db: Session) -> tuple[str, str]:
    """(search provider, reading provider) actually in force, as names.

    The activated configuration decides, and the environment is only the fallback for an
    installation that has not configured anything yet. Reading the environment directly
    is what made the run panel badge a Claude run as "Parallel AI" and "Gemma" - the
    names in `.env`, which by then were not what was running.
    """
    if not ai_settings.is_installed(db):
        return settings.SEARCH_PROVIDER, settings.EXTRACTION_PROVIDER
    search = ai_settings.active_config(db, "search")
    reading = ai_settings.active_config(db, "reading")
    return (
        search.provider if search is not None else settings.SEARCH_PROVIDER,
        reading.provider if reading is not None else settings.EXTRACTION_PROVIDER,
    )


def initial_stages(
    kind: DiscoveryKind,
    search_provider: str | None = None,
    reading_provider: str | None = None,
) -> list[dict[str, Any]]:
    """The stage list the UI renders. Order is the order they run in."""
    # The provider on each stage comes from configuration, not a constant. The panel
    # puts a badge on the stage naming who is doing the work, and it said "Parallel AI"
    # and "Gemma" whatever was actually configured - a run read by Claude claiming to
    # have been read by Gemma is worse than no badge, because the job list beside it
    # tells the truth and the two disagree.
    return [
        _stage("search", search_provider or settings.SEARCH_PROVIDER, "Web search"),
        _stage("capture", None, "Capture sources"),
        _stage(
            "screen",
            reading_provider or settings.EXTRACTION_PROVIDER,
            kind.screen_label,
        ),
    ]


def _write_config_key(db: Session, batch: ImportBatch, key: str, value: Any) -> None:
    """Update one key of ``config`` server-side, then expire the stale in-memory copy.

    This is the whole reason the column is written this way. ``config`` has two
    concurrent writers: the runner, pushing stage progress every few seconds, and the
    request handler, recording the transport or a cancellation. Whenever either assigned
    the whole dict, it silently erased the other's key — which made ``transport`` come
    back null (so a dead in-process run looked like a live Celery one) and made a
    cancellation vanish before the runner ever saw it.

    ``jsonb_set`` merges instead of replacing, and never touching the ORM attribute means
    there is no stale value for a later flush to write back.

    It also commits. Merging is only half the fix: under READ COMMITTED, once a
    transaction has updated a row, later statements in that same transaction see its own
    version rather than anything committed since. The runner's transaction spans several
    stage writes, so without committing each one its later merges were built on a
    snapshot from before the cancellation — which is why a cancel request vanished even
    though it wrote correctly. One short transaction per write keeps every merge based on
    the latest committed value.
    """
    db.execute(
        text(
            "UPDATE import_batches"
            " SET config = jsonb_set(config, CAST(:path AS text[]), CAST(:value AS jsonb), true)"
            " WHERE id = :batch_id"
        ),
        {
            "path": "{" + key + "}",
            "value": json.dumps(value),
            "batch_id": batch.id,
        },
    )
    db.commit()
    db.expire(batch, ["config"])


def _set_stage(  # noqa: PLR0913 - one keyword per field the UI shows
    db: Session,
    batch: ImportBatch,
    kind: DiscoveryKind,
    key: str,
    *,
    status: str | None = None,
    detail: str | None = None,
    done: int | None = None,
    total: int | None = None,
    provider: str | None = None,
) -> None:
    """Update one stage of the run's progress.

    Each change is a real UPDATE, which is what lets the polling endpoint show a sweep
    advancing through twenty-odd searches rather than jumping from queued to done.
    """
    stages = [dict(s) for s in (batch.config or {}).get("stages") or initial_stages(kind)]
    for stage in stages:
        if stage.get("key") != key:
            continue
        if status is not None:
            stage["status"] = status
            if status == "running" and not stage.get("started_at"):
                stage["started_at"] = _now()
            if status in {"done", "failed", "skipped"}:
                stage["finished_at"] = _now()
        if detail is not None:
            stage["detail"] = detail
        if done is not None:
            stage["done"] = done
        if total is not None:
            stage["total"] = total
        if provider is not None:
            # Corrected at execution time: the active configuration can change between
            # a run being queued and it starting, and the badge has to name whoever
            # actually ran rather than whoever was configured when it was queued.
            stage["provider"] = provider
    _write_config_key(db, batch, "stages", stages)


#: How each sweep axis is said, singular and plural. A pair rather than a rule, because
#: pluralising by slicing produced "every countrie" in the run name - which is the name
#: the panel, the run list and the audit entry all show.
AXIS_WORDS: dict[str, tuple[str, str]] = {
    "country": ("country", "countries"),
    "pump_type": ("pump type", "pump types"),
}


def axis_words(scope: str | None) -> tuple[str, str]:
    """The singular and plural for a sweep axis, defaulting to pump types."""
    return AXIS_WORDS.get(scope or "", AXIS_WORDS["pump_type"])


def plan_sweep(
    kind: DiscoveryKind,
    country: str | None,
    *,
    scope: str | None = None,
    countries: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Turn the vocabulary into one search segment per pump type.

    This is what "fetch everything" means in practice. There is no call that returns the
    whole web: Parallel AI, like every retrieval API, answers an objective. So instead of
    asking somebody to imagine every duty, the segments are generated from the controlled
    vocabulary the database already enforces — coverage becomes a property of the domain
    model rather than of anyone's memory.
    """
    planned: list[dict[str, Any]] = []
    for segment in kind.segments_for(scope, country, countries):
        # A country segment carries its own country; a pump-type segment inherits the
        # run's country bias, if there is one.
        objective, queries = kind.build_objective(
            segment.query, getattr(segment, "country", None) or country
        )
        planned.append(
            {
                "key": segment.key,
                "label": segment.label,
                "objective": objective,
                "queries": queries,
            }
        )
    return planned


#: Pages a caller may hand a run instead of searching for them.
#:
#: The chat needs this. It has already run a search to answer the question, and asking
#: the provider the same thing twice returns a different set of pages - which is how a
#: panel that said "read these pages" came to read eight others, half of them
#: educational guides about API 610 rather than product pages. Capped because each page
#: is one reading-model call, the same reason `max_results` is capped.
MAX_SEED_URLS = 12


def seed_url_list(urls: Any) -> list[str]:
    """Normalise the pages handed to a run: stripped, deduplicated in order, capped.

    Shared by `start_run` (which stores them) and `run_discovery` (which reads them back
    out of the run config), so the run cannot be told to read twelve pages and then read
    a different number of them.
    """
    out: list[str] = []
    for url in urls or []:
        if not isinstance(url, str):
            continue
        cleaned = url.strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
        if len(out) >= MAX_SEED_URLS:
            break
    return out


def start_run(
    db: Session,
    kind: DiscoveryKind,
    *,
    tenant_id: uuid.UUID | None,
    query: str | None,
    country: str | None,
    objective: str | None,
    max_results: int,
    user_id: uuid.UUID | None,
    sweep: bool = False,
    sweep_scope: str | None = None,
    countries: Sequence[str] | None = None,
    queries: Sequence[str] | None = None,
    target_vendor_id: uuid.UUID | None = None,
    target_pump_model_id: uuid.UUID | None = None,
    auto_store: bool = False,
    min_confidence: float = extraction.AUTO_PROMOTE_THRESHOLD,
    transport: str | None = None,
    urls: Sequence[str] | None = None,
) -> ImportBatch:
    """Create the run row. Nothing is called yet — the caller dispatches the work.

    ``transport`` is recorded here rather than after dispatch on purpose. Once the runner
    starts it owns ``config``: every stage update assigns the whole dict from its own
    copy, so a key written by the request afterwards is erased on the next progress
    write. That is how ``transport`` came back null and made a dead in-process run look
    like a live Celery one.
    """
    config: dict[str, Any] = {
        "country": (country or "").upper() or None,
        "max_results": max_results,
        "sweep": sweep,
        "auto_store": auto_store,
        "min_confidence": min_confidence,
        "transport": transport,
        "stages": initial_stages(kind, *resolved_providers(db)),
    }

    # Enrichment fills a record somebody opened, so the candidates belong to that record
    # whatever the page calls the company. Without this, enriching "Seal Care" from a
    # page that says "Seal Care (S) Pte Ltd." resolved by name, created a second vendor,
    # and left the page that asked for the update exactly as empty as before.
    if target_vendor_id is not None:
        config["target_vendor_id"] = str(target_vendor_id)
    if target_pump_model_id is not None:
        config["target_pump_model_id"] = str(target_pump_model_id)

    # Given pages, the run reads those pages. See `MAX_SEED_URLS` for why this exists.
    seeded = seed_url_list(urls)
    if seeded:
        config["urls"] = seeded

    if sweep:
        segments = plan_sweep(kind, country, scope=sweep_scope, countries=countries)
        config["segments"] = segments
        config["sweep_scope"] = sweep_scope or "default"
        config["query"] = None
        one, many = axis_words(sweep_scope)
        config["objective"] = (
            f"Sweep {len(segments)} {many if len(segments) != 1 else one} for "
            f"Oil & Gas pump {kind.noun}s"
        )
        config["queries"] = [segment["label"] for segment in segments]
        label = f"every {one} ({len(segments)} segments)"
    else:
        resolved_query = (query or "").strip()
        generated_objective, generated_queries = kind.build_objective(resolved_query, country)
        config["query"] = resolved_query
        config["objective"] = (objective or "").strip() or generated_objective
        # A caller with a different question asks it in its own words. Vendor enrichment
        # does: "company profile", "certifications", "annual report" - none of which the
        # supplier-finding queries would ask, because it already knows who the supplier
        # is and wants the rest of its record.
        config["queries"] = list(queries) if queries else generated_queries
        label = resolved_query or "Oil & Gas pumps"
        if seeded:
            config["queries"] = []
            config["objective"] = f"Read {len(seeded)} pages supplied with the request"

    batch = ingestion.create_batch(
        db,
        tenant_id=tenant_id,
        name=f"{kind.run_name}: {label}"[:255],
        import_mode=kind.import_mode,
        source_type=SourceType.PARALLEL_SEARCH,
        created_by_user_id=user_id,
        config=config,
    )
    db.flush()
    return batch


def _fail_run(
    db: Session, batch: ImportBatch, kind: DiscoveryKind, stage_key: str, message: str
) -> None:
    _set_stage(db, batch, kind, stage_key, status="failed", detail=message[:400])
    batch.status = IngestionStatus.FAILED
    batch.error_summary = message[:2000]
    batch.finished_at = datetime.now(UTC)
    db.commit()


def record_transport(db: Session, batch_id: uuid.UUID, transport: str, task_id: str | None) -> None:
    """Correct the recorded transport after dispatch, if it turned out different.

    The planned value is written by :func:`start_run` before the runner exists. This only
    has to cover the case where the broker answered the probe and then refused the
    publish. ``jsonb_set`` merges server-side rather than assigning the whole column, so
    it cannot erase the stage progress the runner has already written.
    """
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        return
    _write_config_key(db, batch, "transport", transport)
    _write_config_key(db, batch, "celery_task_id", task_id)


#: How long a single provider call may sit unfinished before the run is declared dead.
#:
#: Every call this pipeline makes is bounded: a search client times out at
#: ``*_TIMEOUT_SECONDS`` and retries a fixed number of times, and the slowest page read
#: observed was 94 seconds. So nothing legitimate approaches this. It exists because a
#: bound in the client is not a bound on the *run*: a thread can die between writing
#: "running" and writing anything else - the process is killed, the machine sleeps, an
#: exception escapes the fallback runner - and the row then says "in progress" for as
#: long as anyone leaves the panel open. One sweep sat at "0/60 searches, 1h 2m elapsed"
#: with a single unfinished job and no way to tell from the outside whether it was
#: working.
STALLED_JOB_SECONDS = 20 * 60


def reap_stalled_runs(db: Session) -> int:
    """Fail runs whose current provider call has been unfinished for too long.

    Called from the poll rather than only at startup, because that is when somebody is
    looking: a stalled run is discovered by the person waiting for it, and it should stop
    claiming progress at that moment instead of at the next restart.

    Only in-process runs. A Celery worker outlives the API, so a job running there is
    telling the truth even when this process cannot see it.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=STALLED_JOB_SECONDS)
    candidates = db.scalars(
        select(ImportBatch).where(
            ImportBatch.import_mode.in_(["vendor_discovery", "pump_discovery"]),
            ImportBatch.status.in_(
                [
                    IngestionStatus.QUEUED,
                    IngestionStatus.FETCHING,
                    IngestionStatus.PARSING,
                    IngestionStatus.PARSED,
                    IngestionStatus.EXTRACTING,
                ]
            ),
        )
    ).all()

    reaped = 0
    for batch in candidates:
        config = dict(batch.config or {})
        if config.get("transport") not in (None, "in_process"):
            continue

        latest = db.scalar(
            select(AiJob)
            .where(AiJob.import_batch_id == batch.id)
            .order_by(AiJob.created_at.desc())
            .limit(1)
        )
        # No job yet: judge by when the run itself started, or it can never be reaped.
        marker = (latest.started_at or latest.created_at) if latest else batch.started_at
        if marker is None or marker > cutoff:
            continue
        if latest is not None and latest.finished_at is not None:
            # The last call finished; the runner is between calls, not stuck in one.
            continue

        stages = [dict(stage) for stage in config.get("stages") or []]
        for stage in stages:
            if stage.get("status") in {"pending", "running"}:
                stage["status"] = "failed"
                stage["detail"] = "Abandoned: no progress for over 20 minutes"
                stage["finished_at"] = _now()
        config["stages"] = stages
        batch.config = config
        batch.status = IngestionStatus.FAILED
        minutes = int((datetime.now(UTC) - marker).total_seconds() // 60)
        batch.error_summary = (
            f"Abandoned after {minutes} minutes with a provider call still unfinished. "
            "The work ran inside the API process, which does not survive a restart or a "
            "sleeping machine - start a Celery worker for a run this long. Anything it "
            "had already found is still listed."
        )
        batch.finished_at = datetime.now(UTC)
        if latest is not None and latest.status == AiJobStatus.RUNNING:
            latest.status = AiJobStatus.FAILED
            latest.finished_at = datetime.now(UTC)
            latest.error_message = "Abandoned: the run was declared stalled"
        reaped += 1

    if reaped:
        db.commit()
        log.warning("discovery.reaped_stalled_runs", count=reaped)
    return reaped


def reap_interrupted_runs(db: Session) -> int:
    """Mark in-process runs that a restart killed. Called once at startup.

    The in-process fallback runs discovery on a daemon thread, so a restart takes the
    work with it — and leaves the row saying `fetching` forever. A sweep makes this much
    more likely, because it runs for an hour rather than a minute. A run that claims to
    be in progress with nothing behind it is worse than a failed one: it never resolves,
    and the UI polls it indefinitely.

    Runs dispatched to Celery are left alone: a worker outlives the API process, so a
    running row there is telling the truth.
    """
    stale = db.scalars(
        select(ImportBatch).where(
            ImportBatch.import_mode.in_(["vendor_discovery", "pump_discovery"]),
            ImportBatch.status.in_(
                [
                    IngestionStatus.QUEUED,
                    IngestionStatus.FETCHING,
                    IngestionStatus.PARSING,
                    IngestionStatus.PARSED,
                    IngestionStatus.EXTRACTING,
                ]
            ),
        )
    ).all()

    reaped = 0
    for batch in stale:
        config = dict(batch.config or {})
        # A null transport is reapable too: Celery dispatch always records a task id, so
        # a missing value means the run never reached a worker.
        if config.get("transport") not in (None, "in_process"):
            continue
        stages = [dict(stage) for stage in config.get("stages") or []]
        for stage in stages:
            if stage.get("status") in {"pending", "running"}:
                stage["status"] = "failed"
                stage["detail"] = "Interrupted by an API restart"
                stage["finished_at"] = _now()
        config["stages"] = stages
        batch.config = config
        batch.status = IngestionStatus.FAILED
        batch.error_summary = (
            "Interrupted by an API restart. This run executed in the API process, which "
            "does not survive one — start a Celery worker for long sweeps. Any candidates "
            "it had already found are still listed."
        )
        batch.finished_at = datetime.now(UTC)
        # Close the call it died inside, or the job list shows a provider call that has
        # been "running" since before the restart and will never finish.
        for job in db.scalars(
            select(AiJob).where(
                AiJob.import_batch_id == batch.id, AiJob.status == AiJobStatus.RUNNING
            )
        ).all():
            job.status = AiJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_message = "Interrupted by an API restart"
        reaped += 1

    # Orphans from before this closed its jobs, and from any run whose batch reached a
    # terminal state while a call was still open. A job stuck at "running" for days is
    # not just untidy: the usage report counts it as in-flight spend that never resolved.
    orphans = db.scalars(
        select(AiJob)
        .join(ImportBatch, ImportBatch.id == AiJob.import_batch_id)
        .where(
            AiJob.status == AiJobStatus.RUNNING,
            ImportBatch.status.in_(
                [
                    IngestionStatus.FAILED,
                    IngestionStatus.PROMOTED,
                    IngestionStatus.EXTRACTED,
                    IngestionStatus.NEEDS_REVIEW,
                ]
            ),
        )
    ).all()
    for job in orphans:
        job.status = AiJobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        job.error_message = job.error_message or "Abandoned: its run had already finished"

    if reaped or orphans:
        db.commit()
        log.warning("discovery.reaped_interrupted_runs", count=reaped, orphan_jobs=len(orphans))
    return reaped


def request_cancel(db: Session, batch: ImportBatch) -> None:
    """Ask a running discovery to stop at its next checkpoint.

    A sweep is twenty-plus searches and up to a hundred-odd Gemma calls, so it can run
    for an hour or more. Starting one by mistake with no way to stop it is not a
    tolerable state, and killing the process would lose the candidates already found.
    """
    _write_config_key(db, batch, "cancel_requested", True)


def _cancelled(db: Session, batch: ImportBatch) -> bool:
    """Re-read the flag: it is set by a different request than the one running the loop."""
    db.refresh(batch, ["config"])
    return bool((batch.config or {}).get("cancel_requested"))


def _finish_cancelled(
    db: Session, batch: ImportBatch, kind: DiscoveryKind, candidates: int
) -> dict:
    """Stop cleanly, keeping whatever was already found.

    A cancelled sweep that discards its candidates would punish the person for stopping
    it, so the run lands in the same reviewable state a completed one does.
    """
    for stage in ("search", "capture", "screen"):
        current = next(
            (s for s in (batch.config or {}).get("stages") or [] if s.get("key") == stage),
            {},
        )
        if current.get("status") in {"pending", "running"}:
            _set_stage(db, batch, kind, stage, status="skipped", detail="Cancelled")
    batch.status = IngestionStatus.NEEDS_REVIEW if candidates else IngestionStatus.EXTRACTED
    batch.error_summary = "Cancelled before finishing. Candidates found so far are kept."
    batch.finished_at = datetime.now(UTC)
    db.commit()
    log.info("discovery.cancelled", kind=kind.slug, batch_id=str(batch.id), candidates=candidates)
    return {"batch_id": str(batch.id), "status": "cancelled", "candidates": candidates}


# ---------------------------------------------------------------------- the run itself


def run_discovery(
    db: Session, kind: DiscoveryKind, batch_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> dict:
    """Execute one discovery run. Safe to call from a worker or a background thread.

    Deliberately transport-agnostic: it takes a session and an id, commits as it goes,
    and never holds a transaction across a provider call.
    """
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        # Either the row is gone, or this session cannot see it. The second is the
        # dangerous one: row level security hiding a job from its own worker looks
        # identical to a finished run that never started, so it is logged as an error
        # rather than returned quietly.
        log.error(
            "discovery.run_not_visible",
            kind=kind.slug,
            batch_id=str(batch_id),
            hint=(
                "The worker cannot see this run. If it belongs to no tenant, the session "
                "must be bound as platform admin."
            ),
        )
        return {"batch_id": str(batch_id), "status": "missing"}

    config = dict(batch.config or {})
    tenant_id = batch.tenant_id
    batch.status = IngestionStatus.FETCHING
    batch.started_at = datetime.now(UTC)

    # Pages handed to the run instead of searched for. When there are any, no search
    # provider is consulted at all - which also means this path works with no search
    # provider configured, because the caller already did that part.
    seed_urls = seed_url_list(config.get("urls"))

    searcher = None
    search_provider = None
    if seed_urls:
        _set_stage(
            db,
            batch,
            kind,
            "search",
            status="skipped",
            detail=f"{len(seed_urls)} page(s) supplied, no search needed",
        )
    else:
        # The settings screen is the source of truth. The environment is only a fallback
        # for an installation that has not configured anything yet, so upgrading does not
        # break a working deployment before an operator visits the page.
        active_search = ai_settings.active_config(db, "search")
        if active_search is not None:
            searcher = providers._from_config(active_search)
            search_provider = active_search.provider
        else:
            searcher = providers.search_client()
            search_provider = settings.SEARCH_PROVIDER
        _set_stage(
            db,
            batch,
            kind,
            "search",
            status="running",
            detail=f"Asking {_PROVIDER_LABELS.get(search_provider, search_provider)} for sources",
            provider=search_provider,
        )
    db.commit()

    # ---- stages 1 and 2: the search provider finds pages, every hit becomes a source ---
    #
    # One search for a single query; one per segment for a sweep. Capture happens inside
    # the loop rather than after it, so a long sweep shows real progress and a failure
    # part-way through still keeps the pages it already found.
    segments = (
        []
        if seed_urls
        else config.get("segments")
        or [
            {
                "key": "single",
                "label": config.get("query") or "search",
                "objective": config.get("objective", ""),
                "queries": config.get("queries") or None,
            }
        ]
    )
    per_segment = int(config.get("max_results") or 10)
    sweeping = len(segments) > 1

    if segments:
        _set_stage(
            db,
            batch,
            kind,
            "search",
            status="running",
            total=len(segments),
            detail=(
                f"Asking {_PROVIDER_LABELS.get(search_provider, search_provider)} across "
                f"{len(segments)} segments"
                if sweeping
                else "Asking for sources"
            ),
        )
    _set_stage(db, batch, kind, "capture", status="running", total=len(seed_urls) or None)
    db.commit()

    source_ids: list[uuid.UUID] = []
    # A sweep asks twenty-plus overlapping questions, so the same OEM page comes back
    # again and again. Skipping a URL already captured in this run is the difference
    # between one Gemma call for that page and twenty.
    seen_urls: set[str] = set()
    duplicates = 0
    searched = 0
    search_failures: list[str] = []

    for url in seed_urls:
        if _cancelled(db, batch):
            return _finish_cancelled(db, batch, kind, 0)
        if url in seen_urls:
            duplicates += 1
            continue
        seen_urls.add(url)
        try:
            # Fetched here rather than trusted from the caller: a stored field has to
            # quote the page PumpAtlas read, not a snippet somebody passed in.
            source = ingestion.register_url(
                db, tenant_id=tenant_id, url=url, batch=batch, user_id=user_id
            )
            source_ids.append(source.id)
        except Exception as exc:  # a single bad URL must not end the run
            batch.failed_items += 1
            log.warning("discovery.capture_failed", kind=kind.slug, url=url, error=str(exc))

    if seed_urls:
        batch.total_items = len(source_ids)
        _set_stage(
            db,
            batch,
            kind,
            "capture",
            done=len(source_ids),
            total=len(source_ids),
            detail=_capture_detail(len(source_ids), duplicates),
        )
        db.commit()

    for segment in segments:
        if _cancelled(db, batch):
            return _finish_cancelled(db, batch, kind, 0)

        search_job = extraction.start_job(
            db,
            tenant_id=tenant_id,
            job_type=AiJobType.WEB_SEARCH,
            import_batch_id=batch.id,
            prompt_name=f"{search_provider}_search",
            # Recorded, not assumed: the job list on the run panel names which provider
            # actually ran, and three of them can do this now.
            provider=search_provider,
            request_payload={
                "segment": segment.get("key"),
                "objective": segment.get("objective"),
                "queries": segment.get("queries"),
                "max_results": per_segment,
            },
            user_id=user_id,
        )
        db.commit()

        try:
            run = searcher.search(
                segment.get("objective", ""),
                segment.get("queries") or None,
                max_results=per_segment,
            )
        except SearchUnavailableError as exc:
            extraction.finish_job(db, search_job, status=AiJobStatus.FAILED, error=str(exc))
            search_failures.append(str(exc))
            log.warning(
                "discovery.search_failed",
                kind=kind.slug,
                batch_id=str(batch_id),
                segment=segment.get("key"),
                error=str(exc),
            )
            # One segment failing must not end a sweep; the single search failing does.
            if not sweeping:
                _fail_run(db, batch, kind, "search", f"Parallel AI: {exc}")
                return {"batch_id": str(batch_id), "status": "failed", "error": str(exc)}
            searched += 1
            _set_stage(db, batch, kind, "search", done=searched)
            db.commit()
            continue

        # `finish_job` expects an OpenRouter AiResult; a Parallel run has none, so the
        # outcome is written onto the job row directly.
        search_job.status = AiJobStatus.SUCCEEDED
        search_job.finished_at = datetime.now(UTC)
        search_job.latency_ms = run.latency_ms
        search_job.response_payload = {
            "search_id": run.search_id,
            "segment": segment.get("key"),
            "result_count": len(run.results),
            "urls": [result.url for result in run.results],
        }

        for result in run.results:
            url = (result.url or "").strip()
            if not url:
                continue
            if url in seen_urls:
                duplicates += 1
                continue
            seen_urls.add(url)
            try:
                excerpt = result.combined_excerpt
                if excerpt:
                    # Parallel AI returns the page text with its hits, so the page is
                    # already readable without a second request.
                    source = ingestion.register_search_result(
                        db,
                        tenant_id=tenant_id,
                        url=url,
                        title=result.title,
                        excerpt=excerpt,
                        search_id=run.search_id,
                        rank=result.rank,
                        batch=batch,
                        user_id=user_id,
                    )
                else:
                    # OpenAI and Claude return a citation - a URL and a title, no text.
                    # Registering that produced a source with an empty body, which the
                    # screening step then skipped as "no usable text": a run that found
                    # pages, stored them, and reported nothing found. So the page is
                    # fetched here, which is also what makes the evidence quote on a
                    # stored field a quote from the page rather than from a snippet.
                    source = ingestion.register_url(
                        db,
                        tenant_id=tenant_id,
                        url=url,
                        batch=batch,
                        user_id=user_id,
                    )
                source_ids.append(source.id)
            except Exception as exc:  # a single bad URL must not end the run
                batch.failed_items += 1
                log.warning("discovery.capture_failed", kind=kind.slug, url=url, error=str(exc))

        searched += 1
        batch.total_items = len(source_ids)
        _set_stage(
            db,
            batch,
            kind,
            "search",
            done=searched,
            detail=(
                f"{searched}/{len(segments)} searched, {len(source_ids)} unique pages"
                if sweeping
                else f"{len(source_ids)} pages found"
            ),
        )
        _set_stage(
            db,
            batch,
            kind,
            "capture",
            done=len(source_ids),
            total=len(source_ids),
            detail=_capture_detail(len(source_ids), duplicates),
        )
        db.commit()

    if segments:
        _set_stage(
            db,
            batch,
            kind,
            "search",
            status="done",
            detail=(
                f"{searched} search(es), {len(source_ids)} unique pages"
                + (f", {len(search_failures)} failed" if search_failures else "")
            ),
        )

    if not source_ids:
        _set_stage(db, batch, kind, "capture", status="skipped", detail="Nothing to capture")
        _set_stage(db, batch, kind, "screen", status="skipped", detail="Nothing to screen")
        batch.status = IngestionStatus.EXTRACTED
        batch.finished_at = datetime.now(UTC)
        db.commit()
        return {"batch_id": str(batch_id), "status": "empty"}

    _set_stage(
        db,
        batch,
        kind,
        "capture",
        status="done",
        done=len(source_ids),
        total=len(source_ids),
        detail=_capture_detail(len(source_ids), duplicates),
    )
    batch.status = IngestionStatus.EXTRACTING

    # ---- stage 3: the reading model screens each page and profiles the record ---
    #
    # Resolved before the stage is marked running, so the badge names the provider that
    # is about to do the work rather than whatever `.env` happens to say.
    # The activated configuration, else whatever the environment names - which is only
    # a fallback for an installation that has not used the settings page yet.
    client = providers.configured_reading_model(db)
    if client is None:
        candidate_client = providers.reading_model()
        client = candidate_client if candidate_client.configured else None
    reading_provider = resolved_providers(db)[1]
    _set_stage(
        db,
        batch,
        kind,
        "screen",
        status="running",
        total=len(source_ids),
        provider=reading_provider,
    )
    db.commit()

    if client is None:
        _fail_run(
            db,
            batch,
            kind,
            "screen",
            f"No reading provider is configured. EXTRACTION_PROVIDER is "
            f"{settings.EXTRACTION_PROVIDER!r}; set its API key, or point it at a "
            f"provider that has one.",
        )
        return {"batch_id": str(batch_id), "status": "failed", "error": "ai_not_configured"}

    # The same rule the ingest path uses: write above a confidence bar, and treat a
    # refusal as a review task rather than an error. Nothing bypasses the provenance
    # gate - a field with no evidence quote is still refused, whoever asked for it.
    auto_store = bool(config.get("auto_store"))
    threshold = float(config.get("min_confidence", extraction.AUTO_PROMOTE_THRESHOLD))

    kept = 0
    rejected = 0
    stored = 0
    for index, source_id in enumerate(source_ids, start=1):
        # Checked per page, not per segment: one Gemma call can take a minute and this
        # is the loop that costs money.
        if _cancelled(db, batch):
            batch.needs_review_items = max(0, kept - stored)
            batch.promoted_items = stored
            return _finish_cancelled(db, batch, kind, kept)

        try:
            outcome, candidate = screen_source(
                db, kind, client, source_id, batch=batch, user_id=user_id
            )
            if outcome == "kept" and candidate is not None and auto_store:
                stored += _store_unattended(db, kind, candidate, threshold)
        except Exception as exc:
            batch.failed_items += 1
            log.warning(
                "discovery.screen_failed",
                kind=kind.slug,
                source_id=str(source_id),
                error=str(exc),
            )
            outcome = None

        if outcome == "kept":
            kept += 1
        elif outcome == "rejected":
            rejected += 1

        batch.processed_items = index
        _set_stage(
            db,
            batch,
            kind,
            "screen",
            done=index,
            detail=_progress_detail(kind, kept, rejected),
        )
        db.commit()

    # `kept` counts everything screened in; the ones written unattended are no longer
    # waiting for anybody, so they are not review work.
    batch.needs_review_items = max(0, kept - stored)
    batch.promoted_items = stored
    _set_stage(
        db,
        batch,
        kind,
        "screen",
        status="done",
        detail=_progress_detail(kind, kept, rejected),
        done=len(source_ids),
    )
    batch.status = IngestionStatus.NEEDS_REVIEW if kept else IngestionStatus.EXTRACTED
    batch.finished_at = datetime.now(UTC)
    db.commit()

    log.info(
        "discovery.finished",
        kind=kind.slug,
        batch_id=str(batch_id),
        candidates=kept,
        rejected=rejected,
        failed=batch.failed_items,
    )
    return {"batch_id": str(batch_id), "status": "done", "candidates": kept}


def _capture_detail(stored: int, duplicates: int) -> str:
    """Duplicates are reported, not hidden: they are the sweep paying for itself."""
    if duplicates:
        return f"{stored} sources stored, {duplicates} duplicate hit(s) skipped"
    return f"{stored} sources stored"


def _progress_detail(kind: DiscoveryKind, kept: int, rejected: int) -> str:
    """A page ruled out is a result, not a failure, so both numbers are reported."""
    return f"{kept} {kind.noun}(s) found, {rejected} page(s) ruled out"


def _store_unattended(
    db: Session, kind: DiscoveryKind, candidate: ExtractedEntity, threshold: float
) -> int:
    """Write one screened candidate straight into the record. Returns 1 if it landed.

    Two things keep this honest rather than a bulk import of whatever the web said:

    * **The confidence bar.** Below it the candidate stays in the review queue, which is
      where a doubtful reading belongs.
    * **The provenance gate is unchanged.** Every field still needs a verbatim evidence
      quote from the captured page, and ``unattended=True`` additionally refuses a
      candidate whose subject name is unusable - a page about "BB3 pumps" would
      otherwise create a record called "BB3" that nobody can act on.

    A refusal is a review task, not a failure: the reason is written onto the candidate
    so a person can see why it was not stored, and the run continues.
    """
    score = candidate.overall_confidence
    if score is None or float(score) < threshold:
        return 0

    try:
        _writer_for(kind)(db, candidate, unattended=True)
    except promotion.PromotionError as exc:
        candidate.review_notes = f"Automatic storing declined: {exc}"
        db.flush()
        log.info("discovery.auto_store_declined", kind=kind.slug, reason=str(exc)[:160])
        return 0
    except Exception as exc:  # noqa: BLE001 - one bad candidate must not end the run
        db.rollback()
        log.warning("discovery.auto_store_failed", kind=kind.slug, error=str(exc)[:200])
        return 0

    db.commit()
    log.info("discovery.auto_stored", kind=kind.slug, candidate_id=str(candidate.id))
    return 1


def _writer_for(kind: DiscoveryKind):
    """The function that writes one candidate of this kind into the record.

    Imported inside the call because both kind modules import this one; a top-level
    import would be circular.
    """
    if kind.slug == "pump":
        from app.services import pump_discovery

        return pump_discovery.store_candidate
    from app.services import vendor_discovery

    return vendor_discovery.store_candidate


def screen_source(
    db: Session,
    kind: DiscoveryKind,
    client: providers.ReadingModel,
    source_id: uuid.UUID,
    *,
    batch: ImportBatch,
    user_id: uuid.UUID | None,
) -> tuple[str | None, ExtractedEntity | None]:
    """Ask the reading model whether one page is in scope, and profile it if so.

    Returns ``("kept", entity)``, ``("rejected", None)`` or ``(None, None)`` when the
    page held no usable text. The entity comes back so the caller can store it without
    re-querying: at a third of a second per round trip, looking it up again would be a
    wasted trip on every page of a 150-page sweep.
    """
    source = db.get(Source, source_id)
    if source is None:
        return None, None

    text = (source.parsed_text or source.raw_content or "").strip()
    if len(text) < MIN_PAGE_CHARS:
        return None, None

    job, result, error = extraction.execute_ai_job(
        db,
        client,
        kind.system_prompt,
        kind.build_user_prompt(text, source_url=source.source_url, source_title=source.title),
        job_kwargs={
            "tenant_id": batch.tenant_id,
            "job_type": AiJobType.CLASSIFY_RECORD,
            "import_batch_id": batch.id,
            "source_id": source.id,
            "prompt_name": f"{kind.slug}_profile",
            "user_id": user_id,
        },
        max_tokens=3500,
    )
    if error is not None or result is None or not result.data:
        raise error or AiResponseError("Gemma returned no parseable JSON")

    data = result.data
    if not data.get(kind.relevance_key):
        reason = str(data.get("relevance_reason") or "Gemma ruled the page out")
        metadata = dict(source.source_metadata or {})
        metadata["discovery_screening"] = {"kind": kind.slug, "kept": False, "reason": reason}
        source.source_metadata = metadata
        db.flush()
        return "rejected", None

    fields = {k: v for k, v in (data.get("fields") or {}).items() if v not in (None, "")}
    subject = {key: data.get(key) for key in kind.subject_keys if data.get(key)}

    off_subject = kind.off_subject(subject, fields) if kind.off_subject else None
    if off_subject:
        metadata = dict(source.source_metadata or {})
        metadata["discovery_screening"] = {
            "kind": kind.slug,
            "kept": False,
            "reason": off_subject,
            "ruled_out_by": "designation",
        }
        source.source_metadata = metadata
        db.flush()
        log.info(
            "discovery.category_page_skipped",
            kind=kind.slug,
            source_url=source.source_url,
            reason=off_subject,
        )
        return "rejected", None

    entity = ExtractedEntity(
        tenant_id=batch.tenant_id,
        source_id=source.id,
        ai_job_id=job.id,
        entity_type=kind.entity_type,
        payload={
            "subject": subject,
            "fields": fields,
            "source_units": data.get("source_units") or {},
            "relevance_reason": data.get("relevance_reason"),
            "oil_gas_evidence": data.get("oil_gas_evidence"),
            "unresolved": data.get("unresolved") or [],
            "discovery_batch_id": str(batch.id),
        },
        raw_payload=data,
        field_confidences=data.get("field_confidences") or {},
        evidence_spans={
            name: {"quote": quote} for name, quote in (data.get("evidence") or {}).items() if quote
        },
        overall_confidence=as_ratio(data.get("overall_confidence")),
        confidence_level=ConfidenceLevel.AI_EXTRACTED,
        review_decision=ReviewDecision.PENDING,
    )
    db.add(entity)
    db.flush()
    return "kept", entity


def as_ratio(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    if parsed < 0 or parsed > 1:
        return None
    return parsed


# ------------------------------------------------------------------------ candidates


def candidate_query(kind: DiscoveryKind, batch_id: uuid.UUID):
    """Candidates for one run, found through the screening job that produced them.

    ``extracted_entities`` has no batch column, and the obvious substitute - the source
    the page was captured into - is wrong often enough to matter. ``register_url``
    deduplicates by content hash across the whole tenant: a page some earlier run
    already captured is returned as-is, still attached to *that* run, so a candidate
    screened here hangs off a source belonging to a batch from last week. The run then
    reported "1 pump model found" above a panel listing none of them, which is the same
    dead end as finding nothing while looking nothing like it.

    Two searches for the same term hit this too, which is why the fix is here rather
    than in the seeded path that exposed it.

    The screening job is the honest link: it is created for this batch, one per page
    read, and it is what the entity records in ``ai_job_id``. The source join remains as
    a fallback for rows written before jobs were recorded.
    """
    return (
        select(ExtractedEntity)
        .outerjoin(Source, Source.id == ExtractedEntity.source_id)
        .outerjoin(AiJob, AiJob.id == ExtractedEntity.ai_job_id)
        .where(
            or_(
                AiJob.import_batch_id == batch_id,
                and_(
                    ExtractedEntity.ai_job_id.is_(None),
                    Source.import_batch_id == batch_id,
                ),
            ),
            ExtractedEntity.entity_type == kind.entity_type,
        )
        .order_by(ExtractedEntity.overall_confidence.desc().nullslast())
    )


def candidates_with_sources(
    db: Session, kind: DiscoveryKind, batch_id: uuid.UUID
) -> list[tuple[ExtractedEntity, Source | None]]:
    """Candidates for one run, each paired with the page it came from.

    :func:`candidate_query` already joins ``sources`` to find the candidates, so the
    source rows cost nothing extra here. Fetching them separately - one ``db.get`` per
    candidate while rendering - is a round trip each, and this database is remote.
    """
    rows = db.execute(candidate_query(kind, batch_id).add_columns(Source)).all()
    return [(entity, source) for entity, source in rows]  # noqa: C416 - retype the rows


def candidate_counts(db: Session, kind: DiscoveryKind, batch_id: uuid.UUID) -> tuple[int, int]:
    """(total, stored) for one run, without loading the candidates.

    The run list needs the real numbers: a row that says "0 found" when two are waiting
    reads as a failed run rather than an unopened one.
    """
    rows = db.execute(
        select(ExtractedEntity.promoted_at)
        .join(Source, Source.id == ExtractedEntity.source_id)
        .where(
            Source.import_batch_id == batch_id,
            ExtractedEntity.entity_type == kind.entity_type,
        )
    ).all()
    return len(rows), sum(1 for (promoted_at,) in rows if promoted_at is not None)


def reject_candidate(db: Session, entity: ExtractedEntity, *, principal=None) -> None:
    """Mark a candidate as not wanted. The source stays; only the decision is recorded."""
    entity.review_decision = ReviewDecision.REJECTED
    entity.reviewed_by_user_id = principal.user_id if principal else None
    entity.reviewed_at = datetime.now(UTC)
    db.flush()


#: How many provider calls the run detail carries. A 23-segment sweep makes hundreds;
#: the panel only ever shows the recent ones, and the poll should not grow without
#: bound just because a run is long.
JOB_FEED_LIMIT = 40


def job_summary(
    db: Session, batch_id: uuid.UUID, *, limit: int = JOB_FEED_LIMIT
) -> tuple[list[dict[str, Any]], int]:
    """(most recent provider calls, total count), so the UI can show what each AI did.

    Failed calls are kept ahead of the limit: on a long sweep the errors are the reason
    anyone opens this panel, and they would otherwise scroll off the end.
    """
    rows = db.scalars(
        select(AiJob).where(AiJob.import_batch_id == batch_id).order_by(AiJob.created_at)
    ).all()
    total = len(rows)
    if total > limit:
        failed = [job for job in rows if job.status == AiJobStatus.FAILED]
        recent = [job for job in rows[-limit:] if job.status != AiJobStatus.FAILED]
        rows = (failed + recent)[-limit:]
    return [
        {
            "provider": job.provider,
            "prompt_name": job.prompt_name,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "model": job.model,
            "latency_ms": job.latency_ms,
            "error": job.error_message,
        }
        for job in rows
    ], total
