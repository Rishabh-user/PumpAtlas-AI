"""Coerce model output onto the controlled vocabulary, or refuse it.

The prompts instruct Gemma to use only the enum values and to return null otherwise, but
a small open model will not always comply. Observed against a real key: it returned
``"610"`` for ``applicable_standard`` and ``"centrifugal"`` for ``pump_type``. Written
straight to a native PostgreSQL enum, the first raises
``LookupError: '610' is not among the defined enum values`` and aborts the whole
promotion; the second is simply not a value the platform recognises.

So every enum write passes through here first:

1. **Coerce** the obvious cases. ``"API 610"``, ``"api-610"``, ``"610"`` all mean
   ``api_610``, and a procurement analyst would be rightly annoyed to lose the field over
   punctuation.
2. **Refuse** anything ambiguous or unrecognised, and hand back the original string so it
   can go to the matching ``*_raw`` column for a human to look at.

Ambiguity is always refused rather than guessed. ``"1"`` could be ``zone_1`` or
``class_i_div_1``; picking one would be inventing data.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql.sqltypes import Enum as SAEnum

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def enum_values_for(entity: Any, field_name: str) -> list[str] | None:
    """Allowed values if this column is a native enum, else None."""
    try:
        column = sa_inspect(type(entity)).columns.get(field_name)
    except Exception:  # noqa: BLE001 - not a mapped class
        return None
    if column is None:
        return None
    column_type = getattr(column, "type", None)
    if isinstance(column_type, SAEnum) and column_type.enums:
        return list(column_type.enums)
    return None


def _normalise(raw: str) -> str:
    return _NON_ALNUM.sub("_", raw.strip().lower()).strip("_")


def coerce_enum(value: Any, allowed: list[str]) -> tuple[str | None, str | None]:
    """Map a value onto ``allowed``.

    Returns ``(coerced_value, reason_refused)`` - exactly one is non-None.
    """
    if value is None:
        return None, "value is null"
    if not isinstance(value, str):
        value = str(value)
    if value in allowed:
        return value, None

    candidate = _normalise(value)
    if not candidate:
        return None, "value is empty once normalised"
    if candidate in allowed:
        return candidate, None

    # "api610" -> "api_610": compare with separators removed.
    squashed = {member.replace("_", ""): member for member in allowed}
    if candidate.replace("_", "") in squashed:
        return squashed[candidate.replace("_", "")], None

    # "610" -> "api_610", "bb3" -> "between_bearings_bb3". Only when unambiguous.
    suffix_matches = [m for m in allowed if m.endswith(f"_{candidate}")]
    if len(suffix_matches) == 1:
        return suffix_matches[0], None
    if len(suffix_matches) > 1:
        return None, f"{value!r} is ambiguous between {suffix_matches}"

    # "arrangement_2" -> "api682_arrangement_2": unambiguous containment.
    contains = [m for m in allowed if candidate in m]
    if len(contains) == 1:
        return contains[0], None
    if len(contains) > 1:
        return None, f"{value!r} is ambiguous between {contains}"

    return None, f"{value!r} is not in the controlled vocabulary"


def raw_column_for(entity: Any, field_name: str) -> str | None:
    """The ``*_raw`` companion column, if the model defines one."""
    candidate = f"{field_name}_raw"
    try:
        columns = sa_inspect(type(entity)).columns
    except Exception:  # noqa: BLE001
        return None
    return candidate if columns.get(candidate) is not None else None


# ------------------------------------------------------------------- column types

_TRUE_WORDS = {"true", "yes", "y", "1", "available", "confirmed", "compliant"}
_FALSE_WORDS = {"false", "no", "n", "0", "none", "not available", "unavailable"}

#: ISO 3166-1 alpha-3 and common informal names for the countries that actually appear
#: in Oil & Gas pump supply, mapped to the alpha-2 the schema stores. Gemma is told to
#: return alpha-2 and mostly does; observed slips include "USA", "UK" and "Deutschland".
#: Anything not listed is refused rather than guessed - a wrong country of origin is an
#: export-control problem, not a cosmetic one.
_COUNTRY_ALIASES = {
    "usa": "US",
    "us": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "gbr": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "deu": "DE",
    "germany": "DE",
    "deutschland": "DE",
    "ita": "IT",
    "italy": "IT",
    "italia": "IT",
    "fra": "FR",
    "france": "FR",
    "esp": "ES",
    "spain": "ES",
    "nld": "NL",
    "netherlands": "NL",
    "holland": "NL",
    "che": "CH",
    "switzerland": "CH",
    "swe": "SE",
    "sweden": "SE",
    "nor": "NO",
    "norway": "NO",
    "dnk": "DK",
    "denmark": "DK",
    "fin": "FI",
    "finland": "FI",
    "aut": "AT",
    "austria": "AT",
    "bel": "BE",
    "belgium": "BE",
    "jpn": "JP",
    "japan": "JP",
    "chn": "CN",
    "china": "CN",
    "kor": "KR",
    "south korea": "KR",
    "korea": "KR",
    "ind": "IN",
    "india": "IN",
    "bra": "BR",
    "brazil": "BR",
    "brasil": "BR",
    "can": "CA",
    "canada": "CA",
    "mex": "MX",
    "mexico": "MX",
    "are": "AE",
    "uae": "AE",
    "united arab emirates": "AE",
    "sau": "SA",
    "saudi arabia": "SA",
    "qat": "QA",
    "qatar": "QA",
    "kwt": "KW",
    "kuwait": "KW",
    "omn": "OM",
    "oman": "OM",
    "sgp": "SG",
    "singapore": "SG",
    "mys": "MY",
    "malaysia": "MY",
    "idn": "ID",
    "indonesia": "ID",
    "aus": "AU",
    "australia": "AU",
    "zaf": "ZA",
    "south africa": "ZA",
    "nga": "NG",
    "nigeria": "NG",
    "egy": "EG",
    "egypt": "EG",
    "dza": "DZ",
    "algeria": "DZ",
    "tur": "TR",
    "turkey": "TR",
    "türkiye": "TR",
    "pol": "PL",
    "poland": "PL",
    "cze": "CZ",
    "czechia": "CZ",
    "czech republic": "CZ",
    "rus": "RU",
    "russia": "RU",
}


def _column(entity: Any, field_name: str):
    try:
        columns = sa_inspect(entity).mapper.columns
    except Exception:
        return None
    return columns.get(field_name)


#: Columns holding a web address. A value without a scheme is not a link.
_URL_COLUMNS = frozenset({"website", "logo_url", "source_url", "url"})


def _fit_url(value: Any, field_name: str) -> tuple[Any, str | None]:
    """Give a web address the scheme a browser needs, or refuse it.

    Five vendor records held `www.handolpumps.com` with no `https://`. A browser reads
    that as a *relative* path, so the "Vendor website" button on the profile pointed at
    `/vendors/www.handolpumps.com` - a link that looks right and goes nowhere. The page
    was not at fault: a bare host is not a URL, and the place to fix it is where the
    value is written, not in every template that renders it.
    """
    text_value = str(value).strip()
    if not text_value:
        return None, f"empty {field_name}"
    if text_value.startswith(("http://", "https://")):
        return text_value, None
    if "://" in text_value:
        return None, f"{text_value[:60]!r} is not an http address for {field_name}"
    if "." not in text_value.split("/")[0]:
        return None, f"{text_value[:60]!r} is not a web address for {field_name}"
    return f"https://{text_value.lstrip('/')}", None


def _fit_number(value: Any, column: Any, field_name: str) -> tuple[Any, str | None]:
    """Make a number fit its column, or refuse it with a reason.

    A `NUMERIC(p, s)` column holds numbers below `10 ** (p - s)`; PostgreSQL does not
    truncate an over-large one, it raises, and the raise happens during the flush - which
    aborts the whole transaction and loses every good field written alongside it. That is
    the failure this module was created to prevent for booleans and enums; numbers had
    the same hole.

    The hole has a specific shape here. `Ratio` is `NUMERIC(5, 4)`, holding 0 to 1, and
    every column using it is named `_pct`: `on_time_delivery_pct`,
    `historical_on_time_delivery_pct`, `data_completeness_pct`. The extraction contract
    asks for "percentages as a number 0-100". So a page stating "98% on-time delivery"
    produced 98 for a column whose ceiling is 1, and storing that supplier would have
    failed outright.

    A value above 1 cannot be a fraction of one, so on a ratio column it is read as the
    percentage it plainly is and scaled. A value at or below 1 is taken at face value:
    0.98 is 98%, and guessing that someone meant 0.98% would corrupt a number rather
    than refuse it. Anything that still does not fit is refused, and the refusal is
    recorded with the record.
    """
    numeric_type = getattr(column, "type", None)
    precision = getattr(numeric_type, "precision", None)
    scale = getattr(numeric_type, "scale", None)
    if precision is None or scale is None:
        return value, None

    ceiling = Decimal(10) ** (precision - scale)
    number = Decimal(str(value))
    if abs(number) < ceiling:
        return value, None

    is_ratio_column = precision == 5 and scale == 4
    if is_ratio_column and Decimal(1) < number <= Decimal(100):
        return number / Decimal(100), None

    return (
        None,
        f"{value} does not fit {field_name}, which holds values below {ceiling}",
    )


def coerce_for_column(entity: Any, field_name: str, value: Any) -> tuple[Any, str | None]:
    """Fit a model-supplied value to its column, or explain why it does not fit.

    Vocabulary handling upstream protects enum columns. This protects the rest, and the
    reason it exists is the same: a small model does not always respect the shape it was
    asked for. Observed against a real key, screening one vendor page, Gemma returned
    ``"offshore (platform) installation"`` for the boolean ``fpso_offshore_experience``
    and the bare string ``"US"`` for the ``manufacturing_countries`` array. Passed
    through, the first raises ``TypeError: Not a boolean value`` inside the flush and
    aborts the whole write; the second is a silent shape mismatch.

    Returns ``(coerced, None)`` or ``(None, reason)``.
    """
    column = _column(entity, field_name)
    if column is None or value is None:
        return value, None

    python_type: Any
    try:
        python_type = column.type.python_type
    except (NotImplementedError, AttributeError):
        python_type = None

    # ---- arrays: a scalar or a comma-separated string becomes a list -----------
    if hasattr(column.type, "item_type"):
        items = value if isinstance(value, (list, tuple)) else None
        if items is None:
            text = str(value).strip()
            if not text:
                return None, "empty value for a list field"
            items = [part.strip() for part in text.split(",") if part.strip()]
        cleaned: list[str] = []
        item_length = getattr(column.type.item_type, "length", None)
        for item in items:
            entry = str(item).strip()
            if not entry:
                continue
            # A 2-char array is a country list; normalise before the length check.
            if item_length == 2:
                mapped = _COUNTRY_ALIASES.get(entry.lower())
                entry = mapped or entry.upper()
            if item_length is not None and len(entry) > item_length:
                return None, (
                    f"{entry!r} is longer than the {item_length}-character list items "
                    f"{field_name} stores"
                )
            cleaned.append(entry)
        return (cleaned or None), (None if cleaned else "no usable list items")

    # ---- booleans: only unambiguous words, never a free-text sentence ----------
    if python_type is bool:
        if isinstance(value, bool):
            return value, None
        text = str(value).strip().lower()
        if text in _TRUE_WORDS:
            return True, None
        if text in _FALSE_WORDS:
            return False, None
        return None, f"{str(value)[:60]!r} is not a yes/no answer for {field_name}"

    # ---- numbers: accept numeric text, refuse prose ----------------------------
    if python_type in (int, float) or python_type is Decimal:
        if isinstance(value, bool):
            return None, f"a boolean is not a number for {field_name}"
        if isinstance(value, (int, float, Decimal)):
            return _fit_number(value, column, field_name)
        text = re.sub(r"[,\s]", "", str(value))
        text = re.sub(r"^[^\d.\-]+|[^\d.]+$", "", text)
        try:
            parsed = int(text) if python_type is int else Decimal(text)
        except (ValueError, ArithmeticError):
            return None, f"{str(value)[:60]!r} is not a number for {field_name}"
        return _fit_number(parsed, column, field_name)

    # ---- strings: normalise countries, and refuse over-length rather than let
    #      PostgreSQL truncate a value a buyer will later rely on ---------------
    if python_type is str:
        text = str(value).strip()
        if not text:
            return None, "empty string"
        if field_name in _URL_COLUMNS:
            fitted, refusal = _fit_url(text, field_name)
            if refusal:
                return None, refusal
            text = fitted
        length = getattr(column.type, "length", None)
        if length == 2:
            mapped = _COUNTRY_ALIASES.get(text.lower())
            text = mapped or text.upper()
        if length is not None and len(text) > length:
            if length <= 8:
                return None, (
                    f"{text[:40]!r} does not fit the {length}-character {field_name} "
                    "column; expected a code, not a description"
                )
            text = text[:length]
        return text, None

    return value, None
