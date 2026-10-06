"""The chat: grounded, cited, and unable to write a record on its own.

A chat over a system of record invites one specific failure - the model's prose becomes
data. That is the whole reason the answering path and the storing path are separate here,
and these tests pin that separation along with the grounding that makes an answer
checkable.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid

import pytest

from app.api.v1 import chat_routes
from app.schemas.specs import SPEC_FIELDS
from app.services import chat, discovery
from app.services import records as records_service
from app.services.chat import domain_signal


class TestAnsweringWritesNothing:
    def test_the_answer_path_issues_no_writes(self):
        """`chat.answer` reads the index and the web. It must not touch a table."""
        source = inspect.getsource(chat.answer)
        for forbidden in (
            "db.add(",
            "db.commit()",
            "db.flush()",
            "db.delete(",
            "promote_extracted_entity",
            "store_candidate",
        ):
            assert forbidden not in source, forbidden

    def test_the_service_imports_no_writer(self):
        """It uses `promotion` only for the name normaliser, not to store anything."""
        source = inspect.getsource(chat)
        assert "normalize_company_name" in source
        assert "promote_extracted_entity" not in source

    def test_only_capture_writes_and_it_uses_the_ordinary_pipeline(self):
        """Storing goes through discovery, so provenance cannot be bypassed."""
        source = inspect.getsource(chat_routes.capture)
        assert "discovery.start_run" in source
        assert "dispatch.dispatch" in source
        # Not a second write path.
        assert "promote_extracted_entity" not in source
        assert "provenance" not in source

    def test_asking_and_capturing_need_different_permissions(self):
        """One reads; the other spends money and writes rows."""
        module = pathlib.Path(chat_routes.__file__).read_text(encoding="utf-8")
        tree = ast.parse(module)
        needs: dict[str, str] = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                rendered = ast.unparse(decorator)
                if "require(" in rendered:
                    needs[node.name] = rendered
        assert "search" in needs.get("ask", "")
        assert "ingestion" in needs.get("capture", "")
        assert needs["ask"] != needs["capture"]


class TestTheAnswerIsGrounded:
    def test_the_prompt_forbids_inventing_figures(self):
        """The one failure mode that matters in procurement."""
        prompt = chat.SYSTEM_PROMPT
        assert "Never invent" in prompt
        for field in ("model code", "capacity", "price"):
            assert field in prompt

    def test_the_prompt_demands_a_citation_per_claim(self):
        assert "[R1]" in chat.SYSTEM_PROMPT and "[W2]" in chat.SYSTEM_PROMPT
        assert "unsupported" in chat.SYSTEM_PROMPT

    def test_the_prompt_separates_held_from_unverified(self):
        """An engineer has to know which half of an answer is ours."""
        assert "Authoritative" in chat.SYSTEM_PROMPT
        assert "Unverified" in chat.SYSTEM_PROMPT

    def test_records_and_web_get_distinct_markers(self):
        """So a citation can be resolved back to its source."""
        assert "[R{index}]" in inspect.getsource(chat._record_context)
        assert "[W{index}]" in inspect.getsource(chat._web_context)

    def test_context_is_bounded(self):
        """A page excerpt can be thousands of characters; the window is finite."""
        assert chat.MAX_RECORDS <= 20
        assert chat.MAX_WEB_RESULTS <= 10
        assert chat.MAX_EXCERPT_CHARS <= 10_000


class TestAQuestionCanMatchTheIndex:
    """`websearch_to_tsquery` ANDs every word, so a sentence matches nothing.

    Asking "which Sulzer multistage pumps do we hold and what is their rated head?"
    returned zero rows while "Sulzer" alone returned seven - the answer then correctly
    but uselessly said it held no Sulzer pumps.
    """

    def test_the_answer_path_actually_uses_the_rewriter(self):
        """Testing the helper alone let a regression through.

        Injecting `terms = question` back into `answer` broke nothing, because every
        test here called `record_query` directly. The helper being correct is no use if
        the caller stops using it.
        """
        source = inspect.getsource(chat.answer)
        assert "record_query(question)" in source
        assert "SearchFilters(query=terms)" in source

    def test_the_question_becomes_an_or_query(self):
        terms = chat.record_query("Which Sulzer multistage pumps do we hold?")
        assert " or " in terms
        assert "sulzer" in terms
        assert "multistage" in terms

    @pytest.mark.parametrize("noise", ["which", "we", "do", "the", "what", "pumps"])
    def test_the_vocabulary_of_asking_is_dropped(self, noise):
        """Otherwise every question matches every row through its own filler."""
        assert noise in chat._NOISE

    def test_a_question_with_no_content_words_matches_nothing(self):
        """Returning the whole table as if it were relevant would be worse."""
        assert chat.record_query("what do we have?") == ""
        assert chat.record_query("???") == ""

    def test_terms_are_capped(self):
        long_question = " ".join(f"term{n}" for n in range(50))
        assert len(chat.record_query(long_question).split(" or ")) <= chat.MAX_QUERY_TERMS

    def test_a_term_is_not_repeated(self):
        assert chat.record_query("Sulzer sulzer SULZER MSD") == "sulzer or msd"

    def test_model_codes_survive_tokenising(self):
        """A code is the most useful term in the question and often has punctuation."""
        terms = chat.record_query("Do we hold the MSD-4x6x11 or an API 610 BB3?")
        assert "msd-4x6x11" in terms
        assert "610" in terms


class TestNewOnTheWebIsOnlyASuggestion:
    def test_a_held_vendor_is_not_offered(self):
        class Result:
            url = "https://www.sulzer.com/msd"
            title = "Sulzer MSD"

        assert chat._looks_new(Result(), {"sulzer"}) is None

    def test_an_unheld_vendor_is_offered(self):
        class Result:
            url = "https://www.flowserve.com/hpx"
            title = "Flowserve HPX"

        assert chat._looks_new(Result(), {"sulzer"}) == "Flowserve"

    def test_a_page_naming_no_known_vendor_is_not_offered(self):
        class Result:
            url = "https://example.com/blog/pump-basics"
            title = "How pumps work"

        assert chat._looks_new(Result(), set()) is None

    def test_the_comparison_uses_the_same_normaliser_as_the_resolver(self):
        """So "Sulzer Pumps Ltd." and "sulzer" are one vendor here and there."""
        source = inspect.getsource(chat._looks_new)
        assert "normalize_company_name" in source


class TestFailuresDegradeRatherThanBlank:
    def test_a_web_search_failure_still_answers_from_records(self):
        source = inspect.getsource(chat.answer)
        assert "web_error" in source
        # The except around the search must not re-raise.
        assert "chat.web_search_failed" in source

    def test_a_missing_reading_model_says_so(self):
        source = inspect.getsource(chat.answer)
        assert "No reading model is active" in source

    def test_a_missing_search_provider_says_so_and_names_the_page(self):
        source = inspect.getsource(chat.answer)
        assert "/ai-settings" in source

    def test_the_screen_is_told_up_front_whether_the_web_is_available(self):
        """So the toggle is not offered when it cannot work."""
        assert "web_available" in inspect.getsource(chat_routes.context)
        assert inspect.getsource(chat.web_is_available)


class _Rows:
    """Just enough of a SQLAlchemy result to stand in for one that found nothing."""

    def all(self) -> list:
        return []


class _CountingSession:
    """A session that answers nothing and remembers how often it was asked.

    The point of :func:`chat.record_details` is the query count: this database is remote
    at roughly a third of a second per round trip, so the shape that reads six spec rows
    per record costs fifteen seconds on eight records. Without a database to hand, the
    count is the property worth pinning.
    """

    def __init__(self) -> None:
        self.executes = 0
        self.spec_queries = 0

    def execute(self, _statement) -> _Rows:
        self.executes += 1
        return _Rows()

    def scalars(self, _statement) -> _Rows:
        self.spec_queries += 1
        return _Rows()


class TestARecordIsAnsweredWithEveryFieldItHolds:
    """The search index is a summary; an answer needs the record.

    Answering from the index means saying "not stated" about a casing design pressure
    the technical spec holds, because the index carries two dozen ranking columns while
    the spec tables carry several hundred between them.
    """

    def test_the_answer_path_loads_the_details(self):
        """Same lesson as the query rewriter: a helper the caller stops calling is dead."""
        source = inspect.getsource(chat.answer)
        assert "record_details(db, hits)" in source
        assert "_record_context(details)" in source

    def test_the_groups_are_the_profile_pages_groups_in_its_order(self):
        """A chat result and a pump profile should not need translating between them."""
        assert list(chat.GROUP_LABELS) == [
            "attributes",
            "technical",
            "commercial",
            "dimensional",
            "delivery",
            "operational",
            "administrative",
        ]
        assert chat.GROUP_LABELS["dimensional"] == "Weights & dimensions"

    def test_row_bookkeeping_is_not_shown_as_pump_data(self):
        """`confidence_level: ai_extracted` inside a Technical panel reads as a spec."""
        rows = chat._present(
            [
                ("rated_head_m", 138.0),
                ("confidence_level", "ai_extracted"),
                ("verification_status", "unverified"),
                ("data_submission_date", "2026-09-02"),
            ]
        )
        assert [field["field_name"] for field in rows] == ["rated_head_m"]

    def test_an_empty_json_column_is_not_a_recorded_field(self):
        """An unpopulated JSON column comes back as `{}`, which is not None."""
        assert chat._present([("signal_list", {})]) == []
        assert chat._present([("certifications", [])]) == []
        assert chat._present([("material_class", "")]) == []
        # Zero stages is a value someone wrote down, not a gap.
        assert chat._present([("stages", 0)]) != []

    def test_a_group_reports_what_it_tracks_not_only_what_it_shows(self):
        """ "1 of 144" is checkable; "1 field" is not."""
        session = _CountingSession()
        details = chat.record_details(session, [{"pump_model_id": str(uuid.uuid4())}])
        groups = {group["key"]: group for group in details[0]["groups"]}
        assert groups["technical"]["recorded"] == 0
        assert groups["technical"]["tracked"] == len(
            [name for name in SPEC_FIELDS["technical"] if name not in chat.ROW_META_COLUMNS]
        )

    def test_the_cost_does_not_grow_with_the_number_of_records(self):
        """One query for the pump rows and one per spec group, for any record count."""
        one = _CountingSession()
        chat.record_details(one, [{"pump_model_id": str(uuid.uuid4())}])
        many = _CountingSession()
        chat.record_details(many, [{"pump_model_id": str(uuid.uuid4())} for _ in range(8)])

        assert one.executes == many.executes == 1
        assert one.spec_queries == many.spec_queries == len(records_service.SPEC_CLASSES)

    def test_a_row_without_a_model_id_is_skipped_rather_than_raising(self):
        """A malformed search row should cost that row, not the whole answer."""
        session = _CountingSession()
        assert chat.record_details(session, [{"label": "no id here"}]) == []


class TestTheContextSaysWhatIsAbsent:
    def test_markers_follow_the_order_the_details_were_given(self):
        """A citation is only resolvable if [R2] is the second record in both places."""
        rendered = chat._record_context(
            [
                {"marker": "R1", "label": "first", "groups": []},
                {"marker": "R2", "label": "second", "groups": []},
            ]
        )
        assert "[R1] first" in rendered
        assert "[R2] second" in rendered

    def test_a_record_holding_nothing_says_so(self):
        """Silence reads as "the fields are there and I chose not to show them"."""
        rendered = chat._record_context([{"marker": "R1", "label": "bare", "groups": []}])
        assert "no fields recorded" in rendered

    def test_the_prompt_says_an_absent_field_is_not_a_zero(self):
        """The difference between "not recorded" and "zero" decides a purchase."""
        assert "not recorded for it" in chat.SYSTEM_PROMPT

    def test_fields_are_capped_per_record(self):
        """One record with a thousand array entries must not crowd out the web half."""
        group = {
            "label": "Technical",
            "fields": [{"field_name": f"field_{n}", "value": n} for n in range(500)],
        }
        rendered = chat._record_context([{"marker": "R1", "label": "big", "groups": [group]}])
        assert rendered.count("field_") <= chat.MAX_CONTEXT_FIELDS


class TestCaptureReadsThePagesTheAnswerCited:
    """A capture started from an answer must read *those* pages.

    It used to run a fresh search from the same words, and a search is not a function:
    the same question returned a different eight pages, four of them educational guides
    about API 610 selection rather than product pages, and the run reported nothing
    found under a panel that said "read these pages". Handing the URLs over removes both
    the mismatch and a second search nobody asked for.
    """

    def test_the_route_forwards_the_pages_it_was_given(self):
        source = inspect.getsource(chat_routes.capture)
        assert "urls=payload.urls" in source

    def test_a_seeded_run_consults_no_search_provider(self):
        """Which also means it works with no search provider configured at all."""
        source = inspect.getsource(discovery.run_discovery)
        head = source[: source.index("segments = ")]
        assert "if seed_urls:" in head
        assert 'status="skipped"' in head
        # The searcher is only built on the branch that needs one.
        assert "searcher = None" in head

    def test_a_seeded_page_is_still_fetched_by_the_platform(self):
        """The provenance rule: a stored field quotes a page PumpAtlas read itself."""
        source = inspect.getsource(discovery.run_discovery)
        seeded = source[source.index("for url in seed_urls:") :]
        assert "ingestion.register_url(" in seeded.split("for segment in segments:")[0]

    def test_the_pages_are_normalised_once_for_both_ends(self):
        """Stored by `start_run`, read back by the runner - one list or neither is right."""
        assert "seed_url_list(urls)" in inspect.getsource(discovery.start_run)
        assert 'seed_url_list(config.get("urls"))' in inspect.getsource(discovery.run_discovery)

    def test_blank_and_duplicate_pages_are_dropped(self):
        assert discovery.seed_url_list([" https://a ", "https://a", "", None]) == ["https://a"]

    def test_the_page_count_is_capped(self):
        """Each page is one reading-model call, the same reason `max_results` is."""
        many = [f"https://example.com/{n}" for n in range(50)]
        assert len(discovery.seed_url_list(many)) == discovery.MAX_SEED_URLS

    def test_nothing_supplied_means_search_as_before(self):
        assert discovery.seed_url_list(None) == []
        assert discovery.seed_url_list([]) == []


class TestAnOpeningThatIsNotAQuestion:
    """"Hi there" used to be searched for, and found a dictionary entry for itself.

    `record_query` reduces it to nothing - "hi" is under three characters, "there" is a
    stopword - so no record matched, and the web provider was then handed the literal
    words. It returned Wiktionary on the interjection and a Quora thread on the
    difference between "hi" and "hi there": correct retrieval of entirely the wrong
    thing, at the cost of a real search.
    """

    @pytest.mark.parametrize(
        "opening",
        ["hi there", "HI there", "Hi there!!", "hello", "Hey  there ", "good morning"],
    )
    def test_a_greeting_is_answered_not_searched(self, opening):
        reply = chat.conversational_reply(opening)
        assert reply is not None
        assert reply.startswith("Hello.")
        # The suggestions are the screen's own, so the two cannot drift.
        for example in chat.EXAMPLE_QUESTIONS:
            assert example["query"] in reply

    @pytest.mark.parametrize("closing", ["thanks", "Thank you.", "bye"])
    def test_thanks_and_goodbyes_are_answered_too(self, closing):
        assert chat.conversational_reply(closing) is not None

    def test_asking_what_it_does_describes_it(self):
        reply = chat.conversational_reply("what can you do?")
        assert reply is not None
        assert "Vendor Shortlist" in reply

    @pytest.mark.parametrize(
        "question",
        [
            "Who makes BB3 barrel pumps for crude export duty?",
            "What NACE MR0175 compliant pumps are recorded for sour service?",
            # Contains a greeting word without being a greeting - the whole message is
            # matched, never a substring of it.
            "hi-flow pump seals",
            "Hello Flowserve ECPJ datasheet",
        ],
    )
    def test_a_real_question_is_never_intercepted(self, question):
        assert chat.conversational_reply(question) is None
        assert chat.record_query(question) != ""

    def test_a_message_with_nothing_searchable_asks_for_a_detail(self):
        """"What do we have?" has no content word, so there is nothing to search for."""
        assert chat.record_query("what do we have?") == ""
        reply = chat.clarification_reply("what do we have?")
        assert "no vendor, model, standard or duty" in reply

    def test_a_written_answer_claims_no_evidence_and_no_model(self):
        """Same envelope as a searched answer, with the citation lists honestly empty."""
        result = chat._no_search_result("Hello.")
        assert result["records"] == [] and result["web"] == []
        assert result["record_total"] == 0
        # Naming a model would be untrue: none wrote this.
        assert result["model"] is None
        assert result["error"] is None and result["web_error"] is None


class TestTheDomainGate:
    """Questions outside oil and gas are refused before a search is spent on them.

    The gate sits *after* the catalogue search, not before it, and that ordering is the
    design: a question that matched a record is about this domain by construction, so a
    vendor or a model code the catalogue holds can never be refused however unusual it
    looks. Only a question that matched nothing has to persuade the vocabulary.
    """

    @pytest.mark.parametrize(
        "question",
        [
            "Who makes BB3 barrel pumps for crude export duty?",
            "centrifugal pump",
            "hi-flow pump seals",
            "vertical sump pump for oily water",
            "who supplies mechanical seals to API 682",
            "duplex stainless impeller for produced water injection",
            "FPSO cargo offloading pump 2000 m3/h at 150 m",
            "any ATEX certified pumps for zone 1?",
            "lead time for a boiler feed pump",
            # A model designation the vocabulary cannot list, recognised by shape.
            "HPX4x6",
            "3409L seawater lift",
        ],
    )
    def test_the_domain_is_recognised(self, question):
        assert domain_signal(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "what is the weather in Doha",
            "who won the world cup",
            "write me a poem about the sea",
            "how do I cook rice",
            "what is the capital of India",
            "best laptop under 50000",
        ],
    )
    def test_everything_else_is_not(self, question):
        assert domain_signal(question) is False

    def test_a_matched_record_is_never_refused(self):
        """"PWI-BB" is letters only, so the vocabulary misses it - the search does not.

        This is the case that justifies the ordering. The gate is consulted only when
        `hits` is empty, and a real model code is exactly what fills `hits`.
        """
        assert domain_signal("PWI-BB") is False
        source = inspect.getsource(chat.answer)
        assert "if not hits and not domain_signal(question):" in source
        # ...and it is reached only after the search has run.
        assert source.index("search.search_pump_models") < source.index("domain_signal(")

    def test_a_refusal_searches_nothing(self):
        """Refusing after a web search would defeat the point of refusing."""
        source = inspect.getsource(chat.answer)
        assert source.index("domain_signal(") < source.index("if use_web:")

    def test_the_refusal_says_what_it_does_answer(self):
        reply = chat.off_domain_reply()
        assert "oil and gas pumps" in reply
        for example in chat.EXAMPLE_QUESTIONS:
            assert example["query"] in reply


class TestAskingAfterTheAssistant:
    """"How are you" is a question about the assistant, not a hello.

    It was in the greeting set and so was answered "Hello. I answer questions about..."
    - which ignores what was actually asked. It has its own reply now.
    """

    @pytest.mark.parametrize(
        "question", ["how are you", "How are you?", "hows it going", "you ok"]
    )
    def test_it_is_answered_on_its_own_terms(self, question):
        reply = chat.conversational_reply(question)
        assert reply is not None
        assert not reply.startswith("Hello.")

    def test_a_form_of_address_does_not_swallow_the_phrase(self):
        """"are you there" ends in an address term, and stripping it leaves nothing.

        Both forms are matched - as written, and with the address dropped - so "hi
        there" still reduces to "hi" while "are you there" keeps its meaning.
        """
        assert chat.conversational_reply("are you there") is not None
        assert chat.conversational_reply("hi there") is not None
        assert chat.conversational_reply("hello bro") is not None

    def test_a_question_that_ends_in_one_is_left_alone(self):
        assert chat.conversational_reply("is there an API 610 BB3 pump") is None
        assert chat.conversational_reply("list all Sulzer pumps") is None
