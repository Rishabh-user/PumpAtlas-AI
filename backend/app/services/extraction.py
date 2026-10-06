"""AI extraction orchestration.

Runs Gemma over a source's parsed text, one field group at a time, and records the
result as ``extracted_entities`` rows awaiting review. Nothing is promoted here - see
``app.services.promotion``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.openrouter import AiResponseError, AiResult, AiUnavailableError, OpenRouterClient
from app.core.logging import get_logger
from app.models.ai import AiJob, ExtractedEntity
from app.models.enums import (
    AiJobStatus,
    AiJobType,
    ConfidenceLevel,
    IngestionStatus,
    ReviewDecision,
)
from app.models.source import Source
from app.utils import units

log = get_logger(__name__)

# Group name -> the entity_type the promotion step will write into.
GROUP_TO_ENTITY = {
    "identity": "pump_model",
    "technical": "technical_spec",
    "commercial": "commercial_spec",
    "dimensional": "dimensional_spec",
    "delivery": "delivery_spec",
    "operational": "operational_spec",
    "administrative": "administrative_spec",
}

# Below this, a field is dropped rather than shown to a reviewer as noise.
MIN_FIELD_CONFIDENCE = 0.4
# At or above this, a batch marked auto_promote may write without human review.
AUTO_PROMOTE_THRESHOLD = 0.85


def confidence_to_level(score: float | None) -> ConfidenceLevel:
    if score is None:
        return ConfidenceLevel.UNKNOWN
    if score >= 0.9:
        return ConfidenceLevel.AI_EXTRACTED
    if score >= 0.6:
        return ConfidenceLevel.AI_EXTRACTED
    return ConfidenceLevel.ESTIMATED


def start_job(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    job_type: AiJobType,
    source_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    import_batch_id: uuid.UUID | None = None,
    subject_type: str | None = None,
    subject_id: uuid.UUID | None = None,
    prompt_name: str | None = None,
    request_payload: dict[str, Any] | None = None,
    provider: str = "openrouter",
    model: str | None = None,
    user_id: uuid.UUID | None = None,
    celery_task_id: str | None = None,
) -> AiJob:
    job = AiJob(
        tenant_id=tenant_id,
        job_type=job_type,
        status=AiJobStatus.RUNNING,
        provider=provider,
        model=model,
        prompt_name=prompt_name,
        prompt_version=prompts.PROMPT_VERSION,
        source_id=source_id,
        document_id=document_id,
        import_batch_id=import_batch_id,
        subject_type=subject_type,
        subject_id=subject_id,
        request_payload=request_payload or {},
        celery_task_id=celery_task_id,
        started_at=datetime.now(UTC),
        triggered_by_user_id=user_id,
    )
    db.add(job)
    db.flush()
    return job


def finish_job(
    db: Session,
    job: AiJob,
    *,
    result: AiResult | None = None,
    status: AiJobStatus = AiJobStatus.SUCCEEDED,
    error: str | None = None,
) -> AiJob:
    job.status = status
    job.finished_at = datetime.now(UTC)
    job.error_message = error
    if result is not None:
        job.model = result.model
        job.response_payload = result.data or {}
        job.raw_response_text = result.text[:200_000] if result.text else None
        job.prompt_tokens = result.prompt_tokens
        job.completion_tokens = result.completion_tokens
        job.latency_ms = result.latency_ms
        if result.cost_usd is not None:
            job.cost_usd = result.cost_usd
    db.flush()
    return job


def execute_ai_job(
    db: Session,
    client: OpenRouterClient,
    system_prompt: str,
    user_prompt: str,
    *,
    job_kwargs: dict[str, Any],
    **complete_kwargs: Any,
) -> tuple[AiJob, AiResult | None, Exception | None]:
    """Record an AI job, call the provider, record the outcome.

    The commit before ``client.complete`` is the point of this helper, not incidental.
    A provider call can take minutes - one Gemma call on a full web page took 119
    seconds - and holding a database transaction open across it trips PostgreSQL's
    ``idle_in_transaction_session_timeout``. The server closes the connection, and the
    task dies with ``PendingRollbackError`` *after* the model has already been paid for.

    So: the job row is committed first (it is the durable record that the call was
    attempted), the transaction is released, the HTTP call happens with no database
    resources held, and the result is written in a fresh transaction. The tenant GUC is
    re-applied automatically on that new transaction, so RLS still applies.

    Returns ``(job, result, error)``. Callers decide whether to raise.
    """
    job = start_job(db, **job_kwargs)
    db.commit()

    try:
        result = client.complete(system_prompt, user_prompt, **complete_kwargs)
    except (AiUnavailableError, AiResponseError) as exc:
        finish_job(db, job, status=AiJobStatus.FAILED, error=str(exc))
        db.commit()
        return job, None, exc
    except Exception as exc:  # noqa: BLE001 - any provider failure must be recorded
        finish_job(db, job, status=AiJobStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        db.commit()
        return job, None, exc

    finish_job(db, job, result=result)
    db.commit()
    return job, result, None


def normalise_group_fields(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """SI-normalise numeric fields by name suffix.

    Returns ``(clean_fields, conversion_notes, failures)``. A conversion failure drops
    the field rather than storing an unconvertible number.
    """
    clean: dict[str, Any] = {}
    notes: dict[str, str] = {}
    failures: list[str] = []
    for name, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list, bool)):
            clean[name] = value
            continue
        try:
            converted, original = units.normalise_field(name, value)
        except units.UnitConversionError as exc:
            failures.append(f"{name}: {exc}")
            continue
        if converted is None:
            clean[name] = value
        else:
            clean[name] = converted
            if original and original != str(converted):
                notes[name] = original
    return clean, notes, failures


def _filter_by_confidence(
    fields: dict[str, Any], confidences: dict[str, Any], evidence: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, float], dict[str, str]]:
    kept: dict[str, Any] = {}
    kept_conf: dict[str, float] = {}
    kept_evidence: dict[str, str] = {}
    for name, value in fields.items():
        try:
            score = float(confidences.get(name, 0.0))
        except (TypeError, ValueError):
            score = 0.0
        if score < MIN_FIELD_CONFIDENCE:
            continue
        quote = evidence.get(name)
        if not quote:
            # No citation, no promotion. Keeping it would break traceability.
            continue
        kept[name] = value
        kept_conf[name] = score
        kept_evidence[name] = str(quote)[:2000]
    return kept, kept_conf, kept_evidence


def extract_from_source(
    db: Session,
    source: Source,
    *,
    groups: list[str] | None = None,
    client: OpenRouterClient | None = None,
    user_id: uuid.UUID | None = None,
    import_batch_id: uuid.UUID | None = None,
    celery_task_id: str | None = None,
) -> list[ExtractedEntity]:
    """Run extraction for one source and persist candidate records."""
    if not source.parsed_text:
        raise ValueError(f"Source {source.id} has no parsed text to extract from")

    client = client or OpenRouterClient()
    selected = groups or list(prompts.ALL_FIELD_GROUPS)
    created: list[ExtractedEntity] = []
    # Committed immediately so the import queue shows progress while a long run is in
    # flight, rather than the row appearing to sit untouched for minutes.
    source.status = IngestionStatus.EXTRACTING
    db.commit()

    for group in selected:
        user_prompt = prompts.build_extraction_prompt(
            source.parsed_text,
            [group],
            source_url=source.source_url,
            source_type=source.source_type.value,
            vendor_hint=source.vendor_hint,
            captured_at=source.captured_at.isoformat() if source.captured_at else None,
        )
        job, result, error = execute_ai_job(
            db,
            client,
            prompts.SYSTEM_EXTRACTION,
            user_prompt,
            job_kwargs={
                "tenant_id": source.tenant_id,
                "job_type": AiJobType.EXTRACT_STRUCTURED,
                "source_id": source.id,
                "import_batch_id": import_batch_id,
                "subject_type": "source",
                "subject_id": source.id,
                "prompt_name": f"extract_{group}",
                "request_payload": {"group": group, "chars": len(source.parsed_text)},
                "model": client.model,
                "user_id": user_id,
                "celery_task_id": celery_task_id,
            },
        )
        if error is not None:
            log.warning("extraction.group_failed", group=group, error=str(error))
            continue
        if result is None or not result.data:
            log.warning("extraction.unparseable_output", group=group, job_id=str(job.id))
            continue

        created.extend(_persist_records(db, source, job, group, result))
        db.commit()

    source.status = IngestionStatus.EXTRACTED if created else IngestionStatus.NEEDS_REVIEW
    db.commit()
    log.info(
        "extraction.completed",
        source_id=str(source.id),
        entities=len(created),
        groups=len(selected),
    )
    return created


def _persist_records(
    db: Session, source: Source, job: AiJob, group: str, result: AiResult
) -> list[ExtractedEntity]:
    payload = result.data or {}
    records = payload.get("records")
    if not isinstance(records, list):
        records = [payload] if payload.get("fields") else []

    subject = payload.get("subject") or {}
    created: list[ExtractedEntity] = []

    for record in records:
        if not isinstance(record, dict):
            continue
        raw_fields = record.get("fields") or {}
        if not isinstance(raw_fields, dict) or not raw_fields:
            continue
        confidences = record.get("confidence") or {}
        evidence = record.get("evidence") or {}
        source_units = record.get("source_units") or {}

        kept, kept_conf, kept_evidence = _filter_by_confidence(raw_fields, confidences, evidence)
        if not kept:
            continue
        clean, conversion_notes, failures = normalise_group_fields(kept)
        merged_units = {**source_units, **conversion_notes}

        scores = [kept_conf[name] for name in clean if name in kept_conf]
        overall = round(sum(scores) / len(scores), 4) if scores else None

        entity = ExtractedEntity(
            tenant_id=source.tenant_id,
            source_id=source.id,
            ai_job_id=job.id,
            entity_type=GROUP_TO_ENTITY.get(record.get("group") or group, "pump_model"),
            payload={
                "fields": {k: _jsonable(v) for k, v in clean.items()},
                "subject": subject,
                "group": group,
                "source_units": merged_units,
                "conversion_failures": failures,
                "model_notes": payload.get("notes"),
            },
            raw_payload={"fields": raw_fields, "confidence": confidences},
            field_confidences=kept_conf,
            evidence_spans={name: {"quote": quote} for name, quote in kept_evidence.items()},
            overall_confidence=overall,
            confidence_level=confidence_to_level(overall),
            review_decision=ReviewDecision.PENDING,
        )
        db.add(entity)
        created.append(entity)

    db.flush()
    return created


def _jsonable(value: Any) -> Any:
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def run_normalisation(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    raw_values: dict[str, str],
    client: OpenRouterClient | None = None,
    subject_type: str | None = None,
    subject_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Map free-text values onto the controlled vocabulary."""
    client = client or OpenRouterClient()
    user_prompt = "Normalise these captured values:\n" + "\n".join(
        f"{name}: {value}" for name, value in raw_values.items()
    )
    _job, result, error = execute_ai_job(
        db,
        client,
        prompts.SYSTEM_NORMALIZATION,
        user_prompt,
        job_kwargs={
            "tenant_id": tenant_id,
            "job_type": AiJobType.NORMALIZE_VALUES,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "prompt_name": "normalize_values",
            "request_payload": {"raw_values": raw_values},
            "model": client.model,
            "user_id": user_id,
        },
    )
    if error is not None:
        raise error
    return ((result.data if result else None) or {}).get("normalized", {})


def summarise_vendor(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    vendor_id: uuid.UUID,
    facts: dict[str, Any],
    client: OpenRouterClient | None = None,
    user_id: uuid.UUID | None = None,
) -> tuple[dict[str, Any], AiJob]:
    """Produce the vendor briefing shown on the vendor profile page."""
    import json

    client = client or OpenRouterClient()
    job, result, error = execute_ai_job(
        db,
        client,
        prompts.SYSTEM_VENDOR_SUMMARY,
        "Facts held in the database:\n" + json.dumps(facts, indent=2, default=str),
        job_kwargs={
            "tenant_id": tenant_id,
            "job_type": AiJobType.SUMMARIZE_VENDOR,
            "subject_type": "vendor",
            "subject_id": vendor_id,
            "prompt_name": "summarize_vendor",
            "request_payload": {"fact_keys": sorted(facts)},
            "model": client.model,
            "user_id": user_id,
        },
        temperature=0.2,
    )
    if error is not None:
        raise error
    return ((result.data if result else None) or {}), job
