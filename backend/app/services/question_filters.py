"""Turn a plain-language requirement into the structured filters the search accepts.

The chat only ever built `SearchFilters(query=terms)`, and `record_query` ORs the words
together. So "Which suppliers do we hold in Singapore, and how many are approved?"
became ``suppliers or hold or singapore or many or approved`` — anything matching
"suppliers" or "approved" ranked, "singapore" contributed nothing, and the search
returned all 65 of that tenant's models. The reading model then saw eight records and a
question about Singapore and wrote the two together, reporting four suppliers as
Singaporean whose own ``vendor_country`` said DE, JP, AE and CA.

That is the failure this module exists to stop. A country, a standard, a pump type or a
duty figure named in the question is a *filter*, not a search term: the index carries
each of them as a column, and asking the column is both correct and cheaper than asking
the model to notice afterwards.

Deliberately rule-based rather than a model call. The vocabularies are small, closed and
already defined elsewhere — ISO country aliases in `vocabulary`, API 610 type codes in
`designations` — so a regex over them is exact, free and testable, where a model would
be none of the three. What a model is good at is the open-ended part of the question,
which is still what the free-text terms carry.

SOW §5.3 asks for exactly this: "an LLM-based natural-language layer that parses free-text
requirements into structured filters". This is the structured-filter half.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.designations import PUMP_TYPE_FOR_CODE
from app.services.search import SearchFilters
from app.services.vocabulary import _COUNTRY_ALIASES

#: How people name a country when they are not naming it: "Indian suppliers", "German
#: OEMs". The alias table holds nouns only, so without these the country in
#: "Which Indian suppliers do we hold?" is simply not seen. Mapped to the noun rather
#: than to a code, so a typo here fails loudly at import instead of filtering on a
#: country that does not exist.
_DEMONYMS = {
    "indian": "india",
    "german": "germany",
    "japanese": "japan",
    "chinese": "china",
    "american": "united states",
    "british": "united kingdom",
    "french": "france",
    "italian": "italy",
    "spanish": "spain",
    "dutch": "netherlands",
    "swedish": "sweden",
    "swiss": "switzerland",
    "norwegian": "norway",
    "danish": "denmark",
    "finnish": "finland",
    "polish": "poland",
    "czech": "czechia",
    "austrian": "austria",
    "belgian": "belgium",
    "brazilian": "brazil",
    "mexican": "mexico",
    "canadian": "canada",
    "australian": "australia",
    "korean": "south korea",
    "singaporean": "singapore",
    "malaysian": "malaysia",
    "indonesian": "indonesia",
    "emirati": "united arab emirates",
    "saudi": "saudi arabia",
    "qatari": "qatar",
    "kuwaiti": "kuwait",
    "omani": "oman",
    "egyptian": "egypt",
    "nigerian": "nigeria",
    "turkish": "turkey",
    "russian": "russia",
    "algerian": "algeria",
    "south african": "south africa",
}

#: Aliases that are also ordinary English words. ``are`` is the ISO alpha-3 code for the
#: United Arab Emirates, so "What BB2 models **are** in the catalogue?" filtered the
#: whole question down to the UAE — a silent narrowing of exactly the kind that produced
#: the Singapore answer. These match only where the question wrote them as a code, in
#: capitals; the country's name still matches however it is written.
_AMBIGUOUS_ALIASES = {"are", "can", "us", "nor", "fin", "bra", "pol", "no", "it", "in"}

#: Country name → code, including the adjectival forms. Longest first, so "united states
#: of america" wins over "united states" and "south african" over "south africa".
_COUNTRY_CODES: dict[str, str] = dict(_COUNTRY_ALIASES)
for _adjective, _noun in _DEMONYMS.items():
    if _noun in _COUNTRY_ALIASES:  # the alias table is the authority on what exists
        _COUNTRY_CODES[_adjective] = _COUNTRY_ALIASES[_noun]

_COUNTRY_TERMS = sorted(_COUNTRY_CODES, key=len, reverse=True)

#: API 610 type codes as a word, so "BB2" matches and "BB2000" does not.
_TYPE_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(PUMP_TYPE_FOR_CODE, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

#: How people name a pump type in words rather than in API 610 code. Asked to "find
#: vertical sump pump ranges above 500 m3/h", the parser recognised the duty and not
#: the type: "vertical sump" matched no code, fell through to the free text, matched no
#: record label, and was dropped. Four records came back on capacity alone - two OH2
#: overhung, one rotary screw, one OH6 - and the answer presented all of them as
#: "vertical sump pump ranges". Every figure in it was real and the heading was false.
#:
#: Longest phrase first: "vertical sump" is a VS4 cantilever specifically, where a bare
#: "vertical" means any vertically suspended machine. The span each phrase claims stops
#: the shorter one matching inside the longer.
#:
#: Deliberately absent: "centrifugal". It is accurate - OH, BB and VS are all
#: centrifugal - and useless as a filter, because 79 of the 166 indexed records carry a
#: pump type of `other` and would be excluded by a word that only means "not a screw
#: pump". The same reason "OEM" does not set a tier. A word that broad belongs in the
#: free text, where it ranks rather than excludes.
_TYPE_NAMES: dict[str, tuple[str, ...]] = {
    "vertically suspended": (
        "vertically_suspended_vs1",
        "vertically_suspended_vs4",
        "vertically_suspended_vs6",
    ),
    "vertical sump": ("vertically_suspended_vs4",),
    "vertical turbine": ("vertically_suspended_vs1",),
    "sump pump": ("vertically_suspended_vs4",),
    "between bearings": (
        "between_bearings_bb1",
        "between_bearings_bb2",
        "between_bearings_bb3",
        "between_bearings_bb4",
        "between_bearings_bb5",
    ),
    "between-bearings": (
        "between_bearings_bb1",
        "between_bearings_bb2",
        "between_bearings_bb3",
        "between_bearings_bb4",
        "between_bearings_bb5",
    ),
    "overhung": (
        "centrifugal_oh1",
        "centrifugal_oh2",
        "centrifugal_oh3",
        "centrifugal_oh5",
        "centrifugal_oh6",
    ),
    "progressive cavity": ("rotary_progressive_cavity",),
    "progressing cavity": ("rotary_progressive_cavity",),
    "reciprocating": ("reciprocating_plunger", "reciprocating_diaphragm"),
    "electric submersible": ("esp",),
    "electrical submersible": ("esp",),
    "submersible": ("submersible",),
    "screw pump": ("rotary_screw",),
    "gear pump": ("rotary_gear",),
    "plunger": ("reciprocating_plunger",),
    "diaphragm": ("reciprocating_diaphragm",),
    "metering": ("metering_dosing",),
    "dosing": ("metering_dosing",),
    "multiphase": ("multiphase",),
    "fire water": ("firewater",),
    "firewater": ("firewater",),
    "vertical": (
        "vertically_suspended_vs1",
        "vertically_suspended_vs4",
        "vertically_suspended_vs6",
    ),
}

_TYPE_NAME_TERMS = sorted(_TYPE_NAMES, key=len, reverse=True)


#: Standards the catalogue stores, with the spellings a person actually types.
_STANDARDS = {
    "api 610": "api_610",
    "api610": "api_610",
    "iso 13709": "api_610",  # the same standard under its ISO name
    "api 682": "api_682",
    "api682": "api_682",
    "api 675": "api_675",
    "api675": "api_675",
    "api 676": "api_676",
    "api676": "api_676",
}

_APPROVAL = {
    "approved": "approved",
    "qualified": "approved",
    "pending qualification": "pending_qualification",
    "pending": "pending_qualification",
    "rejected": "rejected",
    "blocked": "rejected",
}

_TIERS = {
    "tier 1": "tier_1_oem",
    "tier one": "tier_1_oem",
    "tier 2": "tier_2_oem",
    "tier two": "tier_2_oem",
    # Deliberately no bare "oem" mapping. It reads as tier 1, but the word only means
    # manufacturer: of 166 indexed records 69 are tier 1, 11 are tier 2 and 86 are
    # unclassified, so "show me German OEMs" would drop 97 of them without saying so.
    # A tier is filtered on when the question names a tier.
    "distributor": "authorized_distributor",
    "packager": "packager",
}

#: A number with a unit, in the forms a requirement is written in.
_CAPACITY = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:m3/?h|m³/?h|m3 per hour|cubic met(?:re|er)s? per hour)",
    re.IGNORECASE,
)
_HEAD = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:m|met(?:re|er)s?)\s*(?:head|of head|total head)",
    re.IGNORECASE,
)
_HEAD_AFTER = re.compile(
    r"head\s*(?:of|at)?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:m\b|met(?:re|er)s?)", re.IGNORECASE
)
_SPEED = re.compile(r"(\d[\d,]*)\s*(?:rpm|r/min)", re.IGNORECASE)
_EFFICIENCY = re.compile(
    r"(?:efficiency|efficient)\D{0,16}?(\d{1,3}(?:\.\d+)?)\s*%|"
    r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:hydraulic\s+)?efficien",
    re.IGNORECASE,
)
_NPSHR = re.compile(
    r"npsh(?:r|a)?\D{0,16}?(\d[\d,]*(?:\.\d+)?)\s*(?:m\b|met(?:re|er)s?)", re.IGNORECASE
)

#: "under 20 weeks", "within 22 weeks", "max 18 weeks".
_LEAD_TIME = re.compile(
    r"(?:under|below|within|less than|no more than|max(?:imum)?|≤|<=)\s*" r"(\d{1,3})\s*weeks?",
    re.IGNORECASE,
)

#: Which direction a bare figure means. "at least 200 m3/h" is a floor, "under" a ceiling.
_AT_LEAST = re.compile(
    r"(?:at least|minimum|min\.?|over|above|greater than|more than|≥|>=)\s*$",
    re.IGNORECASE,
)
_AT_MOST = re.compile(
    r"(?:under|below|within|less than|no more than|max(?:imum)?|max\.?|≤|<=)\s*$",
    re.IGNORECASE,
)

#: Tolerance around a duty point stated without a direction. A requirement for 200 m3/h
#: is not a requirement for exactly 200: a pump doing 190 is a candidate, and excluding
#: it would be the kind of silent zero this search is already prone to.
_DUTY_TOLERANCE = Decimal("0.25")

#: Speed is not continuous the way flow and head are: it falls out of pole count and
#: mains frequency, so the catalogue clusters at 1450, 1750, 2950 and 3550. A quarter
#: either side of 2950 reaches 3550 and answers a 50 Hz question with 60 Hz machines.
_SPEED_TOLERANCE = Decimal("0.05")


def _number(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _direction(question: str, match_start: int) -> str:
    """Whether the words just before a figure make it a floor, a ceiling, or a target."""
    preceding = question[max(0, match_start - 28) : match_start]
    if _AT_MOST.search(preceding):
        return "max"
    if _AT_LEAST.search(preceding):
        return "min"
    return "about"


DUTY_FIELDS = (
    "capacity_min",
    "capacity_max",
    "head_min",
    "head_max",
    "speed_min",
    "speed_max",
    "npshr_max",
    "efficiency_min",
    "lead_time_max",
)

#: The index column behind each duty filter. Used to say *why* a duty filter found
#: nothing: "only 6 of 166 records state a flow rate" is a diagnosis, where "no results"
#: is a dead end that looks like the catalogue has nothing.
DUTY_COLUMNS = {
    "capacity": "rated_capacity_m3h",
    "head": "rated_head_m",
    "speed": "rated_speed_rpm",
    "npshr": "npsh_required_m",
    "efficiency": "hydraulic_efficiency_pct",
    "lead_time": "standard_lead_time_weeks",
}

#: What each duty filter is called when explaining that it had to be dropped.
DUTY_LABELS = {
    "capacity": "flow rate",
    "head": "head",
    "speed": "speed",
    "npshr": "NPSHr",
    "efficiency": "efficiency",
    "lead_time": "lead time",
}


@dataclass
class Parsed:
    """What a question turned out to be asking for.

    ``residue`` is the question with every span that became a filter blanked out. It
    matters because the free-text half is an AND gate - ``websearch_to_tsquery``
    conjoins bare words - so leaving "singapore" among the terms after it has become
    ``countries=['SG']`` demands the word appear in the record's label as well, and no
    label contains it. The filter would be right and the search still empty.
    """

    filters: SearchFilters
    understood: dict[str, Any]
    residue: str

    @property
    def duty_named(self) -> list[str]:
        """Which duty figures the question stated, by the name a reader would use."""
        return [label for key, label in DUTY_LABELS.items() if key in self.understood]

    @property
    def categorical_named(self) -> bool:
        """Whether a country, type, standard, status or tier was recognised."""
        return any(
            key in self.understood
            for key in ("countries", "pump_types", "standards", "approval", "tier")
        )


def parse(question: str) -> Parsed:
    """Read a question into filters, and say what was understood.

    Returns the filters plus a plain-language record of what was recognised, so an
    answer can show its working and a reader can see when the question was misread -
    which matters more than the filters themselves. A silent misparse is how the
    Singapore answer happened.
    """
    text = question.lower()
    understood: dict[str, Any] = {}
    filters = SearchFilters()
    consumed: list[tuple[int, int]] = []

    def claim(begin: int, stop: int) -> bool:
        """Take a span, unless a longer name has already taken part of it."""
        if any(s < stop and begin < e for s, e in consumed):
            return False
        consumed.append((begin, stop))
        return True

    # ---- country ---------------------------------------------------------------
    # Every country named, not only the first: "Indian or German suppliers" is two
    # filters, and stopping at one would quietly drop half the question.
    for term in _COUNTRY_TERMS:
        for match in re.finditer(rf"\b{re.escape(term)}\b", text):
            # An alias that is also an English word only counts where the question
            # wrote it as a code. Without this, "what models are in the catalogue"
            # filters down to the UAE and nobody is told.
            if term in _AMBIGUOUS_ALIASES and not question[match.start() : match.end()].isupper():
                continue
            if not claim(match.start(), match.end()):
                continue
            code = _COUNTRY_CODES[term]
            if code not in filters.countries:
                filters.countries.append(code)
                understood.setdefault("countries", []).append(f"{term} \u2192 {code}")

    # ---- pump type -------------------------------------------------------------
    # Codes first, then the family names. A question that names BB2 and BB3 and then
    # says "between-bearings models" is asking for those two; letting the family name
    # run first turned a two-type question into all five, which is the same silent
    # widening as reading "OEM" as tier 1.
    for match in _TYPE_PATTERN.finditer(text):
        if not claim(match.start(), match.end()):
            continue
        mapped = PUMP_TYPE_FOR_CODE[match.group(1).lower()]
        if mapped not in filters.pump_types:
            filters.pump_types.append(mapped)
            understood.setdefault("pump_types", []).append(
                f"{match.group(1).upper()} \u2192 {mapped}"
            )

    for phrase in _TYPE_NAME_TERMS:
        # `s?` because "screw pumps" and "sump pumps" are how the plural is written,
        # and a type named in the plural is still that type.
        for match in re.finditer(rf"\b{re.escape(phrase)}s?\b", text):
            if not claim(match.start(), match.end()):
                continue
            family = _TYPE_NAMES[phrase]
            if any(mapped in filters.pump_types for mapped in family):
                # A code from this family was named outright. That is the more precise
                # reading, and the family name must not widen it.
                continue
            for mapped in family:
                if mapped not in filters.pump_types:
                    filters.pump_types.append(mapped)
            understood.setdefault("pump_types", []).append(f"{phrase} \u2192 {', '.join(family)}")

    # ---- standard --------------------------------------------------------------
    for spelling in sorted(_STANDARDS, key=len, reverse=True):
        for match in re.finditer(re.escape(spelling), text):
            if not claim(match.start(), match.end()):
                continue
            value = _STANDARDS[spelling]
            if value not in filters.standards:
                filters.standards.append(value)
                understood.setdefault("standards", []).append(f"{spelling} \u2192 {value}")

    # ---- approval status and tier ----------------------------------------------
    for spelling, value in _APPROVAL.items():
        match = re.search(rf"\b{re.escape(spelling)}\b", text)
        if match and claim(match.start(), match.end()):
            if value not in filters.vendor_approval_statuses:
                filters.vendor_approval_statuses.append(value)
                understood.setdefault("approval", []).append(f"{spelling} \u2192 {value}")
            break
    for spelling, value in _TIERS.items():
        # "OEMs" and "distributors" are how the plural is written, and a tier named in
        # the plural is still a tier.
        match = re.search(rf"\b{re.escape(spelling)}s?\b", text)
        if match and claim(match.start(), match.end()):
            if value not in filters.vendor_tiers:
                filters.vendor_tiers.append(value)
                understood.setdefault("tier", []).append(f"{spelling} \u2192 {value}")
            break

    # ---- duty point ------------------------------------------------------------
    capacity = _CAPACITY.search(text)
    if capacity and (value := _number(capacity.group(1))) is not None:
        claim(capacity.start(), capacity.end())
        direction = _direction(text, capacity.start())
        if direction == "max":
            filters.capacity_max = value
        elif direction == "min":
            filters.capacity_min = value
        else:
            filters.capacity_min = value * (1 - _DUTY_TOLERANCE)
            filters.capacity_max = value * (1 + _DUTY_TOLERANCE)
        understood["capacity"] = f"{value} m3/h ({direction})"

    head = _HEAD.search(text) or _HEAD_AFTER.search(text)
    if head and (value := _number(head.group(1))) is not None:
        claim(head.start(), head.end())
        direction = _direction(text, head.start())
        if direction == "max":
            filters.head_max = value
        elif direction == "min":
            filters.head_min = value
        else:
            filters.head_min = value * (1 - _DUTY_TOLERANCE)
            filters.head_max = value * (1 + _DUTY_TOLERANCE)
        understood["head"] = f"{value} m ({direction})"

    speed = _SPEED.search(text)
    if speed and (value := _number(speed.group(1))) is not None:
        claim(speed.start(), speed.end())
        direction = _direction(text, speed.start())
        if direction == "max":
            filters.speed_max = int(value)
        elif direction == "min":
            filters.speed_min = int(value)
        else:
            filters.speed_min = int(value * (1 - _SPEED_TOLERANCE))
            filters.speed_max = int(value * (1 + _SPEED_TOLERANCE))
        understood["speed"] = f"{int(value)} rpm ({direction})"

    npshr = _NPSHR.search(text)
    if npshr and (value := _number(npshr.group(1))) is not None:
        claim(npshr.start(), npshr.end())
        filters.npshr_max = value
        understood["npshr"] = f"{value} m available"

    efficiency = _EFFICIENCY.search(text)
    if efficiency:
        raw = efficiency.group(1) or efficiency.group(2)
        if (value := _number(raw)) is not None:
            claim(efficiency.start(), efficiency.end())
            filters.efficiency_min = value
            understood["efficiency"] = f"at least {value}%"

    lead = _LEAD_TIME.search(text)
    if lead and (value := _number(lead.group(1))) is not None:
        claim(lead.start(), lead.end())
        # `lead_time_max` reads `search_index.standard_lead_time_weeks`, so the figure
        # goes in as written. Guarding this on a field name that never existed is how
        # "delivery under 20 weeks" came back unfiltered.
        filters.lead_time_max = value
        understood["lead_time"] = f"within {int(value)} weeks"

    # Blank the spans that became filters, leaving the open-ended part of the question
    # for the full-text half to match on.
    residue = list(question)
    for begin, stop in consumed:
        residue[begin:stop] = " " * (stop - begin)

    return Parsed(filters=filters, understood=understood, residue="".join(residue))


def describe(understood: dict[str, Any]) -> str:
    """One line naming what was filtered on, for an answer to show its working."""
    if not understood:
        return ""
    parts: list[str] = []
    for key, value in understood.items():
        rendered = ", ".join(value) if isinstance(value, list) else str(value)
        parts.append(f"{key.replace('_', ' ')}: {rendered}")
    return "; ".join(parts)
