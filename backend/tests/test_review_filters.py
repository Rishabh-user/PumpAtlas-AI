"""The review queue's filters: what they must never do.

A filter on a work queue has one job beyond narrowing - it must not lose anything. Two
faults here are silent rather than loud: a decision value that belongs to no filter
group leaves those candidates reachable only through "all", and a vendor state derived
twice (once for the badge, once for the WHERE clause) lets a filtered list show cards
that contradict the filter that selected them. Neither raises an error; both just quietly
hide a reviewer's work.

Everything here is source- and contract-level. The end-to-end behaviour needs a live
PostgreSQL and sits in ``test_live_integration.py``.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.api.v1 import ai_review
from app.models.enums import ReviewDecision
from app.schemas.ai import ReviewQueueItem


class TestNoDecisionIsUnreachable:
    def test_every_stored_decision_belongs_to_a_filter(self):
        """A decision the filters do not name is invisible except under "all".

        This is how ``accepted_with_edits`` went missing: the filter matched the enum
        exactly, so a candidate a reviewer had corrected and promoted appeared under no
        decision at all. Adding a value to :class:`ReviewDecision` without adding it
        here should fail loudly rather than hide records.
        """
        grouped = {value for values in ai_review.DECISION_GROUPS.values() for value in values}
        missing = sorted({decision.value for decision in ReviewDecision} - grouped)
        assert not missing, f"decisions no filter selects: {missing}"

    def test_accepting_with_edits_still_counts_as_accepted(self):
        """Correcting a value before promoting it is still acceptance."""
        assert set(ai_review.DECISION_GROUPS["accepted"]) == {
            ReviewDecision.ACCEPTED.value,
            ReviewDecision.ACCEPTED_WITH_EDITS.value,
        }

    def test_the_groups_do_not_overlap(self):
        """Otherwise two filters would both claim the same candidate."""
        seen: set[str] = set()
        for name, values in ai_review.DECISION_GROUPS.items():
            clash = seen & set(values)
            assert not clash, f"{name} re-claims {sorted(clash)}"
            seen.update(values)

    def test_an_unknown_decision_is_refused_not_ignored(self):
        """Silently returning the default would misreport what the list contains."""
        source = inspect.getsource(ai_review._decision_clause)
        assert "HTTP_422" in source
        assert "Unknown decision" in source


class TestVendorMatchIsDerivedOnce:
    def test_the_three_states_are_the_ones_the_card_shows(self):
        assert ai_review.VENDOR_MATCH_STATES == ("matched", "new", "missing")

    def test_the_state_travels_with_the_candidate(self):
        """The browser must not have to re-derive it.

        The filter selects on the state, so a separately computed badge could disagree
        with the filter that produced the list.
        """
        assert "vendor_match" in ReviewQueueItem.model_fields

    def test_the_filter_and_the_badge_use_one_definition(self):
        """`_matched_vendor_subquery` decides both, so they cannot drift apart."""
        listing = inspect.getsource(ai_review.review_queue)
        assert "_matched_vendor_subquery()" in listing
        assert "_vendor_match_clause(" in listing
        clause = inspect.getsource(ai_review._vendor_match_clause)
        assert "_matched_vendor_subquery()" in clause

    def test_an_unknown_state_is_refused(self):
        source = inspect.getsource(ai_review.review_queue)
        assert "Unknown vendor_match value" in source

    @pytest.mark.parametrize("state", ["matched", "new", "missing"])
    def test_each_state_has_a_clause(self, state):
        assert f'"{state}"' in inspect.getsource(ai_review._vendor_match_clause)


class TestTheListDoesNotQueryPerRow:
    """The queue renders 25 cards against a hosted database.

    Resolving each card's vendor match with its own query cost 25 round trips and took
    six seconds to open the screen - the same fault the discovery poll had.
    """

    def test_the_row_loop_touches_no_session(self):
        tree = ast.parse(pathlib.Path(ai_review.__file__).read_text(encoding="utf-8"))
        handler = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "review_queue"
        )
        loops = [node for node in ast.walk(handler) if isinstance(node, ast.For)]
        assert loops, "expected a loop building the response items"
        for loop in loops:
            calls = [
                ast.unparse(node.func)
                for node in ast.walk(loop)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "db"
            ]
            assert not calls, f"review_queue queries once per row: {calls}"

    def test_the_match_is_a_correlated_column(self):
        source = inspect.getsource(ai_review._matched_vendor_subquery)
        assert "correlate(ExtractedEntity)" in source
        assert "scalar_subquery()" in source

    def test_the_match_uses_the_database_normaliser(self):
        """Not the Python mirror.

        ``pumpatlas_normalize_company_name`` applies ``unaccent`` and the Python copy
        does not, so an accented manufacturer resolved to a different key and was
        reported as new when it already existed. The stored ``normalized_name`` column
        is produced by the SQL function, so the SQL function is the correct comparison.
        """
        source = inspect.getsource(ai_review._matched_vendor_subquery)
        assert "func.pumpatlas_normalize_company_name" in source
        assert "promotion.normalize_company_name" not in source


class TestAFinishedCandidateSaysSo:
    """The queue can now be filtered by decision, so decided candidates reach the screen.

    They cannot be decided again - the API answers "Already promoted to pump_model ..." -
    so the card has to know it is finished and offer something else instead. That is only
    possible if the list tells it, which makes these fields part of the contract rather
    than incidental detail.
    """

    @pytest.mark.parametrize(
        "field",
        ["review_decision", "promoted_at", "target_type", "target_id", "reviewer_edits"],
    )
    def test_the_item_carries_what_the_card_needs(self, field):
        assert field in ReviewQueueItem.model_fields

    def test_a_promoted_candidate_is_refused_a_second_decision(self):
        """The guard the screen relies on, in the service that promotes."""
        from app.services import promotion

        source = inspect.getsource(promotion.promote_extracted_entity)
        assert "was already promoted" in source

    def test_a_promoted_candidate_cannot_be_reset(self):
        """Undoing a promotion is a correction to the record, not to the queue.

        So the card must offer "return to queue" only for decisions that wrote nothing -
        rejected and escalated.
        """
        source = inspect.getsource(ai_review.reset_candidate)
        assert "promoted_at is not None" in source
        assert "HTTP_409_CONFLICT" in source


class TestFieldPresenceFilterKeepsTheTotals:
    def test_a_missing_fields_key_is_not_lost_by_both_filters(self):
        """`NULL NOT IN (...)` and its negation are both NULL.

        Without the coalesce, a candidate whose payload has no "fields" key at all would
        match neither ``has_fields=true`` nor ``has_fields=false``, so the two counts
        would stop adding up to the total and the rows would be unreachable.
        """
        source = inspect.getsource(ai_review._has_fields_expr)
        assert "coalesce" in source

    def test_the_facets_and_the_list_ask_the_same_question(self):
        """A count that disagrees with the list it labels is worse than no count."""
        facets = inspect.getsource(ai_review.review_queue_facets)
        listing = inspect.getsource(ai_review.review_queue)
        for helper in ("_has_fields_expr", "_matched_vendor_subquery", "_decision_clause"):
            assert helper in facets, f"facets does not use {helper}"
            assert helper in listing, f"review_queue does not use {helper}"
