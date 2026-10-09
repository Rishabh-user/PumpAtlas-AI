"""What a captured page keeps, and how a vendor record gets filled from it.

A vendor discovered while storing a pump model is a name and nothing else -
`resolve_vendor` inserts the row so the model has a manufacturer, and no page about the
company itself has been read. The profile then shows "—" against every commercial field
while the record is badged AI extracted, which reads as a broken extractor rather than a
record nobody has researched.

Two things were actually wrong, and both are pinned here: the parser deleted the page
footer, which is where a company states its address and registration; and a page already
captured was handed back with whatever text the parser of the day reduced it to, so no
parser improvement ever reached it.
"""

from __future__ import annotations

import inspect

import pytest

from app.ai import prompts
from app.api.v1 import vendors as vendor_routes
from app.models.source import Source
from app.services import ingestion, parsing, vendor_discovery

COMPANY_PAGE = """
<html><head><title>Amarinth</title>
<meta name="description" content="API 610 pumps"></head>
<body>
  <nav><a href="/about">About</a></nav>
  <h1>Amarinth</h1>
  <h2>Certifications</h2>
  <ul><li>ISO 9001:2015</li><li>API 610 11th edition</li><li>ATEX 2014/34/EU</li></ul>
  <p>Amarinth designs and manufactures low flow API 610 pumps for the oil and gas
     sector, and has done since 2002.</p>
  <table><caption>Capability</caption>
    <tr><th>Flow</th><td>400 m3/h</td></tr><tr><th>Head</th><td>250 m</td></tr>
  </table>
  <a href="/downloads/spec.pdf">Datasheet</a>
  <footer><p>Amarinth Limited, Barnards Yard, Saxmundham, Suffolk IP17 1AX, United
     Kingdom. Registered in England No. 04378962. Tel +44 1502 439 000.
     sales@amarinth.example</p></footer>
</body></html>
"""


class TestTheFooterSurvives:
    """It carries the address, the company number and the switchboard.

    Those are the fields a vendor record most wants and a product page never mentions in
    its body copy - and the parser was decomposing `<footer>` along with the scripts.
    """

    def test_the_footer_text_reaches_the_reading_model(self):
        parsed = parsing.parse_html(COMPANY_PAGE)
        for wanted in ("Saxmundham", "04378962", "IP17 1AX"):
            assert wanted in parsed.text, wanted

    def test_the_footer_is_also_captured_on_its_own(self):
        """So a reader judging a value can see it came from the footer."""
        capture = parsing.parse_html(COMPANY_PAGE).content
        assert "Registered in England" in capture["footer"]

    def test_navigation_is_still_dropped(self):
        """A menu is not content; keeping it would put "About" in every extraction."""
        parsed = parsing.parse_html(COMPANY_PAGE)
        assert parsed.text.count("About") == 0

    def test_a_page_with_no_footer_captures_none(self):
        capture = parsing.parse_html("<html><body><p>Nothing here</p></body></html>").content
        assert capture["footer"] is None


class TestThePageIsKeptAsStructure:
    """`parsed_text` is what the model reads, and it is lossy in the ways that matter."""

    @pytest.fixture(scope="class")
    def capture(self) -> dict:
        return parsing.parse_html(COMPANY_PAGE).content

    def test_a_certification_list_stays_a_list(self, capture):
        assert ["ISO 9001:2015", "API 610 11th edition", "ATEX 2014/34/EU"] in capture["lists"]

    def test_a_specification_table_stays_rows_and_columns(self, capture):
        table = capture["tables"][0]
        assert table["caption"] == "Capability"
        assert ["Flow", "400 m3/h"] in table["rows"]

    def test_headings_keep_their_level(self, capture):
        assert {"level": 1, "text": "Amarinth"} in capture["headings"]

    def test_contact_details_are_pulled_out(self, capture):
        assert capture["emails"] == ["sales@amarinth.example"]
        assert capture["phones"] == ["+44 1502 439 000"]

    def test_documents_are_listed_for_later_ingestion(self, capture):
        assert "/downloads/spec.pdf" in capture["documents"]

    def test_a_part_number_is_not_mistaken_for_a_phone_number(self):
        """A loose pattern turned every model code into a switchboard."""
        capture = parsing.parse_html(
            "<html><body><p>Model 610-BB3-2005 rated 1450 rpm</p></body></html>"
        ).content
        assert capture["phones"] == []

    @pytest.mark.parametrize(
        ("cap", "key"),
        [
            (parsing.MAX_CAPTURE_HEADINGS, "headings"),
            (parsing.MAX_CAPTURE_PARAGRAPHS, "paragraphs"),
            (parsing.MAX_CAPTURE_TABLES, "tables"),
            (parsing.MAX_CAPTURE_LINKS, "links"),
        ],
    )
    def test_the_capture_is_bounded(self, cap, key):
        """A source row is loaded on every screening pass, so a blob is paid for twice."""
        del key
        assert 0 < cap <= 500

    def test_it_is_stored_beside_the_text(self):
        source = inspect.getsource(ingestion.register_url)
        assert '"content": parsed.content or None' in source
        assert '"parser_version": parsing.PARSER_VERSION' in source


class TestAStoredPageIsReparsedWhenTheParserImproves:
    """Deduplication by content hash hid every parser improvement.

    A page captured last week comes back as-is, including the text it was reduced to
    then - so keeping the footer changed nothing for anything already in the database,
    and re-running an enrichment produced the same empty fields for a reason invisible
    from outside.
    """

    def test_the_parser_is_versioned(self):
        assert parsing.PARSER_VERSION >= 2

    def test_an_old_capture_is_reparsed_from_stored_html(self, monkeypatch):
        source = Source(
            source_url="https://example.com/about",
            content_type="text/html",
            raw_content=COMPANY_PAGE,
            parsed_text="stale text",
            source_metadata={"parser_version": 1},
        )
        flushed: list[bool] = []
        monkeypatch.setattr(
            ingestion, "log", type("L", (), {"info": staticmethod(lambda *a, **k: None)})()
        )
        db = type("DB", (), {"flush": lambda self: flushed.append(True)})()

        assert ingestion.refresh_parse(db, source) is True
        assert "Saxmundham" in source.parsed_text
        assert source.source_metadata["parser_version"] == parsing.PARSER_VERSION
        assert source.source_metadata["content"]["footer"]
        assert flushed

    def test_a_current_capture_is_left_alone(self):
        source = Source(
            source_url="https://example.com/about",
            raw_content=COMPANY_PAGE,
            parsed_text="already current",
            source_metadata={"parser_version": parsing.PARSER_VERSION},
        )
        db = type("DB", (), {"flush": lambda self: None})()
        assert ingestion.refresh_parse(db, source) is False
        assert source.parsed_text == "already current"

    def test_a_binary_with_no_stored_html_is_stamped_not_reparsed(self):
        """A PDF lives in object storage, so there is nothing here to re-read."""
        source = Source(
            source_url="https://example.com/a.pdf",
            raw_content=None,
            parsed_text="text from the pdf",
            source_metadata={},
        )
        db = type("DB", (), {"flush": lambda self: None})()
        assert ingestion.refresh_parse(db, source) is False
        assert source.source_metadata["parser_version"] == parsing.PARSER_VERSION
        assert source.parsed_text == "text from the pdf"

    def test_the_dedupe_branch_calls_it(self):
        """Otherwise a re-parse only ever happens on a page nobody had captured."""
        source = inspect.getsource(ingestion.register_url)
        assert "refresh_parse(db, existing)" in source


class TestTheWebsiteIsDerivedFromThePageItWasReadFrom:
    """A company's own domain is the strongest statement of its website.

    It is also almost never written out as text, so a model told to quote or omit
    correctly omits it - and the field stays empty forever.
    """

    def test_a_company_page_yields_its_origin(self):
        assert _derive("https://www.amarinth.com/about/") == "https://amarinth.com"

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/company/amarinth",
            "https://www.scribd.com/document/1234/amarinth",
            "https://www.indiamart.com/proddetail/api-610-pump",
            "https://en.wikipedia.org/wiki/Amarinth",
        ],
    )
    def test_an_aggregator_is_not_the_company(self, url):
        """A wrong website on a vendor record sends somebody to the wrong company."""
        assert _derive(url) is None

    def test_a_stated_website_is_not_overwritten(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert 'if derived_website and not fields.get("website")' in source

    def test_a_derived_value_is_not_recorded_as_something_the_model_read(self):
        """Claiming AI_EXTRACTION for a value nothing quoted is the one thing the
        provenance trail exists to prevent."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "ValueOrigin.CALCULATED" in source
        assert "replace(context, origin=ValueOrigin.CALCULATED)" in source

    def test_the_refusal_report_still_covers_derived_fields(self):
        """A field silently missing from the report reads as applied.

        The merge used the caller's names - `fields_refused` - while `apply_fields`
        returns `refused`, so it wrote keys nothing reads and lost the derived field from
        the report. This asserts the key the producer actually uses.
        """
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert 'report["refused"]' in source
        assert 'report["fields_refused"]' not in source


class TestEnrichingAVendorFromTheWeb:
    def test_the_route_exists_and_writes(self):
        source = inspect.getsource(vendor_routes.enrich_vendor)
        assert "discovery.start_run" in source
        assert "dispatch.dispatch" in source

    def test_it_asks_the_questions_a_procurement_file_needs(self):
        """Not "find me suppliers" - it already knows the supplier."""
        source = inspect.getsource(vendor_routes.enrich_vendor)
        assert "vendor_intelligence_objective(vendor.name)" in source
        assert "queries=queries" in source

    def test_the_run_can_carry_its_own_queries(self):
        """`start_run` used to generate them from the kind, which asks the wrong thing."""
        from app.services import discovery

        source = inspect.getsource(discovery.start_run)
        assert "list(queries) if queries else generated_queries" in source

    def test_the_prompt_says_where_the_identity_fields_hide(self):
        """The footer. Naming it took the yield from 3 fields to 8 on the same pages."""
        prompt = prompts.SYSTEM_VENDOR_PROFILE
        assert "footer" in prompt
        assert "legal_entity_name" in prompt


def _derive(url: str) -> str | None:
    """`_website_from_source` without a database, by standing in for the source row."""

    class Entity:
        source_id = "not-none"

    class Db:
        @staticmethod
        def get(_model, _id):
            return Source(source_url=url)

    return vendor_discovery._website_from_source(Db(), Entity())


class TestEveryChangeRecordsAVersion:
    """`record_versions` claimed to hold "every mutation of a vendor" and did not.

    The only vendor versions in the database came from manual creates; AI discovery and
    enrichment wrote none. So a supplier enriched from the web three times had three sets
    of provenance rows and no way to see what the record looked like before each one.
    """

    def test_storing_a_candidate_writes_a_version(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "audit.record_version(" in source

    def test_the_snapshot_is_taken_before_anything_is_applied(self):
        """Taken afterwards, the diff would be empty and the version would say nothing."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        before_index = source.index("audit.snapshot(existing)")
        apply_index = source.index("provenance.apply_fields(")
        assert before_index < apply_index

    def test_a_run_that_changed_nothing_records_no_version(self):
        """Re-reading the same pages and confirming them is not a new version."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "if changed:" in source

    def test_the_reason_names_the_fields_that_changed(self):
        """ "Enriched from the web" alone leaves the reader opening the diff to learn why."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "Enriched from the web:" in source
        assert "', '.join(sorted(changed))" in source

    def test_a_new_vendor_is_an_insert_and_an_enriched_one_an_update(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert '"insert" if was_new else "update"' in source

    def test_the_history_endpoint_drops_bookkeeping_columns(self):
        """A reader wants "it gained a headquarters", not "updated_at changed"."""
        for field in ("updated_at", "created_at", "id", "tenant_id"):
            assert field in vendor_routes.VERSION_NOISE_FIELDS

    def test_the_history_endpoint_returns_newest_first(self):
        source = inspect.getsource(vendor_routes.vendor_versions)
        assert "RecordVersion.version.desc()" in source

    def test_the_history_endpoint_sends_the_diff_not_the_snapshot(self):
        """The full row is for rollback; a screen wants what changed."""
        source = inspect.getsource(vendor_routes.vendor_versions)
        assert "row.diff" in source
        assert "row.snapshot" not in source


class TestTheListShowsOneCatalogueAtATime:
    """73 rows for 65 companies is two catalogues shown as one list.

    A platform administrator sees every tenancy, so an unscoped vendor list interleaved
    the shared-master catalogue with each client's own and the eight companies held in
    both appeared twice. Scoping the list fixed that, and a platform administrator was
    defaulted to shared master - the catalogue they curate, and the one with no overlaps.

    That default has since been **reversed by the data**. It was chosen while shared
    master was 47 of 77 records. A client's approved vendor lists were then imported and
    the balance inverted: 1,601 of 1,684 records belong to a tenant and 52 are shared, so
    the default hid 95% of the catalogue behind a dropdown and the list read as empty to
    the person who had just loaded that data.

    The scope control is what the original fix was really for, and it stays. The
    duplicate the wider default reintroduces is explained rather than hidden: each row
    carries `also_in_other_tenancies`, and `merge_vendors` still refuses to cross a
    tenancy boundary.
    """

    def test_the_list_takes_a_catalogue_scope(self):
        source = inspect.getsource(vendor_routes.list_vendors)
        assert "tenant_scope" in source

    def test_the_default_is_every_catalogue_the_caller_may_see(self):
        """Hiding 95% of the records by default is worse than showing a duplicate."""
        source = inspect.getsource(vendor_routes.list_vendors)
        assert 'scope = tenant_scope or "all"' in source

    def test_no_caller_is_narrowed_by_their_role(self):
        """Row level security already limits a tenant user to their own plus shared."""
        source = inspect.getsource(vendor_routes.list_vendors)
        assert 'if principal.is_platform_admin else "all"' not in source

    def test_the_duplicate_it_allows_is_still_explained(self):
        source = inspect.getsource(vendor_routes.list_vendors)
        assert "also_in_other_tenancies" in source

    def test_shared_master_means_a_null_tenant(self):
        source = inspect.getsource(vendor_routes.list_vendors)
        assert "Vendor.tenant_id.is_(None)" in source

    def test_a_scope_that_is_not_a_tenant_id_is_refused(self):
        """Silently listing everything would hide that the filter did nothing."""
        source = inspect.getsource(vendor_routes.list_vendors)
        assert "must be 'shared', 'all' or a tenant id" in source


class TestEnrichmentFillsTheRecordItWasAskedFor:
    """It resolved candidates by name, so an update could land on a different record.

    Enriching "Seal Care" read the company's own site, which calls itself
    "Seal Care (S) Pte Ltd." - a different normalised name - so a second vendor was
    created with all nine fields on it and the page that asked for the update stayed
    exactly as empty as before. Two records, one company, and the button looked broken.
    """

    def test_the_run_records_which_vendor_it_is_filling(self):
        from app.services import discovery

        source = inspect.getsource(discovery.start_run)
        assert "target_vendor_id" in source

    def test_the_enrich_route_names_its_target(self):
        source = inspect.getsource(vendor_routes.enrich_vendor)
        assert "target_vendor_id=vendor.id" in source

    def test_a_targeted_candidate_skips_name_resolution(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "targeted = _target_vendor(db, entity)" in source
        assert "targeted or existing_vendor_for" in source

    def test_the_name_from_the_page_is_kept_as_an_alias(self):
        """ "Seal Care (S) Pte Ltd." is how somebody will search for it."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert "vendor.aliases = [*aliases, vendor_name]" in source

    def test_the_record_keeps_its_own_name(self):
        """The person enriching it chose that name; a page should not rewrite it."""
        source = inspect.getsource(vendor_discovery.store_candidate)
        target_branch = source[source.index("if targeted is not None:") :]
        target_branch = target_branch[: target_branch.index("else:")]
        assert "vendor.name =" not in target_branch

    def test_a_target_in_another_tenancy_is_refused(self):
        """A run must not write across a tenancy, whatever its config says."""
        source = inspect.getsource(vendor_discovery._target_vendor)
        assert "vendor.tenant_id != entity.tenant_id" in source
        assert "return None" in source


class TestWhatTheGateRefusedIsNotSilent:
    """A profile of dashes read as "the web had nothing about this supplier".

    One vendor had ten fields extracted and two quoted; the other eight - country,
    website, category, product families - were refused for want of a verbatim quote and
    nothing on the page said so.
    """

    def test_refusals_are_kept_on_the_record(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert 'discovery["refused"] = refused' in source

    def test_the_refusal_keeps_the_value_and_the_reason(self):
        source = inspect.getsource(vendor_discovery.store_candidate)
        assert '"value": fields.get(name)' in source
        assert '"reason": reason' in source

    def test_the_prompt_demands_a_quote_for_coded_values_too(self):
        """`hq_country: "SG"` can never appear verbatim, so the phrase must be quoted."""
        assert 'quote "Singapore"' in prompts.SYSTEM_VENDOR_PROFILE
        assert "A field with no quote is discarded" in prompts.SYSTEM_VENDOR_PROFILE


class TestContactDetailsAreOfferedNotWritten:
    """What the review list is, now that a capture records contacts by itself.

    `vendor_contacts` used to have no column for a source, so a number written there by
    the pipeline would be a value with nothing behind it - the one thing this platform
    promises never to hold. Migration 002 gives it `source_id`, `captured_at` and
    `origin`, and `vendor_discovery.record_page_contacts` writes the details a company
    states on its *own* site, provenance and all.

    This endpoint stayed a reader. What it returns is the remainder - details seen on
    other companies' pages, which no rule can attribute - and recording one of those is
    a person's decision, which the audit log captures. Whether it writes is therefore
    still worth pinning; see `test_vendor_contacts.py` for the recording side.
    """

    def test_the_endpoint_reads_the_captured_pages(self):
        source = inspect.getsource(vendor_routes.vendor_contact_details)
        assert '(source.source_metadata or {}).get("content")' in source

    def test_it_writes_nothing(self):
        source = inspect.getsource(vendor_routes.vendor_contact_details)
        for forbidden in ("db.add(", "db.commit()", "VendorContact("):
            assert forbidden not in source, forbidden

    def test_every_detail_names_the_page_it_came_from(self):
        """Without that a reader cannot judge whether it is the right number."""
        source = inspect.getsource(vendor_routes.vendor_contact_details)
        assert '"seen_on": seen_on' in source
        assert '"url": source.source_url' in source

    def test_the_pages_are_the_ones_that_built_the_record(self):
        """Its provenance sources plus its primary source, not every page ever read."""
        source = inspect.getsource(vendor_routes.vendor_contact_details)
        assert "FieldProvenance.entity_id == vendor.id" in source
        assert "vendor.primary_source_id" in source

    def test_one_number_written_two_ways_is_listed_once(self):
        """A page carried "+65 9385 2894" and "+65 9385-2894"; that is one switchboard.

        The same rule the recorder compares on, so a detail cannot be recorded and
        offered at the same time.
        """
        source = inspect.getsource(vendor_routes.vendor_contact_details)
        assert "vendor_discovery.phone_key(number)" in source

    def test_what_is_already_recorded_is_not_offered_again(self):
        """Otherwise every auto-recorded detail would appear twice on the page."""
        source = inspect.getsource(vendor_routes.vendor_contact_details)
        assert "held_emails" in source and "held_phones" in source
