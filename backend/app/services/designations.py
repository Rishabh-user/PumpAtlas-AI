"""Telling a product's name apart from the category it belongs to.

An API 610 type code is not a model designation. "OH1" is a *configuration* - horizontal
overhung, foot-mounted - that hundreds of manufacturers build; "B Series" is what
Amarinth calls the pumps it builds in that configuration. A record called "OH1" says
nothing about who makes what, cannot be quoted for, and has to be found and merged away
later.

The review queue was offering four such candidates at once, from four different
manufacturers: "OH1" from Nebras, "OH1" from CME, "API 610 OH1" from LUBOR and
"OH1 B Series" from Amarinth. The first two were caught by an exact-match list. The other
two were not: "API 610 OH1" is two category words rather than one, and "OH1 B Series"
carries a real product name behind a type code.

So this reads a designation as words rather than as one string:

* every word is a type code, a standard, or a category noun -> the page names a category,
  and there is no product here to store;
* some words are, and something is left -> the remainder is the product name, and the
  type and standard are facts about it worth keeping in the fields that hold them.

Deliberately conservative. A word is only dropped when it is one of these exactly; a
model genuinely called "OH1-200" keeps its name, because "oh1200" is not "oh1".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: API 610 configuration codes. OH = overhung, BB = between bearings, VS = vertically
#: suspended; the number is the arrangement within the family.
API_TYPE_CODES = frozenset(
    {
        "oh1", "oh2", "oh3", "oh4", "oh5", "oh6",
        "bb1", "bb2", "bb3", "bb4", "bb5",
        "vs1", "vs2", "vs3", "vs4", "vs5", "vs6", "vs7",
    }
)  # fmt: skip

#: Standards a page names beside the type, in the spellings they are written in.
STANDARD_CODES = frozenset(
    {
        "api610", "api674", "api675", "api676", "api682", "api685",
        "iso13709", "iso5199", "iso2858", "iso9001",
        "asmeb731", "asmeb732", "nfpa20", "en733", "atex",
    }
)  # fmt: skip

#: Prefixes that form a standard with the number that follows: "API 610", "ISO 5199".
_STANDARD_PREFIXES = frozenset({"api", "iso", "asme", "ansi", "din", "en", "nfpa"})

#: Nouns that never form part of a product name, wherever they appear. "KGSG 40-250
#: pumps" is the KGSG 40-250.
ALWAYS_GENERIC = frozenset(
    {
        "pump", "pumps", "pumping", "product", "products", "solutions", "industrial",
        "the", "and", "for", "with",
    }
)  # fmt: skip

#: Words that describe a category *until* a product has been named, and belong to the
#: name after it.
#:
#: "Series" is the whole of this distinction. Amarinth's product is the **B Series**, and
#: dropping the word leaves "B" - which is not a name, and which `is_usable_subject_name`
#: then refuses, turning a good candidate into a blocked one. But "Single Stage End
#: Suction Centrifugal Pump" with nothing else in it is a page title. Same words, and
#: what separates them is whether anything has been named yet.
QUALIFIER_WORDS = frozenset(
    {
        "series", "type", "types", "model", "models", "range",
        "single", "stage", "stages", "singlestage", "multistage", "twostage",
        "end", "suction", "endsuction", "centrifugal", "process",
        "horizontal", "vertical", "overhung", "between", "bearings", "inline",
        "radially", "split", "axially", "casing", "barrel", "double", "sealless",
        "standard", "compliant", "compliance",
    }
)  # fmt: skip

#: Everything this module recognises as naming a category rather than a product.
GENERIC_WORDS = ALWAYS_GENERIC | QUALIFIER_WORDS

#: Which `PumpType` a type code means. Only the ones the enum actually carries: OH4,
#: VS2, VS3, VS5 and VS7 have no member, and inventing one to fill this map would put a
#: value in the column that the rest of the system cannot read back.
PUMP_TYPE_FOR_CODE = {
    "oh1": "centrifugal_oh1",
    "oh2": "centrifugal_oh2",
    "oh3": "centrifugal_oh3",
    "oh5": "centrifugal_oh5",
    "oh6": "centrifugal_oh6",
    "bb1": "between_bearings_bb1",
    "bb2": "between_bearings_bb2",
    "bb3": "between_bearings_bb3",
    "bb4": "between_bearings_bb4",
    "bb5": "between_bearings_bb5",
    "vs1": "vertically_suspended_vs1",
    "vs4": "vertically_suspended_vs4",
    "vs6": "vertically_suspended_vs6",
}

#: Which `ApplicableStandard` a standard token means.
STANDARD_FOR_CODE = {
    "api610": "api_610",
    "api674": "api_674",
    "api675": "api_675",
    "api676": "api_676",
    "api682": "api_682",
    "api685": "api_685",
    "iso13709": "iso_13709",
    "iso5199": "iso_5199",
    "iso2858": "iso_2858",
    "asmeb731": "asme_b73_1",
    "asmeb732": "asme_b73_2",
    "nfpa20": "nfpa_20",
    "en733": "en_733",
}

_SPLIT = re.compile(r"[^\s,/|]+")

#: A parenthesised tail: "HZC (OH2)", "ETL (close coupled OH5)".
_TRAILING_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")


def _key(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


@dataclass
class Designation:
    """What a model code turned out to be made of."""

    #: The words that actually name a product, in the spelling the page used.
    product_words: list[str] = field(default_factory=list)
    #: API type codes found, lowercased: ["oh1"].
    types: list[str] = field(default_factory=list)
    #: Standards found, lowercased and squashed: ["api610"].
    standards: list[str] = field(default_factory=list)
    #: Category nouns found.
    generic: list[str] = field(default_factory=list)
    #: Where each product word sat in `text`, so the name can be cut out rather than
    #: rebuilt. Rebuilding turned "EAP/EAPK series" into "EAP EAPK series" and
    #: "BBS, CD" into "BBS CD" - the punctuation inside a designation is part of it.
    product_spans: list[tuple[int, int]] = field(default_factory=list)
    #: The designation as read, after any parenthesised type code was dropped.
    text: str = ""

    @property
    def product_name(self) -> str:
        """The span from the first product word to the last, exactly as written."""
        if not self.product_spans:
            return ""
        start = self.product_spans[0][0]
        end = self.product_spans[-1][1]
        return self.text[start:end].strip(" ,;-")

    @property
    def is_category_only(self) -> bool:
        """Nothing here names a product - and something was recognised as a category.

        The second half matters: an empty string is not a category page, it is a missing
        value, and `blocked_reason` already has a better sentence for that.
        """
        return not self.product_words and bool(self.types or self.standards or self.generic)

    @property
    def pump_type(self) -> str | None:
        for code in self.types:
            if code in PUMP_TYPE_FOR_CODE:
                return PUMP_TYPE_FOR_CODE[code]
        return None

    @property
    def applicable_standard(self) -> str | None:
        for code in self.standards:
            if code in STANDARD_FOR_CODE:
                return STANDARD_FOR_CODE[code]
        return None

    @property
    def api_610_type_code(self) -> str | None:
        return self.types[0].upper() if self.types else None


def _strip_parenthesised_type(raw: str) -> str:
    """Drop a trailing "(OH2)" or "(close coupled OH5)".

    Rodelta writes its ETL that way. Tokenising alone would take the OH5 and leave
    "ETL (close coupled" - a name with an open bracket, which is worse than either
    keeping the whole thing or dropping the whole group.
    """
    match = _TRAILING_PAREN.search(raw)
    if not match:
        return raw
    inside = {_key(word) for word in _SPLIT.findall(match.group(1))}
    if inside & (API_TYPE_CODES | STANDARD_CODES):
        return raw[: match.start()].rstrip()
    return raw


def classify(raw: str | None) -> Designation:
    """Read a model code as words: what names the product, and what names its category."""
    result = Designation()
    if not raw:
        return result

    text = _strip_parenthesised_type(str(raw).strip())
    result.text = text
    matches = list(_SPLIT.finditer(text))
    words = [match.group(0) for match in matches]
    spans = [match.span() for match in matches]

    index = 0
    while index < len(words):
        word = words[index]
        key = _key(word)

        # "API 610" and "ISO 5199" arrive as two words and mean one standard.
        if key in _STANDARD_PREFIXES and index + 1 < len(words):
            joined = key + _key(words[index + 1])
            if joined in STANDARD_CODES:
                result.standards.append(joined)
                index += 2
                continue

        if key in API_TYPE_CODES:
            result.types.append(key)
        elif key in STANDARD_CODES:
            result.standards.append(key)
        elif key in ALWAYS_GENERIC:
            result.generic.append(key)
        elif key in QUALIFIER_WORDS and not result.product_words:
            result.generic.append(key)
        elif key:
            # Past the first product word, a qualifier is part of the name: the B Series
            # is not the B.
            result.product_words.append(word)
            result.product_spans.append(spans[index])
        index += 1

    return result


def product_name(raw: str | None) -> str:
    """The part of a designation that names a product, or the original if none does.

    Falling back to the original is on purpose: a caller stripping a code has to end up
    with *something*, and a designation this module does not understand is safer kept
    whole than replaced with an empty string.
    """
    designation = classify(raw)
    return designation.product_name or (raw or "").strip()


def is_category_only(raw: str | None) -> bool:
    return classify(raw).is_category_only
