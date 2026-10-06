"""AI web discovery: the wiring that cannot be checked without a database.

These are source- and contract-level assertions covering the shared engine and both
kinds that run on it. The end-to-end path needs a live PostgreSQL, both provider keys and
real network, so it lives in ``test_live_integration.py``; what is pinned here is the
structure that made the feature correct in the first place.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import types
import uuid

import pytest
from pydantic import ValidationError

from app.ai import prompts
from app.ai.parallel_search import (
    PUMP_SUPPLY_COUNTRIES,
    PUMP_TYPE_PHRASES,
    SERVICE_PHRASES,
)
from app.api.v1 import discovery_routes
from app.core.countries import is_country
from app.models.enums import PumpType, ValueOrigin
from app.models.pump import PumpModel
from app.models.vendor import Vendor
from app.schemas.discovery import DiscoveryStartRequest
from app.services import discovery, promotion, provenance, pump_discovery, vendor_discovery

KINDS = (vendor_discovery.KIND, pump_discovery.KIND)


class TestRoutePlacement:
    @pytest.mark.parametrize(
        ("prefix", "kind"),
        [("/vendor-discovery", "vendor"), ("/pump-discovery", "pump")],
    )
    def test_prefixes_are_not_under_a_uuid_route(self, prefix, kind):
        """`/vendors/<static>` resolves only while router registration order holds.

        `/comparisons/vendors` and `/tenants/me/settings` were both shadowed by a UUID
        path param in this codebase already. A sibling prefix cannot be.
        """
        router = discovery_routes.ROUTERS[kind]
        assert router.prefix == prefix
        assert not router.prefix.startswith(("/vendors/", "/pumps/", "/pump-models/"))

    def test_both_kinds_expose_the_same_contract(self):
        """One UI drives both, so the route shapes have to match once the prefix is off."""
        shapes = {}
        for kind, router in discovery_routes.ROUTERS.items():
            shapes[kind] = sorted(
                (
                    getattr(route, "path", "").removeprefix(router.prefix) or "/",
                    tuple(sorted(getattr(route, "methods", set()))),
                )
                for route in router.routes
            )
        assert shapes["vendor"] == shapes["pump"]
        assert ("/{run_id}/select", ("POST",)) in shapes["pump"]


class TestRouterFactoryScoping:
    """The route handlers are closures, which makes shadowing an import silent.

    Naming a handler `select` shadowed SQLAlchemy's `select` for every other handler in
    the same scope: `list_runs` then called the handler instead of the query builder and
    returned a 500. Nothing in a type check or a lint pass catches that, because from
    inside the closure the name *is* defined.
    """

    def test_no_handler_shadows_a_module_level_import(self):
        tree = ast.parse(pathlib.Path(discovery_routes.__file__).read_text(encoding="utf-8"))

        imported: set[str] = set()
        factory: ast.FunctionDef | None = None
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
            elif isinstance(node, ast.FunctionDef) and node.name == "build_router":
                factory = node
        assert factory is not None

        nested = {
            child.name
            for child in ast.walk(factory)
            if isinstance(child, ast.FunctionDef) and child is not factory
        }
        collisions = sorted(nested & imported)
        assert not collisions, f"handlers shadow module imports: {collisions}"


class TestPollCostIsBounded:
    """The run detail is polled every few seconds, against a hosted database.

    It used to resolve each candidate's source row and each candidate's duplicate match
    one candidate at a time. At a third of a second per round trip, a run with 33
    candidates took 30 seconds to render, the poll queued faster than it drained, the
    connection pool emptied and the browser reported "failed to fetch" - a search that
    had actually worked looked broken. The queries per poll must not scale with the
    number of candidates found.
    """

    def _factory(self) -> ast.FunctionDef:
        tree = ast.parse(pathlib.Path(discovery_routes.__file__).read_text(encoding="utf-8"))
        factory = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_router"
        )
        return factory

    def _nested(self, name: str) -> ast.FunctionDef:
        return next(
            child
            for child in ast.walk(self._factory())
            if isinstance(child, ast.FunctionDef) and child.name == name
        )

    def test_rendering_a_candidate_touches_no_database(self):
        """`candidate_out` runs once per candidate, so it must be pure.

        Anything it looks up itself is a round trip multiplied by the number of
        candidates - which is exactly the regression this guards.
        """
        render = self._nested("candidate_out")
        assert "db" not in {
            arg.arg for arg in render.args.args
        }, "candidate_out must not take a session: it runs once per candidate"
        loads = [
            node
            for node in ast.walk(render)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "db"
        ]
        assert not loads, f"candidate_out queries the database: {[n.attr for n in loads]}"

    def test_duplicate_matches_are_resolved_in_one_call(self):
        """One `existing_map` call for the whole run, never one per candidate."""
        render = self._nested("render_candidates")
        calls = [
            node
            for node in ast.walk(render)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "existing_map"
        ]
        assert len(calls) == 1, f"existing_map is called {len(calls)} times per render"
        # ...and not from inside a loop or comprehension over the candidates.
        for scope in ast.walk(render):
            if isinstance(scope, ast.For | ast.ListComp | ast.GeneratorExp | ast.DictComp):
                assert not [
                    node
                    for node in ast.walk(scope)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "existing_map"
                ], "existing_map is called per candidate"

    def test_sources_arrive_with_their_candidates(self):
        """The candidate query already joins `sources`; the rows are free there."""
        assert "add_columns(Source)" in inspect.getsource(discovery.candidates_with_sources)
        # `get_run` fetching one batch by id is one query for the whole request; what
        # must not happen is a fetch while rendering, once per candidate.
        rendering = ast.unparse(self._nested("candidate_out")) + ast.unparse(
            self._nested("render_candidates")
        )
        assert "db.get" not in rendering

    @pytest.mark.parametrize(
        "resolver",
        (vendor_discovery.existing_vendors_for, pump_discovery.existing_models_for),
        ids=("vendor", "pump"),
    )
    def test_the_batch_resolvers_take_a_collection(self, resolver):
        """Each kind answers the duplicate question for many candidates at once."""
        params = list(inspect.signature(resolver).parameters)
        assert params[:2] == ["db", "tenant_id"]
        annotation = inspect.signature(resolver).parameters[params[2]].annotation
        assert "Iterable" in str(annotation), annotation

    def test_the_capped_feed_still_reports_the_true_total(self):
        """A field the response model does not declare is silently dropped.

        The payload can carry `job_count` and the browser still never see it - which is
        how `sweep` went missing once already. The schema is the contract.
        """
        from app.schemas.discovery import DiscoveryRun

        assert "job_count" in DiscoveryRun.model_fields

    def test_the_job_feed_is_capped(self):
        """A 23-segment sweep makes hundreds of provider calls.

        The panel shows the recent ones, so the poll payload stays flat instead of
        growing for the whole run - but the true total is still reported, or the UI
        would quietly understate what the AI did.
        """
        assert discovery.JOB_FEED_LIMIT <= 60
        source = inspect.getsource(discovery.job_summary)
        assert "rows[-limit:]" in source
        assert "return [" in source and ", total" in source
        # Failures are kept ahead of the cap: on a long run they are the reason
        # anyone opens the panel at all.
        assert "AiJobStatus.FAILED" in source


class TestSharedEngine:
    @pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.slug)
    def test_both_providers_are_used_and_in_order(self, kind):
        """One provider decides where to look, another decides what the page says.

        Which vendor fills each role is configuration now - search can be Parallel AI,
        OpenAI or Claude, and reading can be Gemma, OpenAI or Claude - so this asserts
        the order of the two roles rather than two class names.
        """
        source = inspect.getsource(discovery.run_discovery)
        assert source.index("providers.search_client(") < source.index("providers.reading_model(")
        assert kind.build_objective is not None
        assert kind.system_prompt

    @pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.slug)
    def test_stages_name_the_provider_doing_the_work(self, kind):
        """The UI badges each stage with the AI doing it, so it must be the real one.

        Previously fixed to "parallel" and "gemma", which became a lie the moment the
        provider was configurable: the badge would say Gemma while the job list beside
        it said Claude.
        """
        from app.core.config import settings

        by_key = {stage["key"]: stage for stage in discovery.initial_stages(kind)}
        assert by_key["search"]["provider"] == settings.SEARCH_PROVIDER
        assert by_key["screen"]["provider"] == settings.EXTRACTION_PROVIDER
        # Capture is PumpAtlas fetching the page itself - no model is involved, which
        # is exactly why a stored value can cite the page rather than a summary of it.
        assert by_key["capture"]["provider"] is None

    def test_no_transaction_is_held_across_a_provider_call(self):
        """The bug that once killed extraction: a 119-second call inside a transaction.

        The search call is preceded by a commit, and the per-page Gemma calls go through
        `extraction.execute_ai_job`, which commits before calling out.
        """
        source = inspect.getsource(discovery.run_discovery)
        before_search, _, _ = source.partition("ParallelSearchClient().search")
        assert "db.commit()" in before_search
        screen = inspect.getsource(discovery.screen_source)
        assert "client.complete" not in screen
        assert "execute_ai_job" in screen

    @pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.slug)
    def test_each_kind_has_its_own_import_mode(self, kind):
        assert kind.import_mode == f"{kind.slug}_discovery"

    def test_the_two_kinds_do_not_share_an_entity_type(self):
        """Candidates are queried by entity type; a collision would mix the two runs."""
        assert vendor_discovery.KIND.entity_type != pump_discovery.KIND.entity_type


class TestOilAndGasScreening:
    @pytest.mark.parametrize(
        ("prompt", "key"),
        [
            (prompts.SYSTEM_VENDOR_PROFILE, "is_oil_gas_pump_vendor"),
            (prompts.SYSTEM_PUMP_PROFILE, "is_oil_gas_pump_model"),
        ],
    )
    def test_the_prompt_demands_an_explicit_in_scope_decision(self, prompt, key):
        assert key in prompt
        assert "relevance_reason" in prompt

    @pytest.mark.parametrize("prompt", [prompts.SYSTEM_VENDOR_PROFILE, prompts.SYSTEM_PUMP_PROFILE])
    def test_the_prompt_rules_out_the_obvious_false_positives(self, prompt):
        """The user asked for Oil & Gas, not every pump page on the web."""
        text = prompt.lower()
        for excluded in ("director", "marketplace", "recruitment", "water", "hvac"):
            assert excluded in text, excluded

    @pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.slug)
    def test_the_relevance_key_matches_the_prompt(self, kind):
        assert kind.relevance_key in kind.system_prompt

    def test_a_page_ruled_out_creates_no_candidate(self):
        source = inspect.getsource(discovery.screen_source)
        rejected_branch = source[source.index("if not data.get(kind.relevance_key)") :]
        head = rejected_branch[: rejected_branch.index('return "rejected"')]
        assert "ExtractedEntity(" not in head

    def test_a_pump_page_must_name_a_model_not_just_a_company(self):
        """A model with no designation is not a row worth having."""
        text = prompts.SYSTEM_PUMP_PROFILE.lower()
        assert "name no model" in text or "names no model" in text

    def test_the_pump_prompt_refuses_to_read_a_range_as_a_rated_duty(self):
        """The most tempting invention on a datasheet: an envelope read as a duty point."""
        assert "envelope, not its rated duty" in prompts.SYSTEM_PUMP_PROFILE


class TestStorageIsGated:
    """A run writes to the record only when it was asked to, and never untraceably.

    Storage was human-gated absolutely: discovery produced candidates and a person
    picked which to keep. Scraping the web for every pump and vendor makes that
    impractical at 150 pages a sweep, so `auto_store` was added - but the guarantee
    that matters is traceability, not the click. What must still hold is that every
    stored field carries a verbatim quote from the page it came from, whoever asked.

    The previous version of the first test forbade the strings "store_candidate" and
    "promote_extracted_entity" in `run_discovery`. It kept passing after auto-store
    landed, because the write moved into a helper and `inspect.getsource` only sees the
    one function - false assurance, which is worse than no test.
    """

    def test_a_run_writes_only_when_the_request_asked_for_it(self):
        source = inspect.getsource(discovery._store_unattended)
        loop = inspect.getsource(discovery.run_discovery)
        # Gated on the flag, and off unless the request set it.
        assert 'config.get("auto_store")' in loop
        assert "auto_store" in loop and "_store_unattended(" in loop
        assert "auto_store: bool = Field(\n        default=False" in inspect.getsource(
            __import__("app.schemas.discovery", fromlist=["x"])
        )
        # And it reuses the one writer per kind rather than growing a second path.
        assert "_writer_for(kind)" in source

    def test_an_unconfident_candidate_is_left_for_review(self):
        """A doubtful reading belongs in the queue, not in the record."""
        source = inspect.getsource(discovery._store_unattended)
        assert "float(score) < threshold" in source
        assert "return 0" in source

    def test_a_refused_candidate_is_a_review_task_not_a_crash(self):
        """One unusable page must not end a sweep that has already paid for searches."""
        source = inspect.getsource(discovery._store_unattended)
        assert "PromotionError" in source
        assert "review_notes" in source

    def test_the_confidence_bar_is_the_platform_default(self):
        """The same bar the ingest path uses, so the two do not diverge."""
        from app.services import extraction

        source = inspect.getsource(discovery.run_discovery)
        assert "extraction.AUTO_PROMOTE_THRESHOLD" in source
        assert extraction.AUTO_PROMOTE_THRESHOLD == 0.85

    def test_vendor_fields_are_an_allowlist_of_real_columns(self):
        """A prompt change must not be able to start writing a new column."""
        for column in vendor_discovery.VENDOR_PROFILE_FIELDS.values():
            assert hasattr(Vendor, column), column

    def test_vendor_facts_without_a_column_are_kept_not_dropped(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "VENDOR_EXTRA_FIELDS" in source
        assert "vendor.extra" in source

    def test_vendor_writes_go_through_the_provenance_gate(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "provenance.apply_fields" in source
        assert "setattr(" not in source

    def test_a_new_vendors_name_gets_provenance(self):
        """`resolve_vendor` must set the name to insert the row at all, which would
        otherwise leave the record's own identity as its one untraceable value."""
        assert "record_unchanged=True" in inspect.getsource(vendor_discovery.store_candidate)

    def test_pump_storage_reuses_the_one_promotion_path(self):
        """A second promotion path would drift from the one the review queue uses."""
        source = inspect.getsource(pump_discovery.store_candidate)
        assert "promotion.promote_extracted_entity" in source
        assert "resolve_pump_model" not in source

    def test_storage_is_attended_unless_the_run_says_otherwise(self):
        """Defaults to attended; a sweep opts in and thereby raises the subject bar.

        Unattended refuses a candidate whose subject name is unusable, because a page
        about "BB3 pumps" names a category and would otherwise become a record called
        "BB3" that nobody can act on.
        """
        import inspect as _inspect

        signature = _inspect.signature(pump_discovery.store_candidate)
        assert signature.parameters["unattended"].default is False
        assert "unattended=unattended" in inspect.getsource(pump_discovery.store_candidate)

    def test_a_vendor_name_is_checked_whoever_stored_it(self):
        """The vendor writer's name check is unconditional, attended or not."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "is_usable_subject_name(vendor_name)" in source
        # Not gated on the flag - a vendor called "Pumps" is useless either way.
        assert "if unattended and not is_usable_subject_name" not in source

    @pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.slug)
    def test_an_already_stored_candidate_cannot_be_stored_twice(self, kind):
        module = vendor_discovery if kind.slug == "vendor" else pump_discovery
        assert "promoted_at is not None" in inspect.getsource(module.store_candidate)


class TestTheFormCanBeFilledInWithoutKnowingAnything:
    """Finding a supplier must not require naming one.

    The panel used to ask for a "pump type or duty" as free text with pump-type presets
    underneath, which is the wrong question: someone searching for vendors knows the duty
    they are buying for and does not know the manufacturers - that is why they are
    searching. So the query is composed from vocabularies the platform already enforces,
    and the phrases below are what the provider is actually asked.
    """

    def test_a_duty_vocabulary_exists_for_the_form_to_offer(self):
        assert len(SERVICE_PHRASES) >= 12

    def test_the_duties_are_the_ones_oil_and_gas_actually_buys_for(self):
        for expected in ("crude_export", "water_injection", "chemical_injection", "lng"):
            assert expected in SERVICE_PHRASES

    @pytest.mark.parametrize("phrase", sorted(SERVICE_PHRASES.values()))
    def test_a_duty_reads_as_prose(self, phrase):
        """It goes into a search objective, which a provider answers as English."""
        assert "_" not in phrase
        assert phrase == phrase.strip()
        assert len(phrase.split()) >= 2

    @pytest.mark.parametrize("phrase", sorted(PUMP_TYPE_PHRASES.values()))
    def test_a_pump_type_reads_as_prose_too(self, phrase):
        assert "_" not in phrase

    def test_every_modelled_pump_type_has_a_phrase(self):
        """A type with no phrase would be missing from both the form and the sweep."""
        modelled = {member.value for member in PumpType} - {"other"}
        assert modelled == set(PUMP_TYPE_PHRASES)


class TestSweep:
    """ "Fetch everything" has to mean something concrete.

    There is no call that returns the whole web — a search provider answers an objective.
    A sweep is the honest version: one search per value of some axis the platform already
    models, so coverage comes from the domain model rather than from whatever the user
    thought to type.

    The two kinds sweep along different axes, and that difference is the point. Asking 23
    pump types returns the same global OEMs from every angle, which is right for finding
    pump *models* and useless for finding suppliers nobody here has heard of; those are
    regional, so vendors sweep countries.
    """

    def test_a_pump_sweep_covers_every_modelled_pump_type(self):
        segments = discovery.plan_sweep(pump_discovery.KIND, None)
        keys = {segment["key"] for segment in segments}
        modelled = {member.value for member in PumpType} - {"other"}
        assert keys == modelled, modelled ^ keys

    def test_a_vendor_sweep_covers_the_supply_countries_by_default(self):
        segments = discovery.plan_sweep(vendor_discovery.KIND, None)
        keys = {segment["key"] for segment in segments}
        assert keys == {code.lower() for code in PUMP_SUPPLY_COUNTRIES}

    def test_the_supply_countries_are_all_real_countries(self):
        """A typo here costs a whole segment and reports as "no suppliers there"."""
        assert all(is_country(code) for code in PUMP_SUPPLY_COUNTRIES)

    def test_the_supply_list_keeps_its_order(self):
        """A cancelled sweep should have covered the countries that matter first."""
        assert PUMP_SUPPLY_COUNTRIES[0] == "US"
        assert isinstance(PUMP_SUPPLY_COUNTRIES, tuple)

    def test_a_vendor_sweep_can_still_go_by_pump_type(self):
        segments = discovery.plan_sweep(vendor_discovery.KIND, None, scope="pump_type")
        keys = {segment["key"] for segment in segments}
        assert keys == {member.value for member in PumpType} - {"other"}

    def test_a_country_sweep_can_be_narrowed_to_a_list(self):
        segments = discovery.plan_sweep(
            vendor_discovery.KIND, None, scope="country", countries=["AE", "NO"]
        )
        assert [segment["label"] for segment in segments] == [
            "United Arab Emirates",
            "Norway",
        ]

    def test_pumps_offer_no_country_axis(self):
        """A pump model is identified by its duty, not its postcode."""
        assert "country" not in pump_discovery.KIND.sweep_scopes
        assert "country" in vendor_discovery.KIND.sweep_scopes

    def test_an_unknown_axis_falls_back_rather_than_crashing(self):
        """`segments_for` is called with whatever the request carried."""
        segments = vendor_discovery.KIND.segments_for("nonsense")
        assert len(segments) == len(PUMP_SUPPLY_COUNTRIES)

    def test_a_single_country_is_not_iterated_as_characters(self):
        """Passing "AE" where a list is expected would sweep the countries A and E."""
        segments = vendor_discovery.KIND.segments_for("country", countries="AE")
        assert [
            segment["label"] if isinstance(segment, dict) else segment.label for segment in segments
        ] == ["United Arab Emirates"]

    @pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.slug)
    def test_every_segment_carries_its_own_objective(self, kind):
        segments = discovery.plan_sweep(kind, None)
        objectives = {segment["objective"] for segment in segments}
        assert len(objectives) == len(segments), "segments must not share an objective"
        for segment in segments:
            assert segment["queries"], segment["key"]

    def test_a_vendor_objective_asks_for_the_basic_information(self):
        """The panel promises basic vendor info, so the objective has to ask for it."""
        objective, _ = vendor_discovery.KIND.build_objective("pumps in Norway", "NO")
        for wanted in ("legal entity", "headquarters", "website", "certification"):
            assert wanted in objective.lower(), wanted

    def test_a_country_sweep_names_the_country_in_english(self):
        """The provider is answering prose; "NO" reads as the word "no"."""
        segments = discovery.plan_sweep(
            vendor_discovery.KIND, None, scope="country", countries=["NO"]
        )
        assert "Norway" in segments[0]["objective"]

    def test_the_country_reaches_every_query_not_just_the_objective(self):
        """A country sweep whose queries omit the country is 60 identical searches."""
        segments = discovery.plan_sweep(
            vendor_discovery.KIND, None, scope="country", countries=["AE"]
        )
        assert all("United Arab Emirates" in query for query in segments[0]["queries"])

    def test_the_place_is_not_pasted_into_the_subject_twice(self):
        """It read "supply Oil & Gas pump suppliers in Norway for Oil & Gas service"."""
        segments = discovery.plan_sweep(
            vendor_discovery.KIND, None, scope="country", countries=["NO"]
        )
        assert segments[0]["objective"].count("Norway") == 1
        assert "suppliers in Norway" not in segments[0]["objective"]

    @pytest.mark.parametrize(
        ("scope", "expected"),
        [
            ("country", ("country", "countries")),
            ("pump_type", ("pump type", "pump types")),
            (None, ("pump type", "pump types")),
            ("nonsense", ("pump type", "pump types")),
        ],
    )
    def test_a_sweep_is_named_in_readable_english(self, scope, expected):
        """The run name is what the panel, the run list and the audit entry all show.

        It read "every countrie (2 segments)", because the plural was being sliced.
        """
        assert discovery.axis_words(scope) == expected

    def test_the_country_reaches_every_segment(self):
        segments = discovery.plan_sweep(pump_discovery.KIND, "BR")
        assert all(
            "BR" in segment["objective"] or "BR" in " ".join(segment["queries"])
            for segment in segments
        )

    def test_a_query_or_a_sweep_is_required(self):
        """A retrieval API needs something to retrieve."""
        with pytest.raises(ValidationError):
            DiscoveryStartRequest()
        assert DiscoveryStartRequest(sweep=True).query is None
        assert DiscoveryStartRequest(query="API 610 BB3").sweep is False

    def test_the_total_page_count_is_capped(self):
        """23 types at 25 pages is 575 Gemma calls; nobody meant to ask for that."""
        segment_count = len(discovery.plan_sweep(pump_discovery.KIND, None))
        per_search = max(
            1,
            min(25, discovery_routes.MAX_SWEEP_PAGES // segment_count),
        )
        assert per_search * segment_count <= discovery_routes.MAX_SWEEP_PAGES
        assert per_search >= 1, "a cap that trims to zero would search nothing"

    def test_duplicate_urls_are_skipped_within_a_run(self):
        """Twenty overlapping searches return the same OEM page twenty times."""
        source = inspect.getsource(discovery.run_discovery)
        assert "seen_urls" in source
        assert "duplicates" in source
        # The skip has to happen before capture, or the saving is lost.
        before_capture, _, _ = source.partition("register_search_result")
        assert "if url in seen_urls:" in before_capture

    def test_one_failed_segment_does_not_end_a_sweep(self):
        source = inspect.getsource(discovery.run_discovery)
        assert "if not sweeping:" in source
        assert "continue" in source

    def test_a_single_search_still_fails_the_run(self):
        """Silently returning an empty run for one failed search would hide the outage."""
        source = inspect.getsource(discovery.run_discovery)
        failure_branch = source[source.index("except SearchUnavailableError") :]
        assert "_fail_run(" in failure_branch[: failure_branch.index("continue")]


class TestMultiGroupPromotion:
    def test_discovery_writes_every_spec_group_it_extracted(self):
        """One datasheet yields technical, commercial, dimensional and delivery values.

        `promote_extracted_entity` used to infer a single spec group from the entity
        type, which would have silently dropped capacity, head and price from a pump
        discovery candidate.
        """
        assert "spec_groups" in inspect.signature(promotion.promote_extracted_entity).parameters
        assert discovery_routes.PUMP_SPEC_GROUPS

    def test_passing_no_groups_offers_all_of_them(self):
        """Naming no groups must not mean naming none.

        This test previously asserted the opposite - that the group is inferred from
        ``entity.entity_type`` - and in doing so pinned a silent data loss as correct
        behaviour. The entity type both real flows produce is "pump_model", which is not
        a spec group, so the inference resolved to nothing: no spec row was opened and
        every extracted specification value was discarded on accept. The record still
        looked plausible afterwards, keeping its vendor and pump-level fields, so only
        the six empty panels gave it away.
        """
        # The write itself lives in `write_spec_groups`, shared with the backfill that
        # repairs the records this defect damaged, so neither can drift from the other.
        source = inspect.getsource(promotion.write_spec_groups)
        assert "if spec_groups is not None" in source
        assert "else list(SPEC_MODEL_BY_ENTITY.values())" in source
        assert "SPEC_MODEL_BY_ENTITY[entity.entity_type]" not in source
        assert "write_spec_groups(" in inspect.getsource(promotion.promote_extracted_entity)

    def test_the_entity_type_both_flows_produce_is_not_a_spec_group(self):
        """Which is precisely why inferring the group from it dropped everything."""
        assert "pump_model" not in promotion.SPEC_MODEL_BY_ENTITY
        assert pump_discovery.KIND.entity_type == "pump_model"

    def test_no_field_is_owned_by_two_spec_groups(self):
        """What makes offering every group safe rather than duplicating values.

        Each field is routed by column membership, so a name shared by two spec models
        would be written to both.
        """
        from sqlalchemy import inspect as sqla_inspect

        infrastructure = {
            "id",
            "created_at",
            "updated_at",
            "tenant_id",
            "version",
            "is_current",
            "superseded_at",
            "schema_version",
            "pump_model_id",
            "source_id",
            "ai_job_id",
            "created_by_user_id",
            "confidence_level",
            "verification_status",
            "source_units",
            "notes",
            "extra",
            "data_submission_date",
            "deleted_at",
        }
        identity = promotion.VENDOR_FIELDS | promotion.PUMP_FIELDS | promotion.PUMP_MODEL_FIELDS
        owners: dict[str, list[str]] = {}
        for name, cls in promotion.SPEC_MODEL_BY_ENTITY.items():
            for column in sqla_inspect(cls).columns.keys():
                if column in infrastructure or column in identity:
                    continue
                owners.setdefault(column, []).append(name)
        shared = {column: groups for column, groups in owners.items() if len(groups) > 1}
        assert not shared, f"columns owned by several spec groups: {shared}"

    def test_an_empty_group_opens_no_version_row(self):
        source = inspect.getsource(promotion.write_spec_groups)
        assert "if not candidate_fields:" in source

    def test_every_named_group_is_a_real_spec_table(self):
        for name in discovery_routes.PUMP_SPEC_GROUPS:
            assert name in promotion.SPEC_MODEL_BY_ENTITY, name

    def test_the_pump_prompt_covers_the_groups_that_get_written(self):
        """A group written but never extracted would open empty version rows forever."""
        assert "rated_capacity_m3h" in prompts.SYSTEM_PUMP_PROFILE
        assert "base_price_amount" in prompts.SYSTEM_PUMP_PROFILE
        assert hasattr(PumpModel, "model_code")


class TestSpecBackfill:
    """The repair that recovers values the promotion defect dropped.

    It re-applies them through `write_spec_groups`, the same function the live path uses,
    so what is pinned here is the part the repair adds: which candidates it recognises as
    damaged, and that neither it nor the live path opens a version row for nothing.
    """

    SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "backfill_dropped_specs.py"

    def _stubs(self):
        entity = types.SimpleNamespace(
            tenant_id=None, field_confidences={}, ai_job_id=None, evidence_spans={}
        )
        pump_model = types.SimpleNamespace(id=uuid.uuid4())
        context = provenance.ProvenanceContext(origin=ValueOrigin.AI_EXTRACTION)
        return entity, pump_model, context

    def test_only_candidates_promoted_to_a_pump_model_are_repaired(self):
        """A candidate promoted since the fix has a spec row as its target, not a model.

        Selecting on `promoted_at` alone would look a pump model up by a specification's
        id, find nothing, and report the healthy records as unrepairable.
        """
        source = self.SCRIPT.read_text(encoding="utf-8")
        assert 'ExtractedEntity.target_type == "pump_model"' in source
        assert "ExtractedEntity.promoted_at.is_not(None)" in source

    def test_the_repair_never_overwrites_a_value_that_is_already_there(self):
        source = self.SCRIPT.read_text(encoding="utf-8")
        assert "skip_fields_with_a_value=True" in source

    def test_the_existing_values_are_resolved_in_one_query_per_table(self):
        """Per-model questions are unaffordable against a database 312ms away.

        Asking per model per spec table is six round trips per candidate; the snapshot
        makes it six for the whole run.
        """
        source = inspect.getsource(promotion.write_spec_groups)
        assert "fields_with_a_value" in source
        assert "existing_spec_values" in self.SCRIPT.read_text(encoding="utf-8")

    def test_a_group_whose_every_field_lacks_evidence_opens_no_version_row(self, monkeypatch):
        """Otherwise the refusal is discovered one row too late.

        `open_spec_version` retires the current version and replaces it with a copy, so a
        group that turns out to have nothing writable in it leaves behind a version
        identical to the one before it and an audit entry recording no change. A run over
        69 repaired candidates left 17 of them behind before this was fixed.
        """
        entity, pump_model, context = self._stubs()
        monkeypatch.setattr(
            promotion, "open_spec_version", lambda *a, **k: pytest.fail("opened a version row")
        )
        # db is None: touching the database at all would raise rather than pass quietly.
        spec, outcomes = promotion.write_spec_groups(
            None,
            entity=entity,
            pump_model=pump_model,
            context=context,
            fields={"rated_head_m": 50, "rated_capacity_m3h": 120},
            evidence={},
        )
        assert spec is None
        assert set(outcomes["technical_specs"]["refused"]) == {"rated_head_m", "rated_capacity_m3h"}
        assert "no evidence quote" in outcomes["technical_specs"]["refused"]["rated_head_m"]

    def test_a_group_of_nothing_but_empty_values_opens_no_version_row(self, monkeypatch):
        entity, pump_model, context = self._stubs()
        monkeypatch.setattr(
            promotion, "open_spec_version", lambda *a, **k: pytest.fail("opened a version row")
        )
        spec, outcomes = promotion.write_spec_groups(
            None,
            entity=entity,
            pump_model=pump_model,
            context=context,
            fields={"rated_head_m": None},
            evidence={"rated_head_m": "quoted"},
        )
        assert spec is None
        assert outcomes == {}

    def test_a_field_the_snapshot_already_holds_opens_no_version_row(self, monkeypatch):
        """And costs no query to establish, which is the point of passing it in."""
        entity, pump_model, context = self._stubs()
        monkeypatch.setattr(
            promotion, "open_spec_version", lambda *a, **k: pytest.fail("opened a version row")
        )
        spec, outcomes = promotion.write_spec_groups(
            None,
            entity=entity,
            pump_model=pump_model,
            context=context,
            fields={"rated_head_m": 50},
            evidence={"rated_head_m": "quoted"},
            skip_fields_with_a_value=True,
            fields_with_a_value={"technical_specs": {"rated_head_m"}},
        )
        assert spec is None
        assert outcomes == {}

    def test_the_refusal_wording_has_one_source(self):
        """The pre-check and the write itself must refuse in the same words."""
        assert "missing_evidence_reason" in inspect.getsource(promotion.write_spec_groups)
        assert "missing_evidence_reason" in inspect.getsource(provenance.apply_field)

    def test_a_value_naming_no_spec_column_is_reported_not_guessed(self):
        """`max_viscosity_cp` and `fluid_viscosity_cst` are different units.

        Routing one onto the other would invent a number, so the repair names them and
        leaves them, the same way it refuses a value with no evidence behind it.
        """
        source = self.SCRIPT.read_text(encoding="utf-8")
        assert "unmapped_fields" in source
        assert "unrecoverable field names" in source


class TestARunCanFindItsOwnCandidates:
    """A candidate belongs to the run that screened it, not to whoever captured the page.

    `register_url` deduplicates by content hash across the tenant, so a page an earlier
    run already captured comes back attached to *that* run. Keying candidates on the
    source therefore hid them: the run reported "1 pump model found" above a panel
    listing none, which reads exactly like finding nothing. Verified against the live
    database - the recovered candidate's page belonged to a batch from a previous run.
    """

    @pytest.mark.parametrize("kind", KINDS)
    def test_candidates_are_found_through_the_screening_job(self, kind):
        sql = str(discovery.candidate_query(kind, uuid.uuid4()))
        assert "ai_jobs.import_batch_id" in sql

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_source_link_remains_for_rows_written_before_jobs(self, kind):
        sql = str(discovery.candidate_query(kind, uuid.uuid4()))
        assert "sources.import_batch_id" in sql
        # Only as a fallback: a row with a job is judged by its job alone, or a source
        # captured here but screened by a later run would be claimed twice.
        assert "ai_job_id IS NULL" in sql

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_candidate_whose_page_was_reused_is_still_listed(self, kind):
        """The join has to be outer, or a null source drops the candidate entirely."""
        sql = str(discovery.candidate_query(kind, uuid.uuid4()))
        assert "LEFT OUTER JOIN sources" in sql
        assert "LEFT OUTER JOIN ai_jobs" in sql

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_candidate_of_another_kind_is_not_listed(self, kind):
        """One run screens one kind; a vendor candidate is not a pump model."""
        sql = str(discovery.candidate_query(kind, uuid.uuid4()))
        assert "extracted_entities.entity_type" in sql
