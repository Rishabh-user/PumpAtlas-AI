"""Scorecards drive procurement decisions, so the failure modes that matter are:
missing data scoring as good data, and a disqualified candidate out-ranking a compliant one.
"""

import pytest

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


class TestNothingToScoreIsNotAVerdict:
    """A card with no evidence must not read as a card with bad evidence.

    This was the live behaviour and it was actively misleading. A pump whose datasheet
    nobody had read scored 0.0 and graded E on commercial fit and delivery risk, which a
    buyer reads as "cheap rubbish that arrives late" rather than "nobody has looked".
    Only 4 of 160 models carry commercial specs, so this was the ordinary case.
    """

    # Duty data from a nameplate, and nothing commercial or logistical - the normal
    # state of a record that arrived without a datasheet.
    NAMEPLATE_ONLY = {
        "rated_capacity_m3h": 305,
        "rated_head_m": 138,
        "confidence_level": "ai_extracted",
        "verification_status": "unverified",
        "open_flag_count": 0,
    }

    def test_an_unscorable_card_has_no_score(self):
        cards = scoring.score_all(self.NAMEPLATE_ONLY, PROFILE, tracked_fields=list(GOOD))
        for name in ("commercial", "delivery"):
            card = cards[name]
            assert card.fields_evaluated == 0, name
            assert card.score is None, name
            assert card.scored is False, name

    def test_an_unscorable_card_has_no_grade(self):
        """Not 'E'. A caller showing a letter has to decide what to show instead."""
        cards = scoring.score_all(self.NAMEPLATE_ONLY, PROFILE, tracked_fields=list(GOOD))
        assert cards["commercial"].grade is None
        assert cards["delivery"].grade is None

    def test_a_card_with_one_evaluated_criterion_still_scores(self):
        """The absence has to be total; one fact is enough to have an opinion."""
        record = dict(self.NAMEPLATE_ONLY, warranty_months=24)
        card = scoring.score_commercial_fit(record, PROFILE)
        assert card.fields_evaluated == 1
        assert card.score is not None
        assert card.grade is not None

    def test_an_unscorable_card_does_not_vote_in_the_overall(self):
        """It contributes no opinion, rather than contributing a zero.

        Commercial and delivery carry 45% of the default weighting between them. Feeding
        them in as zeros made the overall score mostly a measure of what nobody had
        recorded yet.
        """
        cards = scoring.score_all(self.NAMEPLATE_ONLY, PROFILE, tracked_fields=list(GOOD))
        technical, confidence = cards["technical"].score, cards["data_confidence"].score
        expected = (0.40 * technical + 0.15 * confidence) / (0.40 + 0.15)
        assert cards["overall"].score == pytest.approx(expected, abs=0.05)

    def test_the_overall_says_which_cards_abstained(self):
        cards = scoring.score_all(self.NAMEPLATE_ONLY, PROFILE, tracked_fields=list(GOOD))
        reasons = {c.name: c.reason for c in cards["overall"].criteria}
        assert "not scored" in reasons["commercial"]
        assert "not scored" in reasons["delivery"]

    def test_an_abstaining_card_cannot_drag_the_overall_down(self):
        """The point of the change, stated as the comparison that motivated it."""
        sparse = scoring.score_all(self.NAMEPLATE_ONLY, PROFILE, tracked_fields=list(GOOD))
        # Same evidence, plus commercial and delivery facts that happen to score badly.
        with_bad_news = scoring.score_all(
            dict(
                self.NAMEPLATE_ONLY,
                base_price_usd=900_000,
                warranty_months=1,
                standard_lead_time_weeks=29,
                country_of_origin="NO",
            ),
            PROFILE,
            tracked_fields=list(GOOD),
        )
        assert with_bad_news["commercial"].score is not None
        # Knowing bad things must cost more than knowing nothing.
        assert with_bad_news["overall"].score < sparse["overall"].score

    def test_a_record_with_no_evidence_has_no_fit_scores(self):
        cards = scoring.score_all({}, {}, tracked_fields=[])
        assert cards["technical"].score is None
        assert cards["commercial"].score is None
        assert cards["delivery"].score is None

    def test_data_confidence_still_scores_an_empty_record(self):
        """Because "we know nothing" is itself a measurable finding, not an absence.

        Its four criteria always evaluate: an unknown confidence level scores 10, an
        unverified record 40, no open flags 100. That is a real statement about the
        evidence, unlike commercial fit, which has nothing to form an opinion from.
        """
        cards = scoring.score_all({}, {}, tracked_fields=[])
        assert cards["data_confidence"].score is not None
        assert cards["data_confidence"].grade == "E"

    def test_an_empty_record_cannot_produce_a_good_overall(self):
        """The overall then rests on data confidence alone, which is E by construction.

        So an unresearched record still reads as "do not rely on this" - it just gets
        there by saying the evidence is thin, rather than by inventing two bad verdicts.
        """
        cards = scoring.score_all({}, {}, tracked_fields=[])
        assert cards["overall"].score == pytest.approx(cards["data_confidence"].score)
        assert cards["overall"].grade == "E"

    def test_disqualification_still_forces_zero(self):
        """An unscored card is an absence; a disqualification is a finding. Different."""
        record = dict(GOOD, npsh_required_m=7.5)
        cards = scoring.score_all(record, PROFILE, tracked_fields=list(GOOD))
        assert cards["overall"].disqualified is True
        assert cards["overall"].score == 0.0


class TestScoresCrossTheStorageBoundary:
    """`Decimal(str(None))` raises, and `confidence_scores.score` is NOT NULL.

    Both were reachable the moment a card could return None, and neither was covered.
    """

    def test_a_score_converts_for_a_numeric_column(self):
        from app.services.comparison import _as_score

        assert _as_score(None) is None
        assert str(_as_score(72.5)) == "72.5"

    def test_ranking_places_unscored_below_scored_and_above_disqualified(self):
        candidates = [
            (type("I", (), {"disqualified": False})(), 60.0),
            (type("I", (), {"disqualified": False})(), None),
            (type("I", (), {"disqualified": True})(), 0.0),
            (type("I", (), {"disqualified": False})(), 80.0),
        ]
        ordered = sorted(
            candidates,
            key=lambda pair: (pair[0].disqualified, pair[1] is None, -(pair[1] or 0.0)),
        )
        assert [p[1] for p in ordered] == [80.0, 60.0, None, 0.0]
