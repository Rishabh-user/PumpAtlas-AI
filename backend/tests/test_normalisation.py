"""Two normalisers, one answer — and the duplicate detection that depends on it.

A company name is normalised twice in this platform: by
`pumpatlas_normalize_company_name` in the database, and by
`promotion.normalize_company_name` in Python on the write path. Its docstring called
itself a mirror of the SQL and was not one: the SQL calls `unaccent`, which
transliterates, while the Python stripped everything outside `[a-z0-9]`. So
"Apollo Gößnitz GmbH" became `apollo gossnitz` in the database and `apollo g nitz` on the
way in, and the same supplier got two records that nothing could match up.

German, Nordic, Turkish and Spanish names are ordinary in Oil & Gas pump supply, so this
was not an edge case.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.services.dedupe import DuplicateSignal, _combine, _squash
from app.services.promotion import _LEGAL_SUFFIX_RE, fold_accents, normalize_company_name

SQL = (pathlib.Path(__file__).resolve().parents[2] / "db" / "functions.sql").read_text(
    encoding="utf-8"
)


def sql_suffixes() -> set[str]:
    """The legal-form alternation out of the SQL function, as bare tokens."""
    body = SQL[SQL.index("pumpatlas_normalize_company_name") :]
    match = re.search(r"\\y\((?P<alt>[^)]+)\)\\y", body)
    assert match, "could not find the suffix alternation in db/functions.sql"
    return {token.replace("\\", "") for token in match.group("alt").split("|")}


def python_suffixes() -> set[str]:
    match = re.search(r"\\b\((?P<alt>.+)\)\\b", _LEGAL_SUFFIX_RE.pattern, re.S)
    assert match, "could not read the suffix alternation from the Python regex"
    return {token.replace("\\", "") for token in match.group("alt").split("|")}


class TestTheTwoNormalisersAgree:
    def test_the_sql_function_is_readable_from_here(self):
        """If this fails the drift test below is vacuous, so it is asserted separately."""
        assert len(sql_suffixes()) > 20

    def test_no_suffix_is_stripped_by_only_one_of_them(self):
        """`a/s`, `kk`, `b.v` and `n.v` were in the SQL alone.

        "Grundfos A/S" normalised to `grundfos` in the database and `grundfos a s` in
        Python — a different key for the same company, which is a duplicate by
        construction.
        """
        assert sql_suffixes() == python_suffixes()

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Apollo Gößnitz GmbH", "apollo gossnitz"),
            ("Grundfos A/S", "grundfos"),
            ("Nikkiso KK", "nikkiso"),
            ("Van der Graaf B.V.", "van der graaf"),
            ("Türkiye Pompa Sanayi", "turkiye pompa sanayi"),
            ("Ebara Corporación", "ebara corporacion"),
            ("Børresen & Sønner AS", "borresen sonner"),
            ("Sulzer Pumps Ltd.", "sulzer pumps"),
        ],
    )
    def test_known_names_normalise_as_the_database_does(self, raw, expected):
        assert normalize_company_name(raw) == expected

    def test_the_regression_that_started_this(self):
        """It produced `apollo g nitz`: the ß and ö were deleted, not transliterated."""
        assert "g nitz" not in normalize_company_name("Apollo Gößnitz GmbH")


class TestAccentsAreTransliteratedNotDeleted:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ß", "ss"),
            ("ø", "o"),
            ("æ", "ae"),
            ("œ", "oe"),
            ("ł", "l"),
            ("þ", "th"),
            ("ı", "i"),
            ("é", "e"),
            ("ü", "u"),
            ("ç", "c"),
            ("ñ", "n"),
            ("å", "a"),
        ],
    )
    def test_each_letter_folds_to_ascii(self, raw, expected):
        """Decomposition handles the composed ones; the rest need an explicit mapping."""
        assert fold_accents(raw) == expected

    def test_the_result_is_always_ascii(self):
        folded = fold_accents("Ødegård Pumper Łódź Gößnitz Çorum")
        assert folded.isascii(), folded

    def test_plain_ascii_is_untouched(self):
        assert fold_accents("Flowserve 610-BB3") == "Flowserve 610-BB3"

    def test_a_symbol_is_not_expanded_into_letters(self):
        """NFKD turns the trademark sign into "TM"; `unaccent` drops it.

        Expanding it made "Trillium Flow Technologies(TM)" normalise to
        `...technologiestm` here and `...technologies` in the database - a divergence
        introduced by the very fix meant to remove one.
        """
        assert "tm" not in normalize_company_name("Trillium Flow Technologies™")

    def test_a_number_form_is_expanded_because_the_database_expands_it(self):
        """One half as a single character decomposes to "1 2" on both sides."""
        assert normalize_company_name("Cafe ½ Pumpen") == "cafe 1 2 pumpen"

    def test_the_one_remaining_difference_is_recorded_not_guessed_at(self):
        """`unaccent` maps the registered sign to "R"; this drops it, as it always has.

        Left alone on purpose: matching `unaccent`'s rule table for every symbol nobody
        puts in a company name is not worth the risk of getting a letter wrong. Recorded
        here so it is a known difference rather than a surprise.
        """
        assert normalize_company_name("Pumps ® Ltd") == "pumps"


class TestASpaceIsNotADifferentCompany:
    def test_a_squashed_name_ignores_spacing_and_punctuation(self):
        assert _squash("flow serve") == _squash("flowserve")
        assert _squash("ruhr-pumpen") == _squash("ruhrpumpen")

    def test_different_companies_do_not_squash_together(self):
        assert _squash("pumpworks") != _squash("pumpworks 610")

    def test_corroboration_never_lowers_the_score(self):
        """The weighted form discounted a lone signal by 20% whatever else was there.

        A trigram match of 0.615 scored 0.492 and fell under the recording threshold, so
        "Flowserve" and "Flow Serve" stayed two companies because the one signal that
        identified them was marked down for being alone.
        """
        alone = [DuplicateSignal("trigram_name", 0.615, "")]
        assert _combine(alone) >= 0.615

    def test_support_still_adds_to_a_weaker_match(self):
        strong = [DuplicateSignal("trigram_name", 0.7, "")]
        supported = [*strong, DuplicateSignal("country", 0.4, "")]
        assert _combine(supported) > _combine(strong)

    def test_a_squashed_match_is_strong_enough_to_be_recorded(self):
        """Otherwise the fix changes nothing: the pair is found and then dropped."""
        from app.services.dedupe import LOW_CONFIDENCE

        signals = [
            DuplicateSignal("trigram_name", 0.615, ""),
            DuplicateSignal("squashed_name", 0.97, ""),
        ]
        assert _combine(signals) >= LOW_CONFIDENCE


class TestAnUmlautWrittenTwoWaysIsOneCompany:
    """The normaliser folds; a company writing its own name in ASCII expands.

    "Apollo Gößnitz GmbH" normalises to `apollo gossnitz`. The same company writes itself
    "Apollo Goessnitz GmbH", which normalises to `apollo goessnitz`, and its own domain
    is apollo-goessnitz.de. Both spellings are in this database as two records with two
    sets of pump models, and no dedupe signal could see across them: trigram similarity
    scores the pair below the threshold.
    """

    def test_the_folded_and_the_expanded_spelling_meet(self):
        from app.services.dedupe import _fold_digraphs

        assert _fold_digraphs("apollo gossnitz") == _fold_digraphs("apollo goessnitz")

    def test_it_does_not_collapse_unrelated_names(self):
        from app.services.dedupe import _fold_digraphs

        assert _fold_digraphs("sulzer") != _fold_digraphs("sundyne")
        assert _fold_digraphs("pumpworks") != _fold_digraphs("pumpworks 610")

    def test_the_stored_key_is_untouched(self):
        """It is a signal, not the normalised name: collapsing loses information."""
        from app.services.promotion import normalize_company_name

        assert normalize_company_name("Apollo Gößnitz GmbH") == "apollo gossnitz"
