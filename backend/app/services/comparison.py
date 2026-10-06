"""Build and score comparisons - the procurement deliverable.

A comparison freezes what was shown: scores, the field values behind them and the
requirement profile used. That snapshot is what makes it defensible in a tender review
six months later, when the underlying records have moved on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import current_tenant_id
from app.core.logging import get_logger
from app.models.ai import ConfidenceScore
from app.models.comparison import Comparison, ComparisonItem, RequirementProfile
from app.models.enums import ScorecardKind
from app.schemas.specs import ALL_TRACKED_FIELDS
from app.services import records, scoring

log = get_logger(__name__)

# Columns the comparison grid shows by default - the ones buyers actually decide on.
DEFAULT_COMPARISON_FIELDS = [
    "vendor_name",
    "model_code",
    "pump_type",
    "applicable_standard",
    "rated_capacity_m3h",
    "rated_head_m",
    "npsh_required_m",
    "hydraulic_efficiency_pct",
    "rated_power_kw",
    "rated_speed_rpm",
    "material_class",
    "seal_system_type",
    "seal_piping_plan",
    "area_classification",
    "certifications",
    "base_price_amount",
    "base_price_currency",
    "payment_terms",
    "warranty_months",
    "lifecycle_cost_usd",
    "standard_lead_time_weeks",
    "expedited_lead_time_weeks",
    "country_of_origin",
    "historical_on_time_delivery_pct",
    "dry_weight_kg",
    "operating_weight_kg",
    "footprint_area_m2",
    "units_installed_operating",
    "mtbf_hours",
    "fpso_experience",
    "qaqc_certifications",
    "confidence_level",
    "verification_status",
    "data_completeness_pct",
]


def profile_to_dict(profile: RequirementProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        column.name: records.to_jsonable(getattr(profile, column.name))
        for column in profile.__table__.columns
    }


def score_pump_model(
    db: Session,
    pump_model_id: uuid.UUID,
    profile: RequirementProfile | None = None,
    *,
    persist: bool = True,
    record: dict[str, Any] | None = None,
) -> tuple[dict[str, scoring.Scorecard], dict[str, Any]]:
    """Score one pump model against a profile. Returns ``(scorecards, flat_record)``.

    ``record`` lets a caller that has already flattened the model skip doing it again;
    the pump profile page does exactly that.
    """
    if record is None:
        record = records.flatten_pump_model(db, pump_model_id)
    if not record:
        raise ValueError(f"Pump model {pump_model_id} not found")

    profile_dict = profile_to_dict(profile)
    cards = scoring.score_all(record, profile_dict, tracked_fields=ALL_TRACKED_FIELDS)

    if persist:
        # The flattened record has no tenant of its own (and a shared-master model's is
        # NULL), so the owner of a derived scorecard is the tenant it was computed for.
        owner = current_tenant_id(db)
        if owner is not None:
            for card in cards.values():
                _upsert_score(db, pump_model_id, owner, card, profile)
    return cards, record


def _upsert_score(
    db: Session,
    pump_model_id: uuid.UUID,
    tenant_id: Any,
    card: scoring.Scorecard,
    profile: RequirementProfile | None,
) -> ConfidenceScore:
    profile_id = profile.id if profile else None
    existing = db.scalar(
        select(ConfidenceScore).where(
            ConfidenceScore.entity_type == "pump_models",
            ConfidenceScore.entity_id == pump_model_id,
            ConfidenceScore.scorecard_kind == card.kind,
            ConfidenceScore.requirement_profile_id == profile_id,
        )
    )
    row = existing or ConfidenceScore(
        tenant_id=(profile.tenant_id if profile else None) or tenant_id,
        entity_type="pump_models",
        entity_id=pump_model_id,
        scorecard_kind=card.kind,
        requirement_profile_id=profile_id,
    )
    row.score = Decimal(str(card.score))
    row.grade = card.grade
    row.breakdown = records.to_jsonable(card.breakdown())
    row.weighting_profile = (
        {
            "technical": records.to_jsonable(profile.weight_technical),
            "commercial": records.to_jsonable(profile.weight_commercial),
            "delivery": records.to_jsonable(profile.weight_delivery),
            "data_confidence": records.to_jsonable(profile.weight_data_confidence),
        }
        if profile
        else scoring.DEFAULT_WEIGHTS
    )
    row.fields_evaluated = card.fields_evaluated
    row.fields_missing = card.fields_missing
    row.computed_by_version = scoring.SCORING_VERSION
    row.computed_at = datetime.now(UTC)
    row.is_stale = False
    if existing is None:
        db.add(row)
    return row


def build_comparison(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    name: str,
    pump_model_ids: list[uuid.UUID],
    requirement_profile_id: uuid.UUID | None = None,
    description: str | None = None,
    fields_shown: list[str] | None = None,
    principal=None,
) -> Comparison:
    """Score each candidate, rank them and freeze the result."""
    profile = db.get(RequirementProfile, requirement_profile_id) if requirement_profile_id else None
    fields = fields_shown or DEFAULT_COMPARISON_FIELDS

    comparison = Comparison(
        tenant_id=tenant_id,
        name=name,
        description=description,
        requirement_profile_id=profile.id if profile else None,
        comparison_kind="pump_model",
        fields_shown=fields,
        status="draft",
        created_by_user_id=principal.user_id if principal else None,
    )
    db.add(comparison)
    db.flush()

    scored: list[tuple[ComparisonItem, float]] = []
    snapshot_rows: list[dict[str, Any]] = []

    for position, pump_model_id in enumerate(pump_model_ids):
        cards, record = score_pump_model(db, pump_model_id, profile)
        overall = cards["overall"]
        item = ComparisonItem(
            tenant_id=tenant_id,
            comparison_id=comparison.id,
            pump_model_id=pump_model_id,
            position=position,
            technical_score=Decimal(str(cards["technical"].score)),
            commercial_score=Decimal(str(cards["commercial"].score)),
            delivery_risk_score=Decimal(str(cards["delivery"].score)),
            data_confidence_score=Decimal(str(cards["data_confidence"].score)),
            overall_score=Decimal(str(overall.score)),
            score_breakdown={
                kind: {
                    "score": card.score,
                    "grade": card.grade,
                    "fields_evaluated": card.fields_evaluated,
                    "fields_missing": card.fields_missing,
                    "breakdown": records.to_jsonable(card.breakdown()),
                }
                for kind, card in cards.items()
            },
            disqualified=overall.disqualified,
            disqualification_reason=overall.disqualification_reason,
        )
        db.add(item)
        scored.append((item, overall.score))
        snapshot_rows.append(
            {
                "pump_model_id": str(pump_model_id),
                "label": f"{record.get('vendor_name')} {record.get('model_code')}",
                "values": {field: records.to_jsonable(record.get(field)) for field in fields},
                "scores": {
                    "technical": cards["technical"].score,
                    "commercial": cards["commercial"].score,
                    "delivery_risk": cards["delivery"].score,
                    "data_confidence": cards["data_confidence"].score,
                    "overall": overall.score,
                },
                "disqualified": overall.disqualified,
                "disqualification_reason": overall.disqualification_reason,
            }
        )

    # Compliant candidates rank first; disqualified ones keep a rank so they stay visible.
    ordered = sorted(scored, key=lambda pair: (pair[0].disqualified, -pair[1]))
    for rank, (item, _) in enumerate(ordered, start=1):
        item.rank = rank
    for row in snapshot_rows:
        match = next(
            (item for item, _ in ordered if str(item.pump_model_id) == row["pump_model_id"]),
            None,
        )
        row["rank"] = match.rank if match else None

    comparison.snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scoring_version": scoring.SCORING_VERSION,
        "requirement_profile": profile_to_dict(profile),
        "fields_shown": fields,
        "rows": snapshot_rows,
    }
    db.flush()
    log.info(
        "comparison.built",
        comparison_id=str(comparison.id),
        candidates=len(pump_model_ids),
        profile=str(profile.id) if profile else None,
    )
    return comparison


def generate_narrative(
    db: Session,
    comparison: Comparison,
    *,
    client=None,
    user_id: uuid.UUID | None = None,
) -> str | None:
    """Have Gemma write the decision narrative around the computed scores."""
    import json

    from app.ai import prompts
    from app.ai.openrouter import OpenRouterClient
    from app.models.enums import AiJobType
    from app.services import extraction

    client = client or OpenRouterClient()
    job, result, error = extraction.execute_ai_job(
        db,
        client,
        prompts.SYSTEM_COMPARISON_NARRATIVE,
        json.dumps(comparison.snapshot, indent=2, default=str),
        job_kwargs={
            "tenant_id": comparison.tenant_id,
            "job_type": AiJobType.CLASSIFY_RECORD,
            "subject_type": "comparisons",
            "subject_id": comparison.id,
            "prompt_name": "comparison_narrative",
            "request_payload": {"candidates": len(comparison.snapshot.get("rows", []))},
            "model": client.model,
            "user_id": user_id,
        },
        temperature=0.3,
    )
    if error is not None:
        log.warning("comparison.narrative_failed", error=str(error))
        return None
    data = (result.data if result else None) or {}
    comparison.ai_narrative = data.get("narrative")
    snapshot = dict(comparison.snapshot)
    snapshot["ai_analysis"] = {
        "key_differentiators": data.get("key_differentiators", []),
        "data_gaps_affecting_ranking": data.get("data_gaps_affecting_ranking", []),
        "recommended_next_steps": data.get("recommended_next_steps", []),
        "ai_job_id": str(job.id),
    }
    comparison.snapshot = snapshot
    db.flush()
    return comparison.ai_narrative


def recompute_scores(db: Session, pump_model_ids: list[uuid.UUID]) -> int:
    """Rescore against platform defaults - called after a promotion or edit."""
    count = 0
    for pump_model_id in pump_model_ids:
        try:
            score_pump_model(db, pump_model_id, None)
            count += 1
        except ValueError:
            continue
    return count


def mark_scores_stale(db: Session, pump_model_id: uuid.UUID) -> None:
    """Flag stored scorecards for recomputation without blocking the write path."""
    for row in db.scalars(
        select(ConfidenceScore).where(
            ConfidenceScore.entity_type == "pump_models",
            ConfidenceScore.entity_id == pump_model_id,
        )
    ).all():
        row.is_stale = True


VENDOR_SCORECARD_KINDS = (
    ScorecardKind.TECHNICAL_FIT,
    ScorecardKind.COMMERCIAL_FIT,
    ScorecardKind.DELIVERY_RISK,
    ScorecardKind.DATA_CONFIDENCE,
    ScorecardKind.OVERALL,
)
