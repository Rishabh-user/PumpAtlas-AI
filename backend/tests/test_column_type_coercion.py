"""Model output must fit the column, or be refused with a reason.

The vocabulary gate already protects native enum columns — that was added after Gemma
returned ``"610"`` for ``applicable_standard`` and aborted a whole promotion. Every other
column has a type the model can miss just as easily, and until this was added it did:
screening a single real vendor page, Gemma returned

* ``"offshore (platform) installation"`` for the boolean ``fpso_offshore_experience``
* the bare string ``"US"`` for the ``VARCHAR(2)[]`` ``manufacturing_countries``
* ``"USA"`` for the ``VARCHAR(2)`` ``hq_country``

The first raised ``TypeError: Not a boolean value`` inside the flush, which aborted the
transaction and returned a 500 for the whole store request — losing the good fields
along with the bad one. These tests pin the coercion so that never regresses to a crash.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.vendor import Vendor
from app.services.vocabulary import coerce_for_column


@pytest.fixture
def vendor() -> Vendor:
    return Vendor()


class TestBooleans:
    def test_a_sentence_is_refused_not_crashed(self, vendor):
        """The exact value that produced the 500."""
        value, reason = coerce_for_column(
            vendor, "fpso_offshore_experience", "offshore (platform) installation"
        )
        assert value is None
        assert "yes/no" in reason

    @pytest.mark.parametrize("given", ["yes", "Yes", "true", "1", "confirmed", True])
    def test_affirmative_words_become_true(self, vendor, given):
        assert coerce_for_column(vendor, "fpso_offshore_experience", given) == (True, None)

    @pytest.mark.parametrize("given", ["no", "false", "0", "none", False])
    def test_negative_words_become_false(self, vendor, given):
        assert coerce_for_column(vendor, "fpso_offshore_experience", given) == (False, None)


class TestArrays:
    def test_a_scalar_becomes_a_single_item_list(self, vendor):
        assert coerce_for_column(vendor, "product_families", "centrifugal pumps") == (
            ["centrifugal pumps"],
            None,
        )

    def test_a_comma_separated_string_is_split(self, vendor):
        value, reason = coerce_for_column(vendor, "manufacturing_countries", "USA, Germany")
        assert value == ["US", "DE"]
        assert reason is None

    def test_a_real_list_passes_through(self, vendor):
        assert coerce_for_column(vendor, "manufacturing_countries", ["US", "DE"]) == (
            ["US", "DE"],
            None,
        )

    def test_an_item_too_long_for_the_column_is_refused(self, vendor):
        value, reason = coerce_for_column(
            vendor, "manufacturing_countries", ["Republic of Somewhere"]
        )
        assert value is None
        assert "list items" in reason


class TestCountryCodes:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("USA", "US"),
            ("usa", "US"),
            ("United States", "US"),
            ("Deutschland", "DE"),
            ("de", "DE"),
            ("UK", "GB"),
            ("Türkiye", "TR"),
        ],
    )
    def test_common_aliases_normalise_to_alpha_2(self, vendor, given, expected):
        assert coerce_for_column(vendor, "hq_country", given) == (expected, None)

    def test_an_unknown_country_is_refused_not_truncated(self, vendor):
        """Truncating "Republic of Somewhere" to "RE" would invent a country."""
        value, reason = coerce_for_column(vendor, "hq_country", "Republic of Somewhere")
        assert value is None
        assert "2-character" in reason


class TestNumbers:
    def test_thousands_separators_and_trailing_words_are_stripped(self, vendor):
        assert coerce_for_column(vendor, "employee_count", "1,200 staff") == (1200, None)

    def test_prose_is_refused(self, vendor):
        value, reason = coerce_for_column(vendor, "employee_count", "several hundred")
        assert value is None
        assert "not a number" in reason

    def test_a_decimal_column_keeps_precision(self, vendor):
        assert coerce_for_column(vendor, "annual_revenue_usd", " 45000000 ") == (
            Decimal("45000000"),
            None,
        )

    def test_a_boolean_is_not_silently_a_number(self, vendor):
        value, reason = coerce_for_column(vendor, "employee_count", True)
        assert value is None
        assert "boolean" in reason


class TestPassThrough:
    def test_none_is_left_alone(self, vendor):
        assert coerce_for_column(vendor, "employee_count", None) == (None, None)

    def test_an_unknown_field_is_left_alone(self, vendor):
        """Unknown-field handling belongs to `apply_fields`, not to the coercion."""
        assert coerce_for_column(vendor, "not_a_column", "x") == ("x", None)

    def test_a_long_text_column_still_truncates_rather_than_refusing(self, vendor):
        """A clipped description is a cosmetic loss; a clipped country code is a lie."""
        long_name = "x" * 400
        value, reason = coerce_for_column(vendor, "name", long_name)
        assert reason is None
        assert len(value) == 255


class TestAWebAddressIsAddressable:
    """Five vendor records held `www.handolpumps.com` with no scheme.

    A browser reads a bare host as a *relative* path, so the "Vendor website" button on
    the profile pointed at `/vendors/www.handolpumps.com` - a link that looks right and
    goes nowhere. A bare host is not a URL, and the place to fix it is where the value is
    written rather than in every template that renders it.
    """

    def test_a_bare_host_is_given_a_scheme(self, vendor):
        value, error = coerce_for_column(vendor, "website", "www.handolpumps.com")
        assert error is None
        assert value == "https://www.handolpumps.com"

    def test_an_address_that_already_works_is_untouched(self, vendor):
        value, error = coerce_for_column(vendor, "website", "http://amarinth.com/contact")
        assert error is None
        assert value == "http://amarinth.com/contact"

    def test_a_path_survives(self, vendor):
        value, _ = coerce_for_column(vendor, "website", "pumpworks610.com/api-610")
        assert value == "https://pumpworks610.com/api-610"

    def test_prose_is_refused_rather_than_stored_as_a_link(self, vendor):
        value, error = coerce_for_column(vendor, "website", "see contact page")
        assert value is None
        assert "web address" in error

    def test_another_scheme_is_refused(self, vendor):
        """Anything but http(s) on a field rendered as a link is a hazard, not a value."""
        value, error = coerce_for_column(vendor, "website", "javascript:alert(1)")
        assert value is None
        assert error

    def test_an_ordinary_string_column_is_not_treated_as_a_url(self, vendor):
        value, error = coerce_for_column(vendor, "hq_city", "Saxmundham")
        assert error is None
        assert value == "Saxmundham"
