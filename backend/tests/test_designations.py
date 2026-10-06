"""A pump type is not a model designation.

The review queue offered four candidates on one screen, from four manufacturers:
"OH1" (Nebras), "OH1" (CME), "API 610 OH1" (LUBOR) and "OH1 B Series" (Amarinth). An
exact-match list caught the first two and let the other two through - "API 610 OH1" is
two category words rather than one, and "OH1 B Series" hides a real product name behind
a type code.

Storing any of the first three creates a record called "OH1" that says nothing about who
makes what. Storing the fourth as "OH1 B Series" makes a second record of Amarinth's B
Series, which then has to be found and merged away.
"""

from __future__ import annotations

import uuid

import pytest

from app.services import designations, promotion
from app.services.promotion import WeakSubjectError, normalize_model_code
from app.services.pump_discovery import blocked_reason


class TestTheFourCandidatesFromTheQueue:
    @pytest.mark.parametrize(
        "code",
        ["OH1", "API 610 OH1", "API 610 OH1 ISO5199 Single Stage End Suction Centrifugal Pump"],
    )
    def test_a_category_page_is_blocked(self, code):
        reason = blocked_reason({"vendor_name": "Nebras Pumps Co.", "model_code": code}, {})
        assert reason is not None
        assert "pump type" in reason

    def test_a_product_behind_a_type_code_is_not_blocked(self):
        """Amarinth's B Series is a product; OH1 is the configuration it is built in."""
        assert blocked_reason({"vendor_name": "Amarinth", "model_code": "OH1 B Series"}, {}) is None

    def test_and_it_is_stored_under_its_own_name(self):
        assert designations.product_name("OH1 B Series") == "B Series"

    def test_so_the_same_pump_from_two_pages_is_one_record(self):
        assert normalize_model_code("OH1 B Series") == normalize_model_code("B Series")


class TestWhatCountsAsNamingAProduct:
    @pytest.mark.parametrize(
        "code",
        ["OH1", "BB3", "VS4", "API 610", "ISO 5199", "BB3 multistage pumps", "API 610 pumps"],
    )
    def test_categories(self, code):
        assert designations.is_category_only(code) is True

    @pytest.mark.parametrize(
        "code",
        ["MSD", "KGSG 40-250", "B Series", "OH1-200", "3196 i-FRAME", "HPX 6x8-13"],
    )
    def test_products(self, code):
        assert designations.is_category_only(code) is False

    def test_a_designation_nobody_recognises_is_left_alone(self):
        """Conservative on purpose: an unknown word is a name until proven otherwise."""
        assert designations.product_name("Zylem QX-99") == "Zylem QX-99"

    def test_a_type_code_inside_a_name_is_part_of_the_name(self):
        """"OH1-200" is one word, and one word is not the OH1 category."""
        assert designations.product_name("OH1-200") == "OH1-200"
        assert designations.classify("OH1-200").pump_type is None

    def test_series_belongs_to_the_name_it_follows(self):
        """Dropping it leaves "B", which is not a name and would be refused."""
        assert designations.product_name("B Series") == "B Series"

    def test_but_not_when_nothing_has_been_named(self):
        assert designations.is_category_only("Single Stage End Suction Centrifugal Pump")

    def test_a_trailing_noun_is_never_part_of_the_name(self):
        assert designations.product_name("KGSG 40-250 pumps") == "KGSG 40-250"

    def test_an_empty_code_is_a_missing_value_not_a_category(self):
        """`blocked_reason` has a better sentence for nothing at all."""
        assert designations.is_category_only("") is False
        assert designations.is_category_only(None) is False


class TestTheTypeIsKeptAsAFactAboutThePump:
    def test_the_configuration_is_recognised(self):
        assert designations.classify("OH1 B Series").pump_type == "centrifugal_oh1"
        assert designations.classify("BB3 MSD").pump_type == "between_bearings_bb3"

    def test_the_standard_is_recognised_across_two_words(self):
        assert designations.classify("API 610 B Series").applicable_standard == "api_610"
        assert designations.classify("ISO 5199 KGSG").applicable_standard == "iso_5199"

    def test_a_code_with_no_enum_member_claims_nothing(self):
        """OH4, VS2, VS3, VS5 and VS7 have no `PumpType`; inventing one would be worse."""
        assert designations.classify("OH4 Something").pump_type is None
        assert designations.classify("OH4 Something").api_610_type_code == "OH4"

    def test_every_mapped_value_exists_in_the_enum(self):
        from app.models.enums import ApplicableStandard, PumpType

        types = {member.value for member in PumpType}
        standards = {member.value for member in ApplicableStandard}
        assert set(designations.PUMP_TYPE_FOR_CODE.values()) <= types
        assert set(designations.STANDARD_FOR_CODE.values()) <= standards


class _Entity:
    """The shape `promote_extracted_entity` reads before it touches the database."""

    def __init__(self, subject, fields=None):
        self.id = uuid.uuid4()
        self.promoted_at = None
        self.tenant_id = None
        self.payload = {"subject": subject, "fields": fields or {}}
        self.evidence_spans = {}
        self.field_confidences = {}
        self.confidence_level = None
        self.overall_confidence = None
        self.source_id = None
        self.ai_job_id = None
        self.ai_job = None


class TestStoringOneIsRefusedNotJustWarnedAbout:
    """`blocked_reason` tells a reviewer before the click. This stops the click.

    It also stops a sweep storing one with nobody watching, which is how three of these
    reached the queue in the first place.
    """

    @pytest.mark.parametrize("code", ["OH1", "API 610 OH1", "BB3 multistage pumps"])
    def test_a_category_candidate_cannot_be_promoted(self, code):
        with pytest.raises(WeakSubjectError) as caught:
            promotion.promote_extracted_entity(
                None, _Entity({"vendor_name": "Nebras Pumps Co.", "model_code": code})
            )
        assert "category rather than a product" in str(caught.value)

    def test_it_is_refused_before_anything_is_written(self):
        """`db` is None here: reaching the database at all would raise AttributeError."""
        with pytest.raises(WeakSubjectError):
            promotion.promote_extracted_entity(
                None, _Entity({"vendor_name": "Nebras Pumps Co.", "model_code": "OH1"})
            )

    def test_a_reviewer_who_supplies_the_real_code_is_not_blocked(self):
        """The correction has to be the thing that unblocks it, or the queue is a wall."""
        with pytest.raises(AttributeError):
            # Past the gate, into `resolve_vendor`, which needs a real session.
            promotion.promote_extracted_entity(
                None,
                _Entity({"vendor_name": "Nebras Pumps Co.", "model_code": "OH1"}),
                reviewer_edits={"model_code": "NP-3196"},
            )


class TestAReviewersCorrectionOutranksTheExtraction:
    """It did not. The subject was read first and only fell back to the edited fields,
    so correcting a manufacturer or a model code in the review screen changed nothing and
    the record was written with the value the reviewer had just rejected."""

    def test_the_edited_model_code_is_the_one_used(self):
        with pytest.raises(AttributeError):
            promotion.promote_extracted_entity(
                None,
                _Entity({"vendor_name": "Nebras", "model_code": "OH1"}),
                reviewer_edits={"model_code": "NP-3196"},
            )

    def test_the_source_reads_the_edit_first(self):
        import inspect

        source = inspect.getsource(promotion.promote_extracted_entity)
        assert 'edits.get("model_code") or subject.get("model_code")' in source
        assert 'edits.get("vendor_name") or subject.get("vendor_name")' in source
        assert 'edits.get("pump_name") or fields.get("pump_name")' in source


class TestTheNameIsCutOutNotRebuilt:
    """Rebuilding a designation from its words rewrites the punctuation inside it.

    Joining the surviving words with spaces turned Inno Pumps' "EAP/EAPK series" into
    "EAP EAPK series" and Sulzer's "BBS, CD" into "BBS CD" - both already stored under
    those names. The separators in a model code are part of it, so the name is taken as
    a span of the original text.
    """

    @pytest.mark.parametrize(
        "code", ["EAP/EAPK series", "BBS, CD", "PWI-BB", "KGSG 40-250", "3196 i-FRAME"]
    )
    def test_a_designation_with_no_category_words_is_returned_verbatim(self, code):
        assert designations.product_name(code) == code

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("LMV 311 OH6", "LMV 311"),
            ("BP API 610 BB5", "BP"),
            ("PWI-BB OH3", "PWI-BB"),
            ("OH1 B Series", "B Series"),
        ],
    )
    def test_a_type_code_at_either_end_comes_off(self, code, expected):
        assert designations.product_name(code) == expected

    @pytest.mark.parametrize(
        ("code", "expected"),
        [("HZC (OH2)", "HZC"), ("ETL (close coupled OH5)", "ETL")],
    )
    def test_a_parenthesised_type_is_dropped_whole(self, code, expected):
        """Taking only the code out of "(close coupled OH5)" leaves an open bracket."""
        assert designations.product_name(code) == expected

    def test_a_bracket_without_a_type_code_is_left_alone(self):
        placeholder = "Dynapro Pumps Company unspecified line (unspecified variant)"
        assert designations.product_name(placeholder) == placeholder


class TestACategoryPageNeverBecomesACandidate:
    """The queue was filling with candidates nobody could ever store.

    Blocking them was only half the fix: a blocked candidate still occupies a row, is
    read, and is clicked on before the reason is noticed. The screening question Gemma
    answers is "is this page about a pump model?", and for a manufacturer's category page
    - "API 610 VS6 Vertical Suspended Pumps" - the honest answer is yes. A rule catches
    what a prompt cannot.
    """

    @pytest.mark.parametrize(
        "code",
        ["OH1", "VS6", "API 610 OH1", "BB3 multistage pumps", "API 675"],
    )
    def test_the_page_is_ruled_out_before_a_candidate_exists(self, code):
        from app.services.pump_discovery import KIND

        assert KIND.off_subject is not None
        assert KIND.off_subject({"model_code": code}, {}) is not None

    @pytest.mark.parametrize("code", ["OH1 B Series", "LMV 311 OH6", "KGSG 40-250", "MSD"])
    def test_a_real_product_still_reaches_the_queue(self, code):
        from app.services.pump_discovery import KIND

        assert KIND.off_subject({"model_code": code}, {}) is None

    def test_a_page_with_no_designation_still_reaches_the_queue(self):
        """A reviewer can type in a model code; nobody can invent a product."""
        from app.services.pump_discovery import KIND

        assert KIND.off_subject({}, {}) is None

    def test_the_reason_says_what_is_wrong_with_the_page(self):
        from app.services.pump_discovery import category_page_reason

        reason = category_page_reason("VS6")
        assert "pump type" in reason
        assert "category" in reason

    def test_the_vendor_kind_has_no_such_rule(self):
        """A vendor page about a category of pump is still a page about a supplier."""
        from app.services.vendor_discovery import KIND

        assert KIND.off_subject is None


class TestAClassificationCannotContradictTheDesignation:
    """One LUBOR candidate was titled "API 610 VS6 Vertical Suspended Pump" and came back
    classified OH6 - overhung, the opposite arrangement to vertically suspended.

    Both cannot be true. The designation is the manufacturer's own word for the product;
    the classification is the reading model's opinion of it, so the opinion is refused
    and the type is derived from the designation instead, with the designation as its
    evidence.
    """

    def test_the_refusal_is_in_the_write_path(self):
        import inspect

        source = inspect.getsource(promotion.promote_extracted_entity)
        assert "contradicts the designation" in source
        assert 'fields.get("pump_type")' in source

    def test_the_two_codes_really_do_disagree(self):
        """VS6 is vertically suspended; OH6 is overhung. Not a spelling difference."""
        assert designations.classify("VS6 Something").pump_type == "vertically_suspended_vs6"
        assert designations.classify("OH6 Something").pump_type == "centrifugal_oh6"


class TestAnEnrichmentRunFillsTheRecordItStartedFrom:
    """Resolving by name instead would leave the record the user was looking at empty.

    A datasheet page writes the designation its own way - "HZC-200" for the model
    recorded as "HZC", "B Series" for "OH1 B Series". Resolved by name, that creates a
    second model beside the one the run was started from, and the profile the person is
    watching stays exactly as empty as before.
    """

    def test_the_run_records_which_model_it_exists_to_fill(self):
        import inspect

        from app.services import discovery

        source = inspect.getsource(discovery.start_run)
        assert "target_pump_model_id" in source
        assert 'config["target_pump_model_id"]' in source

    def test_the_target_is_read_from_the_run_not_the_candidate(self):
        """The candidate is produced by reading a page and knows nothing about why."""
        import inspect

        from app.services import pump_discovery

        source = inspect.getsource(pump_discovery._target_model)
        assert "discovery_batch_id" in source
        assert "target_pump_model_id" in source

    def test_a_target_in_another_tenancy_is_refused(self):
        """A run must not write across a tenancy, whatever its config says."""
        import inspect

        from app.services import pump_discovery

        source = inspect.getsource(pump_discovery._target_model)
        assert "tenant_id != entity.tenant_id" in source

    def test_the_write_path_uses_the_target_instead_of_resolving_by_name(self):
        import inspect

        source = inspect.getsource(promotion.promote_extracted_entity)
        assert "if target_pump_model is not None:" in source
        assert "pump_model = target_pump_model" in source

    def test_an_untargeted_run_still_resolves_by_name(self):
        """The review queue stores candidates that belong to no particular record."""
        import inspect

        source = inspect.getsource(promotion.promote_extracted_entity)
        assert "resolve_pump_model(" in source


class TestAPlaceholderIsAskedADifferentQuestion:
    """A record with no designation has no datasheet to look for.

    The first enrichment run against "Bornerman unspecified line (unspecified variant)"
    searched the web for that phrase, read two pages, found nothing and reported that the
    record could not be filled. The record was never a product: `resolve_pump_model`
    invented the name so the vendor had somewhere to hang.
    """

    @pytest.mark.parametrize(
        "code",
        [
            "Bornerman unspecified line (unspecified variant)",
            "Amarinth unspecified line",
            "LUBOR PUMP unspecified line (unspecified variant)",
        ],
    )
    def test_an_invented_name_is_recognised(self, code):
        assert promotion.is_placeholder_designation(code) is True

    @pytest.mark.parametrize("code", ["B Series", "HZC", "KGSG 40-250", "LMV 311", ""])
    def test_a_real_designation_is_not(self, code):
        assert promotion.is_placeholder_designation(code) is False

    def test_the_templates_and_the_test_cannot_drift_apart(self):
        """Both are built from the same strings, so a reworded placeholder stays known."""
        assert promotion.is_placeholder_designation(
            promotion.UNSPECIFIED_LINE.format(vendor="Bornerman")
        )
        assert promotion.is_placeholder_designation(
            promotion.UNSPECIFIED_VARIANT.format(pump="Bornerman unspecified line")
        )

    def test_the_endpoint_asks_what_the_vendor_sells_instead(self):
        import inspect

        from app.api.v1 import pumps as pump_routes

        source = inspect.getsource(pump_routes.enrich_pump_model)
        assert "vendor_range_objective(vendor.name)" in source
        assert "pump_model_objective(vendor.name, designation)" in source

    def test_and_does_not_write_the_answers_onto_the_placeholder(self):
        """Forcing them on would name Bornerman's real pump after the row that stood in."""
        import inspect

        from app.api.v1 import pumps as pump_routes

        source = inspect.getsource(pump_routes.enrich_pump_model)
        assert "target_pump_model_id=None if placeholder else model.id" in source

    def test_the_range_objective_names_no_model(self):
        from app.ai.parallel_search import vendor_range_objective

        objective, queries = vendor_range_objective("Bornerman")
        assert "unspecified" not in objective.lower()
        assert all("unspecified" not in query.lower() for query in queries)
        assert "Bornerman" in objective
