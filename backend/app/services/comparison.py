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
from app.models.comparison import RequirementProfile
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


def _as_score(value: float | None) -> Decimal | None:
    """A score column takes a number or nothing; `Decimal("None")` raises."""
    return None if value is None else Decimal(str(value))


def _upsert_score(
    db: Session,
    pump_model_id: uuid.UUID,
    tenant_id: Any,
    card: scoring.Scorecard,
    profile: RequirementProfile | None,
) -> ConfidenceScore | None:
    """Store the card, or remove any stored score when there is nothing to store.

    `confidence_scores.score` is NOT NULL, so an unscorable card has no row to write -
    and absence is the right representation anyway: no row means nothing was scored,
    where a 0.000 row would mean "scored, and terrible".

    An existing row is deleted rather than left behind. Data can be withdrawn - a spec
    corrected away, a source retracted - and a stale row would go on asserting a score
    the evidence no longer supports.
    """
    profile_id = profile.id if profile else None
    existing = db.scalar(
        select(ConfidenceScore).where(
            ConfidenceScore.entity_type == "pump_models",
            ConfidenceScore.entity_id == pump_model_id,
            ConfidenceScore.scorecard_kind == card.kind,
            ConfidenceScore.requirement_profile_id == profile_id,
        )
    )
    if card.score is None:
        if existing is not None:
            db.delete(existing)
        return None
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
