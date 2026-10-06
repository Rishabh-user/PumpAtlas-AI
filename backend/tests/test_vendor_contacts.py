"""Contact details taken off a captured page.

A person had to click "Add" on every email address and phone number the crawler saw,
because `vendor_contacts` had no column naming a source - and an untraceable phone
number in a procurement file is the one thing this platform promises never to hold.
Migration 002 gives the table `source_id`, `captured_at` and `origin`, so the details a
company states on its own site are now recorded as they are found.

"Its own site" is the whole of the safety here. A supplier's page routinely lists its
distributors: one Amarinth page carried `global@mopartners.global` and a Brazilian
number belonging to a partner. Recording those would put another company's switchboard
in this company's file, so they stay behind a click.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.sql.dml import Insert

from app.api.v1 import vendors as vendor_routes
from app.models.enums import ValueOrigin
from app.models.source import Source
from app.models.vendor import Vendor
from app.services import vendor_discovery

CAPTURED = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)


def _source(url: str, *, emails=(), phones=()) -> Source:
    return Source(
        id=uuid.uuid4(),
        source_url=url,
        captured_at=CAPTURED,
        source_metadata={"content": {"emails": list(emails), "phones": list(phones)}},
    )


def _vendor(website: str | None = "https://www.amarinth.com/") -> Vendor:
    return Vendor(id=uuid.uuid4(), name="Amarinth", website=website, tenant_id=None)


class _Session:
    """Just enough session for the recording path: rows held, and rows written.

    Both directions go through Core statements rather than the ORM, so that a database
    still waiting for migration 002 is never asked about a column it has not got; the
    fake speaks the same language.
    """

    def __init__(self, existing: list[dict] | None = None):
        self.existing = existing or []
        self.added: list[dict] = []

    def execute(self, statement):
        if isinstance(statement, Insert):
            self.added.append(dict(statement.compile().params))
            return None
        return _Rows(self.existing)


@pytest.fixture(autouse=True)
def _columns_present(monkeypatch):
    """Pretend migration 002 is applied; the guard itself is tested separately."""
    monkeypatch.setattr(vendor_discovery, "_CONTACT_PROVENANCE_READY", True)


class TestOnlyTheCompanysOwnPages:
    def test_details_from_the_companys_own_domain_are_recorded(self):
        db = _Session()
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor(),
            _source(
                "https://www.amarinth.com/contact",
                emails=["sales@amarinth.com"],
                phones=["+44 (0)1394 462 120", "+44 (0)1394 462 130"],
            ),
        )
        assert added == 3
        assert {row["email"] for row in db.added if row.get("email")} == {
            "sales@amarinth.com"
        }
        assert {row["phone"] for row in db.added if row.get("phone")} == {
            "+44 (0)1394 462 120",
            "+44 (0)1394 462 130",
        }

    def test_a_partners_switchboard_is_left_for_a_person(self):
        """The real capture that made this rule necessary."""
        db = _Session()
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor(),
            _source(
                "https://mopartners.global/representation",
                emails=["global@mopartners.global"],
                phones=["+55 (21) 3239 4850"],
            ),
        )
        assert added == 0
        assert db.added == []

    def test_www_is_not_a_different_company(self):
        db = _Session()
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor("https://amarinth.com"),
            _source("https://www.amarinth.com/contact", emails=["sales@amarinth.com"]),
        )
        assert added == 1

    def test_a_vendor_with_no_website_yet_takes_the_page_it_came_from(self):
        """The page that produced the record is the best evidence of who it belongs to."""
        db = _Session()
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor(None),
            _source("https://sealcaresg.com/", phones=["+65 6300 3654"]),
        )
        assert added == 1


class TestEachContactSaysWhereItCameFrom:
    def test_the_page_the_date_and_the_hand_that_wrote_it(self):
        db = _Session()
        source = _source(
            "https://www.amarinth.com/contact", emails=["sales@amarinth.com"]
        )
        vendor_discovery.record_page_contacts(db, _vendor(), source)

        row = db.added[0]
        assert row["source_id"] == source.id
        assert row["captured_at"] == CAPTURED
        assert row["origin"] == ValueOrigin.AI_EXTRACTION.value

    def test_nothing_is_written_before_the_columns_exist(self, monkeypatch):
        """Until the migration is applied there is nowhere to put the provenance."""
        monkeypatch.setattr(vendor_discovery, "_CONTACT_PROVENANCE_READY", False)
        db = _Session()
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor(),
            _source("https://www.amarinth.com/", emails=["sales@amarinth.com"]),
        )
        assert added == 0
        assert db.added == []


class TestOneSwitchboardIsRecordedOnce:
    def test_an_address_already_held_is_not_added_again(self):
        db = _Session([{"email": "Sales@Amarinth.com", "phone": None}])
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor(),
            _source("https://www.amarinth.com/", emails=["sales@amarinth.com"]),
        )
        assert added == 0

    def test_the_same_number_spelled_differently_is_the_same_number(self):
        """One page listed the same Seal Care line with a space and with a hyphen."""
        db = _Session([{"email": None, "phone": "+65 9385 2894"}])
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor("https://sealcaresg.com"),
            _source(
                "https://sealcaresg.com/contact",
                phones=["+65 9385-2894", "+65 9853 3845"],
            ),
        )
        assert added == 1
        assert db.added[0]["phone"] == "+65 9853 3845"

    def test_a_page_repeating_itself_yields_one_contact(self):
        db = _Session()
        added = vendor_discovery.record_page_contacts(
            db,
            _vendor(),
            _source(
                "https://www.amarinth.com/",
                emails=["sales@amarinth.com", "SALES@amarinth.com"],
            ),
        )
        assert added == 1


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def mappings(self):
        return self.rows


class _EndpointSession:
    """Answers the endpoint's reads: the vendor, its held contacts, then its sources.

    Contacts arrive through `contact_rows`, which reads columns rather than entities so
    that a database without migration 002 still answers - so they come back as mappings,
    the way the endpoint sees them.
    """

    def __init__(self, vendor, held, source_ids, sources):
        self.vendor = vendor
        self.held = held
        self.answers = [source_ids, sources]

    def get(self, _model, _id):
        return self.vendor

    def execute(self, _statement):
        return _Rows(
            [
                {
                    "id": row.get("id"),
                    "email": row.get("email"),
                    "phone": row.get("phone"),
                    "source_id": None,
                    "captured_at": None,
                    "origin": None,
                }
                for row in self.held
            ]
        )

    def scalars(self, _statement):
        return _Rows(self.answers.pop(0))


class TestTheReviewListShowsOnlyWhatIsLeft:
    """Anything already recorded must not be offered again, or every auto-added detail
    would appear twice on the page - once as a contact, once as a suggestion."""

    def _call(self, held):
        source = _source(
            "https://www.amarinth.com/contact",
            emails=["sales@amarinth.com", "export@amarinth.com"],
            phones=["+44 (0)1394 462 120"],
        )
        db = _EndpointSession(_vendor(), held, [source.id], [source])
        return vendor_routes.vendor_contact_details(uuid.uuid4(), db)

    def test_a_recorded_address_is_dropped(self):
        result = self._call([{"email": "SALES@amarinth.com"}])
        assert [item["value"] for item in result["emails"]] == ["export@amarinth.com"]

    def test_a_recorded_number_is_dropped_however_it_was_spaced(self):
        result = self._call([{"phone": "+44 1394 462120"}])
        assert result["phones"] == []

    def test_what_is_left_says_whether_the_page_was_the_companys_own(self):
        result = self._call([])
        assert all(item["seen_on"]["same_domain"] for item in result["emails"])


class TestOneTelephoneWrittenTwoWays:
    """`phone_key` is what both the recorder and the review list compare on."""

    def test_a_british_trunk_zero_is_not_part_of_the_number(self):
        assert vendor_discovery.phone_key("+44 (0)1394 462 120") == (
            vendor_discovery.phone_key("+44 1394 462120")
        )

    def test_punctuation_and_spacing_do_not_make_a_new_line(self):
        assert vendor_discovery.phone_key("+65 9385-2894") == (
            vendor_discovery.phone_key("+65 9385 2894")
        )

    def test_two_different_extensions_stay_different(self):
        assert vendor_discovery.phone_key("+44 1394 462120") != (
            vendor_discovery.phone_key("+44 1394 462130")
        )

    def test_a_zero_that_is_a_digit_is_kept(self):
        """Only a bracketed zero is a trunk code."""
        assert vendor_discovery.phone_key("+1 (202) 555 0100") == "12025550100"


class TestTheAppReadsTheColumnsTheDatabaseHas:
    """Declaring a column the database lacks takes out every page that lists contacts.

    An ORM entity load asks for every mapped column, so between adding `source_id` to
    the model and applying migration 002 the vendor profile answered
    "column vendor_contacts.source_id does not exist" - a 500 on the page this work was
    meant to improve. `contact_rows` reads the columns the catalogue reports instead.
    """

    class _ColumnSession:
        def __init__(self):
            self.asked: list[str] = []

        def execute(self, statement):
            self.asked = [column.name for column in statement.selected_columns]
            return _Rows([])

    def _ask(self, monkeypatch, *, migrated: bool):
        monkeypatch.setattr(vendor_discovery, "_CONTACT_PROVENANCE_READY", migrated)
        db = self._ColumnSession()
        vendor_discovery.contact_rows(db, uuid.uuid4())
        return db.asked

    def test_an_unmigrated_database_is_not_asked_for_the_new_columns(self, monkeypatch):
        asked = self._ask(monkeypatch, migrated=False)
        assert not vendor_discovery.CONTACT_PROVENANCE_COLUMNS & set(asked)
        assert "email" in asked and "phone" in asked

    def test_a_migrated_database_is(self, monkeypatch):
        asked = self._ask(monkeypatch, migrated=True)
        assert vendor_discovery.CONTACT_PROVENANCE_COLUMNS <= set(asked)

    def test_the_shape_is_the_same_either_way(self, monkeypatch):
        """So no caller has to know which state the database is in."""
        monkeypatch.setattr(vendor_discovery, "_CONTACT_PROVENANCE_READY", False)

        class _OneRow(self._ColumnSession):
            def execute(self, statement):
                super().execute(statement)
                return _Rows([{"id": uuid.uuid4(), "email": "a@b.com", "phone": None}])

        row = vendor_discovery.contact_rows(_OneRow(), uuid.uuid4())[0]
        assert row["origin"] is None
        assert row["source_id"] is None
        assert row["email"] == "a@b.com"


class TestProvenanceIsNotSomethingAClientCanClaim:
    def test_a_posted_contact_cannot_name_a_page_it_was_never_on(self):
        """Provenance that says nothing true is worse than none at all."""
        from app.schemas.entities import VendorContactIn

        assert not vendor_discovery.CONTACT_PROVENANCE_COLUMNS & set(
            VendorContactIn.model_fields
        )

    def test_a_person_can_still_record_the_details_themselves(self):
        from app.schemas.entities import VendorContactIn

        assert {"email", "phone", "full_name"} <= set(VendorContactIn.model_fields)


class TestADerivedWebsiteHasToLookLikeTheCompany:
    """A record built from a page does not make that page's owner the company.

    The audit of the live data found a Flowserve record whose only captured page was
    `abset.com` - a distributor's catalogue listing Flowserve pumps. Writing that as
    Flowserve's website would put a buyer through to the wrong company, the same mistake
    the contact-domain rule exists to prevent.
    """

    def test_a_distributors_catalogue_is_not_the_manufacturers_site(self):
        assert (
            vendor_discovery.website_from_url("https://abset.com/pumps", "Flowserve")
            is None
        )

    def test_the_companys_own_site_is(self):
        assert (
            vendor_discovery.website_from_url("https://www.flowserve.com/", "Flowserve")
            == "https://flowserve.com"
        )

    def test_a_domain_longer_than_the_name_still_matches(self):
        """Apollo's site is apollo-goessnitz.de."""
        assert (
            vendor_discovery.website_from_url(
                "https://www.apollo-goessnitz.de/en/", "Apollo"
            )
            == "https://apollo-goessnitz.de"
        )

    def test_a_domain_shorter_than_the_name_still_matches(self):
        """Dickow Pump Co. writes dickow.com."""
        assert (
            vendor_discovery.website_from_url(
                "https://pumpcatalog.dickow.com/", "Dickow Pump Co."
            )
            == "https://pumpcatalog.dickow.com"
        )

    def test_a_two_part_suffix_is_not_mistaken_for_the_name(self):
        assert vendor_discovery.domain_name_part("pumpi.com.mk") == "pumpi"

    def test_a_directory_is_refused_whatever_the_name(self):
        assert (
            vendor_discovery.website_from_url(
                "https://www.linkedin.com/company/sulzer", "Sulzer"
            )
            is None
        )

    def test_a_short_name_is_not_matched_on_coincidence(self):
        """Below four characters, a substring says nothing about ownership."""
        assert vendor_discovery.domain_matches_name("ksb-pumps.de", "KSB") is False

    def test_without_a_name_the_old_behaviour_stands(self):
        """The candidate path passed no name before this guard existed."""
        assert (
            vendor_discovery.website_from_url("https://abset.com/pumps")
            == "https://abset.com"
        )
