"""Scorecards drive procurement decisions, so the failure modes that matter are:
missing data scoring as good data, and a disqualified candidate out-ranking a compliant one.
"""

from app.services import scoring

PROFILE = {
    "required_capacity_m3h": 300,
    "required_head_m": 140,
    "max_npshr_m": 5.0,
    "min_efficiency_pct": 70,
    "required_standard": "api_610",
    "required_area_classification": "zone_1",
    "required_certifications": ["ATEX", "DNV"],
    "nace_required": True,
    "max_lead_time_weeks": 30,
    "max_budget_usd": 400_000,
    "excluded_countries": ["IR", "RU"],
}

GOOD = {
    "rated_capacity_m3h": 305,
    "rated_head_m": 138,
    "npsh_required_m": 3.2,
    "hydraulic_efficiency_pct": 78,
    "applicable_standard": "api_610",
    "area_classification": "zone_1",
    "certifications": ["atex", "dnv", "iso 9001"],
    "nace_mr0175_compliant": True,
    "base_price_usd": 310_000,
    "historical_price_benchmark_usd": 330_000,
    "lifecycle_cost_usd": 560_000,
    "warranty_months": 24,
    "advance_payment_pct": 20,
    "standard_lead_time_weeks": 26,
    "historical_on_time_delivery_pct": 0.94,
    "otd_sample_size": 18,
    "country_of_origin": "NO",
    "export_licence_required": False,
    "confidence_level": "verified",
    "verification_status": "verified",
    "open_flag_count": 0,
}


def test_good_candidate_scores_well_and_is_not_disqualified():
    cards = scoring.score_all(GOOD, PROFILE, tracked_fields=list(GOOD))
    assert not cards["overall"].disqualified
    assert cards["technical"].score > 80
    assert cards["commercial"].score > 55
    assert cards["delivery"].score > 70
    assert cards["overall"].grade in {"A", "B"}


def test_missing_data_is_not_scored_as_good_data():
    sparse = {"rated_capacity_m3h": 305, "applicable_standard": "api_610"}
    cards = scoring.score_all(sparse, PROFILE, tracked_fields=list(GOOD))
    technical = cards["technical"]
    assert technical.fields_missing > technical.fields_evaluated
    # Data confidence must collapse, which is the honest signal to the buyer.
    assert cards["data_confidence"].score < 40
    assert cards["data_confidence"].grade == "E"


def test_no_price_means_no_price_score_not_a_zero_or_a_pass():
    no_price = {k: v for k, v in GOOD.items() if k != "base_price_usd"}
    card = scoring.score_commercial_fit(no_price, PROFILE)
    price_criterion = next(c for c in card.criteria if c.name == "price")
    assert price_criterion.score is None
    assert "cannot be scored" in price_criterion.reason


def test_npshr_above_available_disqualifies():
    record = dict(GOOD, npsh_required_m=7.5)
    card = scoring.score_technical_fit(record, PROFILE)
    assert card.disqualified
    assert "NPSHr" in card.disqualification_reason


def test_wrong_standard_disqualifies():
    card = scoring.score_technical_fit(dict(GOOD, applicable_standard="asme_b73_1"), PROFILE)
    assert card.disqualified


def test_iso_13709_accepted_where_api_610_required():
    card = scoring.score_technical_fit(dict(GOOD, applicable_standard="iso_13709"), PROFILE)
    assert not card.disqualified
    standard = next(c for c in card.criteria if c.name == "standard")
    assert standard.score == 95.0


def test_nace_non_compliance_disqualifies_for_sour_service():
    card = scoring.score_technical_fit(dict(GOOD, nace_mr0175_compliant=False), PROFILE)
    assert card.disqualified
    assert "NACE" in card.disqualification_reason


def test_late_delivery_disqualifies():
    card = scoring.score_delivery_risk(dict(GOOD, standard_lead_time_weeks=44), PROFILE)
    assert card.disqualified


def test_excluded_country_of_origin_disqualifies():
    card = scoring.score_delivery_risk(dict(GOOD, country_of_origin="RU"), PROFILE)
    assert card.disqualified


def test_disqualified_candidate_cannot_outrank_a_compliant_one():
    compliant = scoring.score_all(GOOD, PROFILE, tracked_fields=list(GOOD))
    # Cheaper and faster, but the wrong standard
    non_compliant = scoring.score_all(
        dict(
            GOOD,
            applicable_standard="asme_b73_1",
            base_price_usd=150_000,
            standard_lead_time_weeks=12,
        ),
        PROFILE,
        tracked_fields=list(GOOD),
    )
    assert non_compliant["overall"].disqualified
    assert non_compliant["overall"].score == 0.0
    assert compliant["overall"].score > non_compliant["overall"].score


def test_small_otd_sample_is_penalised():
    big = scoring.score_delivery_risk(dict(GOOD, otd_sample_size=50), PROFILE)
    small = scoring.score_delivery_risk(dict(GOOD, otd_sample_size=2), PROFILE)
    assert small.score < big.score


def test_high_lifecycle_cost_penalises_a_cheap_pump():
    cheap_but_costly = dict(GOOD, base_price_usd=200_000, lifecycle_cost_usd=1_400_000)
    card = scoring.score_commercial_fit(cheap_but_costly, PROFILE)
    lifecycle = next(c for c in card.criteria if c.name == "lifecycle_cost")
    assert lifecycle.score < 60


def test_breakdown_is_explainable():
    card = scoring.score_technical_fit(GOOD, PROFILE)
    breakdown = card.breakdown()
    assert "capacity" in breakdown
    assert set(breakdown["capacity"]) == {
        "score",
        "weight",
        "contribution",
        "value",
        "target",
        "reason",
    }


def test_weights_come_from_the_requirement_profile():
    commercial_heavy = dict(
        PROFILE,
        weight_technical=0.1,
        weight_commercial=0.7,
        weight_delivery=0.1,
        weight_data_confidence=0.1,
    )
    default_cards = scoring.score_all(GOOD, PROFILE, tracked_fields=list(GOOD))
    weighted_cards = scoring.score_all(GOOD, commercial_heavy, tracked_fields=list(GOOD))
    assert default_cards["overall"].score != weighted_cards["overall"].score


def test_grades_map_to_bands():
    assert scoring.Scorecard(scoring.ScorecardKind.OVERALL, 90).grade == "A"
    assert scoring.Scorecard(scoring.ScorecardKind.OVERALL, 72).grade == "B"
    assert scoring.Scorecard(scoring.ScorecardKind.OVERALL, 60).grade == "C"
    assert scoring.Scorecard(scoring.ScorecardKind.OVERALL, 45).grade == "D"
    assert scoring.Scorecard(scoring.ScorecardKind.OVERALL, 10).grade == "E"
