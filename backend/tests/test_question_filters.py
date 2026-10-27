"""Reading a requirement into filters, and refusing to read one that is not there.

The chat used to send every question to the full-text index as a bag of words. Asked
which suppliers were held in Singapore, it matched on "suppliers" and "approved",
ranked eight records, and the reading model - handed a question about Singapore and a
list of records - reported four vendors as Singaporean whose own country field said DE,
JP, AE and CA. Every record was real; the answer was false.

So these tests pin two things, and the second matters more than the first:

* a country, standard, type or duty figure in the question becomes a *filter*;
* a word that merely looks like one does not.

A false positive here is worse than a miss. Missing a filter returns too much and the
reader sees it; inventing one silently removes records and the answer still reads
fluently. The `are`/UAE case below is exactly that, and it was live.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from app.services import chat
from app.services.chat import _strip_unknown_markers
from app.services.question_filters import DUTY_FIELDS, describe, parse
from app.services.search import SearchFilters

# --- what should be recognised ------------------------------------------------


def test_country_named_becomes_a_filter() -> None:
    parsed = parse("Which suppliers do we hold in Singapore?")
    assert parsed.filters.countries == ["SG"]


def test_demonym_counts_as_naming_the_country() -> None:
    """ "Indian suppliers" names India. The alias table holds nouns only, so without
    the adjectival forms the country in this question is simply not seen."""
    assert parse("Which Indian suppliers do we hold?").filters.countries == ["IN"]
    assert parse("Show me German OEMs").filters.countries == ["DE"]


def test_every_country_named_is_kept() -> None:
    """Stopping at the first match answers half the question and says nothing."""
    assert set(parse("German and Japanese suppliers").filters.countries) == {"DE", "JP"}


def test_pump_type_codes_and_standards() -> None:
    parsed = parse("API 610 BB2 and BB3 pumps")
    assert parsed.filters.standards == ["api_610"]
    assert parsed.filters.pump_types == [
        "between_bearings_bb2",
        "between_bearings_bb3",
    ]


def test_a_pump_type_named_in_words_is_a_filter() -> None:
    """Asked to "find vertical sump pump ranges above 500 m3/h", the parser saw the
    duty and not the type: `_TYPE_PATTERN` matched API 610 codes only, so "vertical
    sump" fell through to the free text, matched no record label and was dropped. Four
    records came back on capacity alone - two OH2 overhung, one rotary screw, one OH6 -
    and the answer presented all four as "vertical sump pump ranges"."""
    parsed = parse("Find vertical sump pump ranges rated above 500 m3/h")
    assert parsed.filters.pump_types == ["vertically_suspended_vs4"]
    assert parsed.filters.capacity_min == Decimal("500")


def test_a_family_name_covers_its_whole_family() -> None:
    assert parse("show me between-bearings pumps").filters.pump_types == [
        "between_bearings_bb1",
        "between_bearings_bb2",
        "between_bearings_bb3",
        "between_bearings_bb4",
        "between_bearings_bb5",
    ]


def test_a_named_code_is_not_widened_by_the_family_name() -> None:
    """ "BB2 and BB3 between-bearings models" asks for two types, not five. Letting the
    family name run first turned a precise question into the whole family."""
    parsed = parse("What BB2 and BB3 between-bearings models are in the catalogue?")
    assert parsed.filters.pump_types == [
        "between_bearings_bb2",
        "between_bearings_bb3",
    ]


def test_a_type_named_in_the_plural_still_counts() -> None:
    types = parse("any submersible or screw pumps?").filters.pump_types
    assert set(types) == {"submersible", "rotary_screw"}


def test_centrifugal_is_deliberately_not_a_type_filter() -> None:
    """It is accurate and useless: OH, BB and VS are all centrifugal, and 79 of the 166
    indexed records carry a pump type of `other`, so the word would exclude half the
    catalogue to mean "not a screw pump". Same reason "OEM" does not set a tier."""
    assert parse("centrifugal pumps above 100 m3/h").filters.pump_types == []


def test_duty_point_without_a_direction_becomes_a_range() -> None:
    """A requirement for 200 m3/h is not a requirement for exactly 200: a pump doing
    190 is a candidate, and excluding it is the silent zero this module exists to
    avoid."""
    filters = parse("200 m3/hr at 150 m head").filters
    assert filters.capacity_min == Decimal("150.00")
    assert filters.capacity_max == Decimal("250.00")
    assert filters.head_min < Decimal("150") < filters.head_max


def test_a_direction_is_honoured() -> None:
    assert parse("under 20 weeks").filters.lead_time_max == Decimal("20")
    assert parse("at least 75% efficiency").filters.efficiency_min == Decimal("75")
    assert parse("NPSHr under 4 m").filters.npshr_max == Decimal("4")


def test_lead_time_lands_on_the_field_that_exists() -> None:
    """`lead_time_max` reads `search_index.standard_lead_time_weeks`. An earlier guard
    looked for `lead_time_max_weeks`, which never existed, so "delivery under 20 weeks"
    was dropped without a word."""
    assert any(f.name == "lead_time_max" for f in SearchFilters.__dataclass_fields__.values())
    assert parse("delivery under 20 weeks").filters.lead_time_max == Decimal("20")


def test_speed_tolerance_does_not_cross_mains_frequency() -> None:
    """Speed falls out of pole count and frequency, so the catalogue clusters at 1450,
    1750, 2950 and 3550. A quarter either side of 2950 reaches 3550 and answers a 50 Hz
    question with 60 Hz machines."""
    filters = parse("pumps running at 2950 rpm").filters
    assert filters.speed_min <= 2950 <= filters.speed_max
    assert filters.speed_max < 3550


# --- what must not be recognised ----------------------------------------------


def test_an_english_word_that_is_also_a_country_code_is_not_a_country() -> None:
    """`are` is the ISO alpha-3 code for the United Arab Emirates. Left unguarded it
    turned "what models are in the catalogue" into a question about the UAE, and the
    reader was never told the question had been narrowed."""
    parsed = parse("What BB2 and BB3 models are in the catalogue?")
    assert parsed.filters.countries == []
    assert parsed.filters.pump_types  # the rest of the question still parsed


def test_the_same_word_written_as_a_code_is_a_country() -> None:
    assert parse("vendors in the ARE").filters.countries == ["AE"]
    assert parse("suppliers based in the US").filters.countries == ["US"]


def test_can_and_nor_are_not_canada_and_norway() -> None:
    parsed = parse("Which pumps can we source, nor should we?")
    assert parsed.filters.countries == []


def test_bare_oem_does_not_narrow_to_tier_one() -> None:
    """ "OEM" means manufacturer, not tier 1. Of 166 indexed records 69 are tier 1, 11
    are tier 2 and 86 are unclassified, so reading the word as a tier drops 97 of them
    without saying so. A tier is filtered on when a tier is named."""
    assert parse("Show me German OEMs").filters.vendor_tiers == []
    assert parse("Show me tier 1 OEMs").filters.vendor_tiers == ["tier_1_oem"]


def test_a_question_with_nothing_structured_yields_no_filters() -> None:
    parsed = parse("Who makes the HPX4x6 and what does Sulzer offer?")
    assert parsed.understood == {}
    assert parsed.filters.countries == []
    assert parsed.residue == "Who makes the HPX4x6 and what does Sulzer offer?"


# --- the residue ---------------------------------------------------------------


def test_words_that_became_filters_leave_the_free_text() -> None:
    """The free-text half matches the record *label*. A word already expressed as a
    filter has no business also being demanded of the label."""
    parsed = parse("Which suppliers do we hold in Singapore?")
    assert "singapore" not in parsed.residue.lower()
    assert "suppliers" in parsed.residue


def test_duty_figures_leave_the_free_text_too() -> None:
    residue = parse("BB2 pumps, 200 m3/hr at 150 m head").residue
    assert "200" not in residue
    assert "bb2" not in residue.lower()


# --- showing the working -------------------------------------------------------


def test_describe_names_what_was_read_and_what_it_became() -> None:
    """The mapping is shown, not just the result, so a misreading is legible: a reader
    who sees "are -> AE" knows instantly what went wrong."""
    said = describe(parse("approved suppliers in Singapore").understood)
    assert "singapore" in said
    assert "SG" in said
    assert "approved" in said


# --- citations ------------------------------------------------------------------


def test_a_citation_to_a_source_that_was_never_given_is_removed() -> None:
    """With nothing to cite, a model told to cite everything invents a marker.

    Asked about Brazilian pumps with no record matched, gpt-4o-mini answered "we do not
    hold any pumps from Brazil [R1]". The sentence is true and the citation is
    fabricated, which is worse than an uncited sentence: the page renders markers as
    references to real records, so the reader sees evidence that does not exist.
    """
    prose, dropped = _strip_unknown_markers("No, we do not hold any pumps from Brazil [R1].", set())
    assert prose == "No, we do not hold any pumps from Brazil."
    assert dropped == ["R1"]


def test_a_citation_to_a_source_that_was_given_survives() -> None:
    prose, dropped = _strip_unknown_markers(
        "Sulzer makes it [R1] and KSB does too [R2][R9].", {"R1", "R2"}
    )
    assert prose == "Sulzer makes it [R1] and KSB does too [R2]."
    assert dropped == ["R9"]


def test_tightening_the_prompt_was_not_enough_on_its_own() -> None:
    """The prompt asks; this checks. Both are kept, because the rule is worth stating
    and a stated rule is not a guarantee - adding it fixed the Indian question and the
    very next question invented a marker again."""
    assert "Cite only markers that actually appear in the context" in chat.SYSTEM_PROMPT
    assert "_strip_unknown_markers(prose, known)" in inspect.getsource(chat.answer)


def test_duty_fields_are_all_real_filter_fields() -> None:
    """The relaxation path clears these by name. A typo would silently stop clearing
    one, and the duty filter it leaves behind would keep the result at zero."""
    names = set(SearchFilters.__dataclass_fields__)
    assert set(DUTY_FIELDS) <= names
