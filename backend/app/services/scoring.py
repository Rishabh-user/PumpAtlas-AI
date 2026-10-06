"""Scorecards: technical fit, commercial fit, delivery risk, data confidence.

Scoring is deliberately deterministic and explainable - every score comes back with a
per-criterion breakdown, because a buyer has to defend the ranking in a tender review.
The AI layer only writes the narrative around these numbers, never the numbers.

The one rule worth stating loudly: **missing data never scores as good data.** A
candidate with no price does not win on price; it is scored ``None`` for that criterion
and the gap is surfaced in ``fields_missing`` and in the data-confidence scorecard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.models.enums import ConfidenceLevel, ScorecardKind, VerificationStatus

SCORING_VERSION = "1.0.0"

# Confidence level -> how much a value backed by it is worth, 0-100.
CONFIDENCE_WEIGHT: dict[str, float] = {
    ConfidenceLevel.VERIFIED.value: 100.0,
    ConfidenceLevel.VENDOR_DECLARED.value: 75.0,
    ConfidenceLevel.THIRD_PARTY.value: 60.0,
    ConfidenceLevel.AI_EXTRACTED.value: 50.0,
    ConfidenceLevel.ESTIMATED.value: 30.0,
    ConfidenceLevel.UNKNOWN.value: 10.0,
}

VERIFICATION_WEIGHT: dict[str, float] = {
    VerificationStatus.VERIFIED.value: 100.0,
    VerificationStatus.IN_REVIEW.value: 60.0,
    VerificationStatus.UNVERIFIED.value: 40.0,
    VerificationStatus.DISPUTED.value: 10.0,
    VerificationStatus.SUPERSEDED.value: 20.0,
}


@dataclass
class Criterion:
    """One scored dimension."""

    name: str
    weight: float
    score: float | None
    reason: str
    value: Any = None
    target: Any = None

    @property
    def contribution(self) -> float:
        return 0.0 if self.score is None else self.score * self.weight


@dataclass
class Scorecard:
    kind: ScorecardKind
    score: float
    criteria: list[Criterion] = field(default_factory=list)
    disqualified: bool = False
    disqualification_reason: str | None = None

    @property
    def fields_evaluated(self) -> int:
        return sum(1 for c in self.criteria if c.score is not None)

    @property
    def fields_missing(self) -> int:
        return sum(1 for c in self.criteria if c.score is None)

    @property
    def grade(self) -> str:
        if self.score >= 85:
            return "A"
        if self.score >= 70:
            return "B"
        if self.score >= 55:
            return "C"
        if self.score >= 40:
            return "D"
        return "E"

    def breakdown(self) -> dict[str, Any]:
        return {
            c.name: {
                "score": c.score,
                "weight": round(c.weight, 4),
                "contribution": round(c.contribution, 3),
                "value": _plain(c.value),
                "target": _plain(c.target),
                "reason": c.reason,
            }
            for c in self.criteria
        }


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aggregate(kind: ScorecardKind, criteria: list[Criterion]) -> Scorecard:
    """Weighted mean over the criteria that could be evaluated.

    Weights are renormalised across evaluated criteria so a missing field does not
    silently drag a score toward zero - the absence is reported separately instead.
    """
    scored = [c for c in criteria if c.score is not None]
    total_weight = sum(c.weight for c in scored)
    if not scored or total_weight <= 0:
        return Scorecard(kind=kind, score=0.0, criteria=criteria)
    value = sum(c.score * c.weight for c in scored) / total_weight  # type: ignore[operator]
    return Scorecard(kind=kind, score=round(value, 3), criteria=criteria)


def _closeness(actual: float, target: float, tolerance_pct: float = 15.0) -> float:
    """100 at target, decaying to 0 at three times the tolerance band."""
    if target == 0:
        return 100.0 if actual == 0 else 0.0
    deviation_pct = abs(actual - target) / abs(target) * 100.0
    if deviation_pct <= tolerance_pct:
        return 100.0 - (deviation_pct / tolerance_pct) * 15.0
    span = tolerance_pct * 3.0
    if deviation_pct >= span:
        return 0.0
    return max(0.0, 85.0 * (1.0 - (deviation_pct - tolerance_pct) / (span - tolerance_pct)))


def _lower_is_better(actual: float, budget: float) -> float:
    """100 at or under half the budget, 50 at the budget, 0 at twice the budget."""
    if budget <= 0:
        return 0.0
    ratio = actual / budget
    if ratio <= 0.5:
        return 100.0
    if ratio <= 1.0:
        return 100.0 - (ratio - 0.5) * 100.0
    if ratio >= 2.0:
        return 0.0
    return max(0.0, 50.0 * (2.0 - ratio))


def score_technical_fit(record: dict[str, Any], profile: dict[str, Any]) -> Scorecard:
    """How well a pump model meets the requirement profile's duty and hard requirements."""
    criteria: list[Criterion] = []
    disqualified = False
    reasons: list[str] = []

    # --- duty point -------------------------------------------------------
    for field_name, target_key, weight, label in (
        ("rated_capacity_m3h", "required_capacity_m3h", 0.22, "capacity"),
        ("rated_head_m", "required_head_m", 0.22, "head"),
    ):
        actual, target = _num(record.get(field_name)), _num(profile.get(target_key))
        if actual is None:
            criteria.append(
                Criterion(label, weight, None, f"{field_name} not recorded", None, target)
            )
        elif target is None:
            criteria.append(
                Criterion(label, weight, 70.0, "no requirement stated; value present", actual)
            )
        else:
            criteria.append(
                Criterion(
                    label,
                    weight,
                    round(_closeness(actual, target), 2),
                    f"{actual} against required {target}",
                    actual,
                    target,
                )
            )

    # --- NPSH margin: a hard engineering gate ----------------------------
    npshr, max_npshr = _num(record.get("npsh_required_m")), _num(profile.get("max_npshr_m"))
    if npshr is None:
        criteria.append(Criterion("npsh_required", 0.14, None, "NPSHr not recorded"))
    elif max_npshr is None:
        criteria.append(Criterion("npsh_required", 0.14, 70.0, "no NPSHr limit stated", npshr))
    elif npshr > max_npshr:
        disqualified = True
        reasons.append(f"NPSHr {npshr} m exceeds the available margin of {max_npshr} m")
        criteria.append(
            Criterion("npsh_required", 0.14, 0.0, "exceeds available NPSH", npshr, max_npshr)
        )
    else:
        criteria.append(
            Criterion(
                "npsh_required",
                0.14,
                round(_lower_is_better(npshr, max_npshr), 2),
                "within available NPSH",
                npshr,
                max_npshr,
            )
        )

    # --- efficiency -------------------------------------------------------
    efficiency = _num(record.get("hydraulic_efficiency_pct"))
    min_efficiency = _num(profile.get("min_efficiency_pct"))
    if efficiency is None:
        criteria.append(Criterion("efficiency", 0.10, None, "efficiency not recorded"))
    else:
        if min_efficiency and efficiency < min_efficiency:
            score = max(0.0, 60.0 - (min_efficiency - efficiency) * 4.0)
            reason = f"below the required {min_efficiency}%"
        else:
            score = min(100.0, 40.0 + efficiency * 0.7)
            reason = "meets or exceeds the efficiency requirement"
        criteria.append(
            Criterion("efficiency", 0.10, round(score, 2), reason, efficiency, min_efficiency)
        )

    card_criteria = criteria
    disq, disq_reasons = _score_hard_requirements(record, profile, card_criteria)
    disqualified = disqualified or disq
    reasons.extend(disq_reasons)

    card = _aggregate(ScorecardKind.TECHNICAL_FIT, card_criteria)
    card.disqualified = disqualified
    card.disqualification_reason = "; ".join(reasons) or None
    return card


def _score_hard_requirements(
    record: dict[str, Any], profile: dict[str, Any], criteria: list[Criterion]
) -> tuple[bool, list[str]]:
    """Standard, area classification, certifications and sour service.

    These are pass/fail gates in a real tender, so a mismatch disqualifies rather than
    just scoring low. Appends to ``criteria`` in place.
    """
    disqualified = False
    reasons: list[str] = []

    required_standard = profile.get("required_standard")
    actual_standard = record.get("applicable_standard")
    if required_standard:
        if not actual_standard:
            criteria.append(Criterion("standard", 0.12, None, "standard not recorded"))
        elif str(actual_standard) == str(required_standard):
            criteria.append(
                Criterion(
                    "standard",
                    0.12,
                    100.0,
                    f"complies with {required_standard}",
                    actual_standard,
                    required_standard,
                )
            )
        elif {str(actual_standard), str(required_standard)} == {"api_610", "iso_13709"}:
            # ISO 13709 is the ISO adoption of API 610; treating them as different
            # would disqualify half the European vendor base for no engineering reason.
            criteria.append(
                Criterion(
                    "standard",
                    0.12,
                    95.0,
                    "API 610 and ISO 13709 are technically equivalent",
                    actual_standard,
                    required_standard,
                )
            )
        else:
            disqualified = True
            reasons.append(
                f"declared standard {actual_standard} does not meet required {required_standard}"
            )
            criteria.append(
                Criterion(
                    "standard", 0.12, 0.0, "standard mismatch", actual_standard, required_standard
                )
            )
    else:
        criteria.append(
            Criterion(
                "standard",
                0.12,
                80.0 if actual_standard else None,
                "no standard required by the profile",
                actual_standard,
            )
        )

    required_area = profile.get("required_area_classification")
    actual_area = record.get("area_classification")
    if required_area:
        matches = str(actual_area or "") == str(required_area)
        score = 100.0 if matches else (None if not actual_area else 20.0)
        criteria.append(
            Criterion(
                "area_classification",
                0.08,
                score,
                "matches required zone" if matches else "does not match required zone",
                actual_area,
                required_area,
            )
        )
    else:
        criteria.append(
            Criterion(
                "area_classification",
                0.08,
                80.0 if actual_area else None,
                "no zone requirement stated",
                actual_area,
            )
        )

    required_certs = [str(c) for c in (profile.get("required_certifications") or [])]
    held_certs = {str(c).lower() for c in (record.get("certifications") or [])}
    if required_certs:
        matched = [c for c in required_certs if c.lower() in held_certs]
        ratio = len(matched) / len(required_certs)
        criteria.append(
            Criterion(
                "certifications",
                0.07,
                round(ratio * 100.0, 2),
                f"{len(matched)} of {len(required_certs)} required certifications evidenced",
                sorted(held_certs),
                required_certs,
            )
        )
        if ratio == 0:
            reasons.append("none of the required certifications are evidenced")
    else:
        criteria.append(
            Criterion(
                "certifications",
                0.07,
                75.0 if held_certs else None,
                "no certifications required",
                sorted(held_certs),
            )
        )

    if profile.get("nace_required"):
        nace = record.get("nace_mr0175_compliant")
        if nace is None:
            criteria.append(Criterion("nace_compliance", 0.05, None, "NACE status unknown"))
        elif nace:
            criteria.append(Criterion("nace_compliance", 0.05, 100.0, "NACE MR0175 compliant"))
        else:
            disqualified = True
            reasons.append("NACE MR0175 is required but the pump is not compliant")
            criteria.append(Criterion("nace_compliance", 0.05, 0.0, "not NACE compliant"))

    return disqualified, reasons


def score_commercial_fit(record: dict[str, Any], profile: dict[str, Any]) -> Scorecard:
    """Price against budget and benchmark, plus terms, warranty and life-cycle cost."""
    criteria: list[Criterion] = []
    disqualified = False
    reasons: list[str] = []

    price = _num(record.get("base_price_usd")) or _num(record.get("base_price_amount"))
    budget = _num(profile.get("max_budget_usd"))
    if price is None:
        criteria.append(
            Criterion("price", 0.32, None, "no price on record - cannot be scored on cost")
        )
    elif budget is None:
        criteria.append(Criterion("price", 0.32, 70.0, "price known, no budget stated", price))
    else:
        if price > budget:
            reasons.append(f"price {price:,.0f} USD exceeds the budget {budget:,.0f} USD")
        criteria.append(
            Criterion(
                "price",
                0.32,
                round(_lower_is_better(price, budget), 2),
                "scored against budget",
                price,
                budget,
            )
        )

    benchmark = _num(record.get("historical_price_benchmark_usd"))
    if price is not None and benchmark:
        variance = (price - benchmark) / benchmark * 100.0
        score = max(0.0, min(100.0, 70.0 - variance * 1.5))
        criteria.append(
            Criterion(
                "price_vs_benchmark",
                0.14,
                round(score, 2),
                f"{variance:+.1f}% against benchmark",
                price,
                benchmark,
            )
        )
    else:
        criteria.append(
            Criterion("price_vs_benchmark", 0.14, None, "no historical benchmark available")
        )

    lifecycle = _num(record.get("lifecycle_cost_usd"))
    if lifecycle and price:
        # A low purchase price with a high life-cycle cost is the classic pump trap.
        multiple = lifecycle / price
        score = 100.0 if multiple <= 2 else max(0.0, 100.0 - (multiple - 2) * 12.0)
        criteria.append(
            Criterion(
                "lifecycle_cost",
                0.16,
                round(score, 2),
                f"life-cycle cost is {multiple:.1f}x the purchase price",
                lifecycle,
                price,
            )
        )
    else:
        criteria.append(Criterion("lifecycle_cost", 0.16, None, "life-cycle cost not estimated"))

    warranty = _num(record.get("warranty_months"))
    if warranty is None:
        criteria.append(Criterion("warranty", 0.12, None, "warranty not stated"))
    else:
        # 12 months is the market floor, 24 the common ask, 36+ excellent.
        score = min(100.0, max(0.0, (warranty - 6) / 30.0 * 100.0))
        criteria.append(
            Criterion("warranty", 0.12, round(score, 2), f"{warranty:.0f} months", warranty, 24)
        )

    payment_terms = record.get("payment_terms")
    advance = _num(record.get("advance_payment_pct"))
    if payment_terms or advance is not None:
        # Less cash up front is better for the buyer.
        score = 70.0 if advance is None else max(0.0, 100.0 - advance * 2.0)
        criteria.append(
            Criterion(
                "payment_terms",
                0.12,
                round(score, 2),
                f"{advance:.0f}% advance payment"
                if advance is not None
                else "terms stated, advance share unknown",
                advance,
            )
        )
    else:
        criteria.append(Criterion("payment_terms", 0.12, None, "payment terms not stated"))

    local_content = _num(record.get("local_content_pct"))
    minimum_local = _num(profile.get("local_content_min_pct"))
    if minimum_local:
        if local_content is None:
            criteria.append(Criterion("local_content", 0.14, None, "local content not declared"))
        elif local_content < minimum_local:
            disqualified = True
            reasons.append(
                f"local content {local_content:.0f}% is below the mandated {minimum_local:.0f}%"
            )
            criteria.append(
                Criterion(
                    "local_content",
                    0.14,
                    0.0,
                    "below mandated local content",
                    local_content,
                    minimum_local,
                )
            )
        else:
            criteria.append(
                Criterion(
                    "local_content",
                    0.14,
                    100.0,
                    "meets local content requirement",
                    local_content,
                    minimum_local,
                )
            )

    card = _aggregate(ScorecardKind.COMMERCIAL_FIT, criteria)
    card.disqualified = disqualified
    card.disqualification_reason = "; ".join(reasons) or None
    return card


def score_delivery_risk(record: dict[str, Any], profile: dict[str, Any]) -> Scorecard:
    """Higher score = lower risk. Schedule is usually what kills an offshore project."""
    criteria: list[Criterion] = []
    disqualified = False
    reasons: list[str] = []

    lead_time = _num(record.get("standard_lead_time_weeks"))
    required_by = _num(profile.get("max_lead_time_weeks"))
    if lead_time is None:
        criteria.append(Criterion("lead_time", 0.30, None, "lead time not stated"))
    elif required_by is None:
        score = max(0.0, 100.0 - max(0.0, lead_time - 20.0) * 1.5)
        criteria.append(
            Criterion(
                "lead_time",
                0.30,
                round(score, 2),
                f"{lead_time:.0f} weeks, no deadline stated",
                lead_time,
            )
        )
    elif lead_time > required_by:
        disqualified = True
        reasons.append(
            f"lead time {lead_time:.0f} weeks misses the required {required_by:.0f} weeks"
        )
        criteria.append(
            Criterion("lead_time", 0.30, 0.0, "misses the required date", lead_time, required_by)
        )
    else:
        criteria.append(
            Criterion(
                "lead_time",
                0.30,
                round(_lower_is_better(lead_time, required_by), 2),
                "meets the required date",
                lead_time,
                required_by,
            )
        )

    otd = _num(record.get("historical_on_time_delivery_pct"))
    if otd is None:
        criteria.append(Criterion("on_time_delivery", 0.22, None, "no on-time delivery history"))
    else:
        # Stored as a 0-1 ratio; accept a percentage too.
        ratio = otd if otd <= 1 else otd / 100.0
        sample = _num(record.get("otd_sample_size"))
        confidence_penalty = 0.0 if (sample or 0) >= 10 else 12.0
        criteria.append(
            Criterion(
                "on_time_delivery",
                0.22,
                round(max(0.0, ratio * 100.0 - confidence_penalty), 2),
                f"{ratio * 100:.0f}% on time"
                + (f" over {sample:.0f} orders" if sample else " (small sample)"),
                ratio,
            )
        )

    long_lead = record.get("long_lead_components") or {}
    single_source = record.get("single_source_components") or []
    if long_lead or single_source:
        penalty = min(60.0, len(long_lead) * 10.0 + len(single_source) * 15.0)
        criteria.append(
            Criterion(
                "supply_chain_exposure",
                0.18,
                round(100.0 - penalty, 2),
                f"{len(long_lead)} long-lead items, {len(single_source)} single-source items",
                {"long_lead": list(long_lead), "single_source": single_source},
            )
        )
    else:
        criteria.append(
            Criterion(
                "supply_chain_exposure",
                0.18,
                None,
                "long-lead and single-source exposure not documented",
            )
        )

    excluded = {str(c).upper() for c in (profile.get("excluded_countries") or [])}
    origin = str(record.get("country_of_origin") or "").upper()
    if excluded and origin:
        if origin in excluded:
            disqualified = True
            reasons.append(f"country of origin {origin} is excluded by the profile")
            criteria.append(
                Criterion(
                    "origin", 0.15, 0.0, "excluded country of origin", origin, sorted(excluded)
                )
            )
        else:
            criteria.append(Criterion("origin", 0.15, 100.0, "acceptable origin", origin))
    else:
        criteria.append(
            Criterion(
                "origin",
                0.15,
                80.0 if origin else None,
                "origin recorded" if origin else "country of origin unknown",
                origin,
            )
        )

    if record.get("export_licence_required"):
        weeks = _num(record.get("export_licence_lead_time_weeks")) or 8.0
        criteria.append(
            Criterion(
                "export_control",
                0.15,
                round(max(0.0, 80.0 - weeks * 3.0), 2),
                f"export licence required, about {weeks:.0f} weeks",
                weeks,
            )
        )
    else:
        criteria.append(
            Criterion(
                "export_control",
                0.15,
                90.0 if record.get("export_licence_required") is False else None,
                "no export licence required"
                if record.get("export_licence_required") is False
                else "export control status unknown",
            )
        )

    fat_weeks = _num(record.get("fat_lead_time_weeks"))
    if fat_weeks is not None and lead_time is not None and fat_weeks > lead_time:
        criteria.append(
            Criterion(
                "fat_schedule",
                0.10,
                20.0,
                "FAT readiness is later than the quoted delivery",
                fat_weeks,
                lead_time,
            )
        )
    elif fat_weeks is not None:
        criteria.append(
            Criterion("fat_schedule", 0.10, 85.0, "FAT fits inside the delivery window", fat_weeks)
        )

    card = _aggregate(ScorecardKind.DELIVERY_RISK, criteria)
    card.disqualified = disqualified
    card.disqualification_reason = "; ".join(reasons) or None
    return card


def score_data_confidence(record: dict[str, Any], tracked_fields: list[str]) -> Scorecard:
    """How much the other three scores can be trusted.

    This is the scorecard that keeps the platform honest: a beautifully ranked candidate
    with a data-confidence grade of E is a research task, not a recommendation.
    """
    criteria: list[Criterion] = []

    populated = [f for f in tracked_fields if record.get(f) not in (None, "", [], {})]
    completeness = (len(populated) / len(tracked_fields) * 100.0) if tracked_fields else 0.0
    criteria.append(
        Criterion(
            "completeness",
            0.40,
            round(completeness, 2),
            f"{len(populated)} of {len(tracked_fields)} tracked fields populated",
            len(populated),
            len(tracked_fields),
        )
    )

    level = str(record.get("confidence_level") or ConfidenceLevel.UNKNOWN.value)
    criteria.append(
        Criterion(
            "source_confidence",
            0.25,
            CONFIDENCE_WEIGHT.get(level, 10.0),
            f"record confidence level is {level}",
            level,
        )
    )

    status = str(record.get("verification_status") or VerificationStatus.UNVERIFIED.value)
    criteria.append(
        Criterion(
            "verification",
            0.20,
            VERIFICATION_WEIGHT.get(status, 40.0),
            f"verification status is {status}",
            status,
        )
    )

    open_flags = _num(record.get("open_flag_count")) or 0.0
    criteria.append(
        Criterion(
            "open_quality_flags",
            0.15,
            max(0.0, 100.0 - open_flags * 15.0),
            f"{open_flags:.0f} unresolved data quality flags",
            open_flags,
        )
    )

    return _aggregate(ScorecardKind.DATA_CONFIDENCE, criteria)


DEFAULT_WEIGHTS = {
    "technical": 0.40,
    "commercial": 0.25,
    "delivery": 0.20,
    "data_confidence": 0.15,
}


def score_all(
    record: dict[str, Any],
    profile: dict[str, Any] | None = None,
    tracked_fields: list[str] | None = None,
) -> dict[str, Scorecard]:
    """Produce all four scorecards plus a weighted overall score."""
    profile = profile or {}
    tracked = tracked_fields or _default_tracked_fields()

    cards = {
        "technical": score_technical_fit(record, profile),
        "commercial": score_commercial_fit(record, profile),
        "delivery": score_delivery_risk(record, profile),
        "data_confidence": score_data_confidence(record, tracked),
    }

    weights = {
        "technical": _num(profile.get("weight_technical")) or DEFAULT_WEIGHTS["technical"],
        "commercial": _num(profile.get("weight_commercial")) or DEFAULT_WEIGHTS["commercial"],
        "delivery": _num(profile.get("weight_delivery")) or DEFAULT_WEIGHTS["delivery"],
        "data_confidence": (
            _num(profile.get("weight_data_confidence")) or DEFAULT_WEIGHTS["data_confidence"]
        ),
    }
    total_weight = sum(weights.values()) or 1.0
    overall_criteria = [
        Criterion(
            name, weights[name] / total_weight, card.score, f"{name} scorecard grade {card.grade}"
        )
        for name, card in cards.items()
    ]
    overall = _aggregate(ScorecardKind.OVERALL, overall_criteria)
    overall.disqualified = any(card.disqualified for card in cards.values())
    overall.disqualification_reason = (
        "; ".join(
            card.disqualification_reason for card in cards.values() if card.disqualification_reason
        )
        or None
    )
    if overall.disqualified:
        # A disqualified candidate must not out-rank a compliant one on points.
        overall.score = 0.0
    cards["overall"] = overall
    return cards


def _default_tracked_fields() -> list[str]:
    """The fields data-confidence is measured against, drawn from the prompt registry."""
    from app.ai.prompts import FIELD_GROUPS

    seen: list[str] = []
    for group, fields in FIELD_GROUPS.items():
        if group == "identity":
            continue
        seen.extend(fields)
    return sorted(set(seen))
