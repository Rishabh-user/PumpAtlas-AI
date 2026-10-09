"""Reading a client's documents into the tables that hold their facts.

Three document types were imported - a signed approved suppliers list, a project package
list, and five SAP vendor-master exports - and every column survived, inside
`vendors.extra` as JSON. These pin the move from that holding pen into
`vendor_approvals`, `vendor_identifiers`, `vendor_contacts` and the identity columns,
because the move has to be exact: a company's tax number read into the wrong field, or a
"No" read as a purchasing block, is worse than leaving it in JSON.

The payload shapes here are taken from a real record (ABB Pte Ltd), headings included.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.vendor import Vendor
from app.services import client_records


def _vendor(extra: dict, **kwargs) -> Vendor:
    return Vendor(name=kwargs.pop("name", "ABB Pte Ltd"), extra=extra, **kwargs)


SAP_COLUMNS = {
    "CoCd": "G040",
    "Name 1": "ABB PTE LTD",
    "Name 2": "ABB PTE LTD",
    "Region": "Singapore",
    "Vendor": "10085880",
    "Street 2": "NO 2 AYER RAJAH CRESCENT",
    "Telephone": "6567765711",
    "Country Key": "Singapore",
    "E-Mail Address": "Juraimi.Jahya@sg.abb.com",
    "Vendor Cr. Date": "2018-05-28 00:00:00",
    "Central posting block": "No",
    "Centrally imposed purchasing block": "No",
    "Region (State, Province, County)": "Singapore",
}


def _sap(columns: dict | None = None, **identifiers) -> dict:
    return {
        "sap": {
            "rows": [{"columns": {**SAP_COLUMNS, **(columns or {})}, "vendor_no": "10085880"}],
            "vendor_numbers": ["10085880"],
            "identifiers": {
                "currency": "United States Dollar",
                "gst_class": "Registered",
                **identifiers,
            },
        }
    }


class TestApprovalsAreOnePerStatement:
    def test_a_package_on_a_project_becomes_a_row(self):
        vendor = _vendor(
            {
                "approved_packages": [
                    {"project": "ONGC KG-DWN-98/2", "package": "Sea Water Injection Pumps",
                     "country": "UK"},
                ],
                "source_documents": ["20171-SPOG-14100-PM-LS-0002 D0.pdf"],
            }
        )
        [approval] = client_records.approvals_for(vendor)
        assert approval["project"] == "ONGC KG-DWN-98/2"
        assert approval["package"] == "Sea Water Injection Pumps"
        assert approval["document_reference"] == "20171-SPOG-14100-PM-LS-0002 D0.pdf"

    def test_the_country_is_kept_as_the_document_wrote_it(self):
        """"UK / Brazil / India" is what the signed list says, and it is the authority."""
        vendor = _vendor(
            {"approved_packages": [
                {"project": "P", "package": "Crude Transfer Pump", "country": "UK / Brazil / India"}
            ]}
        )
        assert client_records.approvals_for(vendor)[0]["approved_country"] == "UK / Brazil / India"

    def test_the_same_package_twice_is_one_approval(self):
        vendor = _vendor(
            {"approved_packages": [
                {"project": "P", "package": "Boilers", "country": "UK"},
                {"project": "P", "package": "Boilers", "country": "Italy"},
            ]}
        )
        assert len(client_records.approvals_for(vendor)) == 1

    def test_an_entry_naming_no_package_is_not_an_approval(self):
        vendor = _vendor({"approved_packages": [{"project": "P", "country": "UK"}]})
        assert client_records.approvals_for(vendor) == []

    def test_two_documents_leave_the_reference_unset(self):
        """Attributing a statement to one of two documents would be a guess."""
        vendor = _vendor(
            {
                "approved_packages": [{"project": "P", "package": "Boilers"}],
                "source_documents": ["a.pdf", "b.xlsx"],
            }
        )
        assert client_records.approvals_for(vendor)[0]["document_reference"] is None


class TestIdentifiersAreSchemeKeyed:
    def test_the_sap_number_is_an_identifier(self):
        vendor = _vendor(_sap())
        schemes = {e["scheme"]: e["value"] for e in client_records.identifiers_for(vendor)}
        assert schemes["sap_vendor_no"] == "10085880"

    def test_tax_numbers_are_carried_under_their_scheme(self):
        vendor = _vendor(_sap(gst="06AAACD2199L1ZG", pan="1240941X", msme="AP-03-0000278"))
        schemes = {e["scheme"]: e["value"] for e in client_records.identifiers_for(vendor)}
        assert schemes["gst"] == "06AAACD2199L1ZG"
        assert schemes["pan"] == "1240941X"
        assert schemes["msme"] == "AP-03-0000278"

    def test_a_currency_and_a_tax_class_are_not_identifiers(self):
        vendor = _vendor(_sap())
        schemes = {entry["scheme"] for entry in client_records.identifiers_for(vendor)}
        assert "currency" not in schemes
        assert "gst_class" not in schemes

    def test_bank_details_are_never_carried(self):
        """Payment instructions are a liability, and this platform has no use for them."""
        vendor = _vendor(_sap(bank_account="00000035140796691", bank_key="BARB0SIRPMR",
                              bank_name="PUNJAB NATIONAL BANK"))
        values = {entry["value"] for entry in client_records.identifiers_for(vendor)}
        assert "00000035140796691" not in values
        assert not {"bank_account", "bank_key", "bank_name"} & set(
            client_records.IDENTIFIER_SCHEMES
        )

    @pytest.mark.parametrize("junk", ["NA", "N/A", " none ", "-", "000000000000000"])
    def test_a_spreadsheet_saying_nothing_is_not_an_identifier(self, junk):
        """`ART Number` is "NA" on its one populated row; VAT is fifteen zeros on nine."""
        vendor = _vendor(_sap(vat=junk))
        assert all(e["scheme"] != "vat" for e in client_records.identifiers_for(vendor))

    def test_the_same_number_is_not_recorded_twice(self):
        vendor = _vendor(_sap(gst="X1"))
        first = client_records.identifiers_for(vendor)
        assert len(first) == len({(e["scheme"], e["value"]) for e in first})


class TestIdentityReadsTheAddressApart:
    def test_the_street_lines_become_one_address(self):
        vendor = _vendor(_sap({"Street 2": "237 PANDAN LOOP", "Street 3": "#04-07"}))
        assert client_records.identity_for(vendor)["address_line"] == "237 PANDAN LOOP, #04-07"

    def test_the_state_comes_from_the_long_heading_or_the_short_one(self):
        vendor = _vendor(_sap({"Region (State, Province, County)": "Aberdeenshire"}))
        assert client_records.identity_for(vendor)["state_region"] == "Aberdeenshire"

        fallback = _vendor(_sap({"Region (State, Province, County)": None, "Region": "Selangor"}))
        assert client_records.identity_for(fallback)["state_region"] == "Selangor"

    def test_the_account_opening_date_is_read_from_the_text(self):
        """SAP exports it as "2018-05-28 00:00:00", and JSON keeps it a string."""
        assert client_records.identity_for(_vendor(_sap()))["client_since"] == date(2018, 5, 28)

    def test_a_repeated_name_is_not_a_legal_entity_name(self):
        """Name 2 repeats Name 1 on most rows; a repeat states nothing."""
        assert "legal_entity_name" not in client_records.identity_for(_vendor(_sap()))

    def test_a_different_second_name_is(self):
        vendor = _vendor(_sap({"Name 2": "ABB Singapore Private Limited"}))
        identity = client_records.identity_for(vendor)
        assert identity["legal_entity_name"] == "ABB Singapore Private Limited"

    def test_no_means_not_blocked(self):
        """Every row carries "No"; reading that as a flag would bar 2,534 suppliers."""
        assert client_records.identity_for(_vendor(_sap())).get("is_purchasing_blocked") is None

    def test_yes_means_blocked_and_says_which_column_said_so(self):
        vendor = _vendor(_sap({"Centrally imposed purchasing block": "Yes"}))
        identity = client_records.identity_for(vendor)
        assert identity["is_purchasing_blocked"] is True
        assert "purchasing block" in identity["purchasing_block_note"]

    def test_a_vendor_with_no_sap_row_yields_nothing(self):
        assert client_records.identity_for(_vendor({})) == {}


class TestContactsComeOutOfTheBlob:
    def test_an_entry_becomes_a_contact(self):
        vendor = _vendor(
            {"contacts": [{"role": "commercial", "email": "a@b.com", "phone": "6567765711",
                           "company_name": "ABB PTE LTD"}]}
        )
        [contact] = client_records.contacts_for(vendor)
        assert contact["email"] == "a@b.com"
        assert contact["phone"] == "6567765711"
        assert contact["company_name"] == "ABB PTE LTD"

    def test_an_entry_with_neither_address_nor_number_is_not_a_contact(self):
        vendor = _vendor({"contacts": [{"role": "commercial", "company_name": "X"}]})
        assert client_records.contacts_for(vendor) == []

    def test_the_same_person_listed_twice_is_one_contact(self):
        vendor = _vendor(
            {"contacts": [
                {"email": "A@B.com", "phone": "65 6776 5711"},
                {"email": "a@b.com", "phone": "6567765711"},
            ]}
        )
        assert len(client_records.contacts_for(vendor)) == 1


class TestNothingIsWrittenBeforeTheSchemaIsReady:
    def test_the_sync_is_skipped_until_migration_003(self, monkeypatch):
        monkeypatch.setattr(client_records, "_READY", False)

        class _Db:
            def scalars(self, _statement):
                raise AssertionError("must not query before the tables exist")

        counts = client_records.sync_vendor(_Db(), _vendor(_sap()))
        assert counts == {"approvals": 0, "identifiers": 0, "contacts": 0, "fields": 0}


class TestTheBatchLoadReplacesPerVendorQueries:
    """Two queries per vendor across 1,684 vendors is 3,368 round trips to a database
    300ms away - about seventeen minutes of waiting to learn that nothing is there yet."""

    def test_a_preloaded_set_is_used_instead_of_querying(self, monkeypatch):
        monkeypatch.setattr(client_records, "_READY", True)
        monkeypatch.setattr(client_records, "_sync_contacts", lambda *a, **k: 0)

        vendor = _vendor(
            {"approved_packages": [{"project": "P", "package": "Boilers"}]},
        )
        added: list = []

        class _Db:
            def scalars(self, _statement):
                raise AssertionError("should not query when `held` is supplied")

            def add(self, row):
                added.append(row)

        counts = client_records.sync_vendor(_Db(), vendor, held=(set(), set()))
        assert counts["approvals"] == 1
        assert len(added) == 1

    def test_an_approval_already_held_is_not_written_again(self, monkeypatch):
        monkeypatch.setattr(client_records, "_READY", True)
        monkeypatch.setattr(client_records, "_sync_contacts", lambda *a, **k: 0)

        vendor = _vendor({"approved_packages": [{"project": "P", "package": "Boilers"}]})

        class _Db:
            def add(self, row):
                raise AssertionError("already held")

        held = ({(vendor.id, "P", "Boilers")}, set())
        assert client_records.sync_vendor(_Db(), vendor, held=held)["approvals"] == 0

    def test_the_same_vendor_twice_in_one_run_writes_once(self, monkeypatch):
        """The batch set is updated as it goes, or a repeated name duplicates the row."""
        monkeypatch.setattr(client_records, "_READY", True)
        monkeypatch.setattr(client_records, "_sync_contacts", lambda *a, **k: 0)

        vendor = _vendor({"approved_packages": [{"project": "P", "package": "Boilers"}]})
        held = (set(), set())

        class _Db:
            def __init__(self):
                self.rows = []

            def add(self, row):
                self.rows.append(row)

        db = _Db()
        client_records.sync_vendor(db, vendor, held=held)
        client_records.sync_vendor(db, vendor, held=held)
        assert len(db.rows) == 1


class TestTheListEndpointSurvivesAnUnmigratedDatabase:
    """A deferred column protects an entity load and nothing else.

    `/vendors` returned 500 twice over after migration 003's columns were declared, for
    two different reasons, and neither was the entity load the deferral was chosen to
    protect:

    * `VendorOut` is built from the table, so serialising a row touched every field -
      which loaded each deferred column and failed on a database without them;
    * the count wrapped `select(Vendor)` in a subquery, and a subquery materialises every
      mapped column inside it, deferred or not.

    Both are pinned here because the failure is invisible until a request arrives: the
    tests pass, the build passes, and the page is down.
    """

    def test_the_list_response_model_leaves_the_new_columns_out(self):
        from app.models.vendor import MIGRATION_003_COLUMNS
        from app.schemas.entities import VendorOut

        assert not MIGRATION_003_COLUMNS & set(VendorOut.model_fields)

    def test_the_names_are_declared_once(self):
        """Two lists that can disagree is how half of them get missed."""
        from app.models.vendor import MIGRATION_003_COLUMNS

        assert client_records.MIGRATION_003_VENDOR_COLUMNS is MIGRATION_003_COLUMNS

    def test_every_deferred_column_is_in_the_list(self):
        """A column added later and left out of the set reintroduces the 500."""
        from sqlalchemy import inspect as sa_inspect

        from app.models.vendor import MIGRATION_003_COLUMNS, Vendor

        mapper = sa_inspect(Vendor)
        deferred = {
            name
            for name, attribute in mapper.column_attrs.items()
            if getattr(attribute, "deferred", False)
        }
        assert deferred == set(MIGRATION_003_COLUMNS)

    def test_the_count_does_not_select_the_entity(self):
        import inspect

        from app.api.v1 import vendors as routes

        source = inspect.getsource(routes.list_vendors)
        assert "with_only_columns(func.count(Vendor.id)" in source
        assert "select_from(stmt.subquery())" not in source


class TestOneProductLinePerPackage:
    """Two documents spell the same package differently and produced two records.

    The ONGC signed list says "Firewater Pump"; the Kikeh list says "FIRE WATER PUMP".
    Framo AS ended up holding both as separate product lines for the one piece of
    equipment, and the same split put "Flowserve unspecified line" beside "Flow Serve
    unspecified line".
    """

    def test_spacing_and_case_do_not_make_a_second_line(self):
        from app.services.promotion import normalize_model_code

        assert normalize_model_code("Firewater Pump") == normalize_model_code("FIRE WATER PUMP")
        assert normalize_model_code("Flowserve unspecified line") == normalize_model_code(
            "Flow Serve unspecified line"
        )

    def test_genuinely_different_packages_stay_apart(self):
        """The distinction that matters: these are two pieces of equipment, not one."""
        from app.services.promotion import normalize_model_code

        assert normalize_model_code("Sea Water Lift Pump") != normalize_model_code(
            "Sea Water Injection Pumps"
        )
        assert normalize_model_code("FIRE WATER PUMP") != normalize_model_code(
            "WATER INJECTION PUMPS PACKAGE"
        )

    def test_the_match_is_scoped_to_one_vendor(self):
        """Two manufacturers both supplying a fire water pump keep their own line."""
        import inspect

        from app.services import promotion

        source = inspect.getsource(promotion.resolve_pump)
        assert "Pump.vendor_id == vendor.id" in source
        assert "normalize_model_code(candidate.name) == squashed" in source

    def test_the_exact_normalised_match_is_still_preferred(self):
        """The spelling fallback must not shadow a real match."""
        import inspect

        from app.services import promotion

        source = inspect.getsource(promotion.resolve_pump)
        exact = source.index("candidate.normalized_name == normalized")
        fallback = source.index("normalize_model_code(candidate.name) == squashed")
        assert exact < fallback


class TestWhatTheClientStatedCannotBeOverwrittenByAWebPage:
    """`provenance.apply_field` refuses an AI write over a VERIFIED value - and reads
    that verdict from `field_provenance`, which all 1,601 imported records lacked.

    Proven against the live data before this was added: an AI write moved a Singapore
    supplier to Zimbabwe and was accepted. With provenance recorded, the same write is
    refused and the country stays SG, while an empty website still fills.
    """

    def test_the_fields_a_document_establishes_are_named(self):
        for field in ("name", "country", "hq_country", "product_families", "approval_status"):
            assert field in client_records.DOCUMENT_ESTABLISHED_FIELDS

    def test_a_record_with_no_client_document_is_left_alone(self):
        """An AI-discovered vendor's values are not the client's to vouch for."""

        class _Db:
            def execute(self, *_a, **_k):
                raise AssertionError("should not query for a record it will skip")

        assert client_records.record_document_provenance(_Db(), _vendor({})) == 0

    def test_the_provenance_is_recorded_even_though_the_value_is_already_there(
        self, monkeypatch
    ):
        """These values were written at insert, so `apply_field` sees no change.

        Without `record_unchanged` it records nothing, which is how the most trustworthy
        data in the platform became the only data with no source.
        """
        from app.models.enums import ConfidenceLevel, ValueOrigin
        from app.services import provenance

        calls: list[dict] = []

        def fake_apply(db, entity, field_name, value, context, **kwargs):
            calls.append({"field": field_name, "context": context, **kwargs})
            return True

        monkeypatch.setattr(provenance, "apply_field", fake_apply)

        class _Rows:
            def all(self):
                return []

        class _Db:
            def execute(self, *_a, **_k):
                return _Rows()

        vendor = _vendor({"data_owner": "SP Energy", "source_documents": ["signed list.pdf"]})
        vendor.country = "SG"
        vendor.confidence_level = ConfidenceLevel.VERIFIED

        written = client_records.record_document_provenance(_Db(), vendor)
        assert written >= 1
        assert all(call["record_unchanged"] is True for call in calls)
        assert all(call["context"].origin is ValueOrigin.IMPORT for call in calls)
        assert all(
            call["context"].confidence_level is ConfidenceLevel.VERIFIED for call in calls
        )
        assert "signed list.pdf" in calls[0]["evidence_quote"]

    def test_an_sap_only_record_is_third_party_not_verified(self):
        """An ERP account is not a statement that anybody approved the company."""
        from app.models.enums import ConfidenceLevel
        from app.services import provenance

        seen: list = []

        class _Rows:
            def all(self):
                return []

        class _Db:
            def execute(self, *_a, **_k):
                return _Rows()

        original = provenance.apply_field
        provenance.apply_field = lambda db, e, f, v, ctx, **k: seen.append(ctx) or True
        try:
            vendor = _vendor({"data_owner": "SP Energy"})
            vendor.country = "IN"
            vendor.confidence_level = ConfidenceLevel.THIRD_PARTY
            client_records.record_document_provenance(_Db(), vendor)
        finally:
            provenance.apply_field = original

        assert seen and all(c.confidence_level is ConfidenceLevel.THIRD_PARTY for c in seen)

    def test_enrichment_refuses_to_run_against_unprotected_records(self):
        """The interlock: reading the web before provenance exists risks the client's data."""
        import inspect
        import pathlib

        source = pathlib.Path("scripts/enrich_vendors.py").read_text(encoding="utf-8")
        assert "Refusing to start" in source
        assert "structure_client_data --commit" in source
        # Scoped to the imported records, not to provenance in general: the AI-discovered
        # rows would otherwise satisfy the check on their own.
        assert 'Vendor.extra.op("?")("data_owner")' in source
        assert inspect is not None
