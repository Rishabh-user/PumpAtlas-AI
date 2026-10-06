"""Unit normalisation to the platform's SI baseline.

Vendor material mixes US and metric units freely - a US datasheet quotes USgpm and
feet, a European one m3/h and metres, and Middle East tenders often mix both on one
page. Everything is stored in SI; the original string is kept in ``source_units`` and
``field_provenance.original_value`` so a reviewer can always audit the conversion.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# factor to multiply by, to reach the SI baseline
FLOW_TO_M3H: dict[str, Decimal] = {
    "m3/h": Decimal(1),
    "m3/hr": Decimal(1),
    "m³/h": Decimal(1),
    "cmh": Decimal(1),
    "m3/s": Decimal(3600),
    "l/s": Decimal("3.6"),
    "lps": Decimal("3.6"),
    "l/min": Decimal("0.06"),
    "lpm": Decimal("0.06"),
    "usgpm": Decimal("0.2271247"),
    "gpm": Decimal("0.2271247"),
    "us gpm": Decimal("0.2271247"),
    "gal/min": Decimal("0.2271247"),
    "igpm": Decimal("0.2727652"),
    "ukgpm": Decimal("0.2727652"),
    "bpd": Decimal("0.0066245"),
    "bbl/d": Decimal("0.0066245"),
    "bph": Decimal("0.1589873"),
    "bbl/h": Decimal("0.1589873"),
    "cfm": Decimal("1.699011"),
}

LENGTH_TO_M: dict[str, Decimal] = {
    "m": Decimal(1),
    "metre": Decimal(1),
    "meter": Decimal(1),
    "mtr": Decimal(1),
    "ft": Decimal("0.3048"),
    "feet": Decimal("0.3048"),
    "foot": Decimal("0.3048"),
    "mm": Decimal("0.001"),
    "cm": Decimal("0.01"),
    "in": Decimal("0.0254"),
    "inch": Decimal("0.0254"),
    '"': Decimal("0.0254"),
}

LENGTH_TO_MM: dict[str, Decimal] = {
    "mm": Decimal(1),
    "cm": Decimal(10),
    "m": Decimal(1000),
    "in": Decimal("25.4"),
    "inch": Decimal("25.4"),
    '"': Decimal("25.4"),
    "ft": Decimal("304.8"),
    "feet": Decimal("304.8"),
}

MASS_TO_KG: dict[str, Decimal] = {
    "kg": Decimal(1),
    "kgs": Decimal(1),
    "kilogram": Decimal(1),
    "t": Decimal(1000),
    "te": Decimal(1000),
    "tonne": Decimal(1000),
    "mt": Decimal(1000),
    "lb": Decimal("0.4535924"),
    "lbs": Decimal("0.4535924"),
    "pound": Decimal("0.4535924"),
    "ton": Decimal("907.1847"),  # US short ton
    "g": Decimal("0.001"),
}

POWER_TO_KW: dict[str, Decimal] = {
    "kw": Decimal(1),
    "w": Decimal("0.001"),
    "mw": Decimal(1000),
    "hp": Decimal("0.7456999"),
    "bhp": Decimal("0.7456999"),
    "ps": Decimal("0.7354988"),
}

PRESSURE_TO_BAR: dict[str, Decimal] = {
    "bar": Decimal(1),
    "barg": Decimal(1),
    "bara": Decimal(1),
    "kpa": Decimal("0.01"),
    "mpa": Decimal(10),
    "pa": Decimal("0.00001"),
    "psi": Decimal("0.0689476"),
    "psig": Decimal("0.0689476"),
    "psia": Decimal("0.0689476"),
    "kg/cm2": Decimal("0.980665"),
    "kgf/cm2": Decimal("0.980665"),
    "atm": Decimal("1.01325"),
}

VOLUME_TO_M3: dict[str, Decimal] = {
    "m3": Decimal(1),
    "l": Decimal("0.001"),
    "ft3": Decimal("0.0283168"),
    "cft": Decimal("0.0283168"),
}

_NUMBER_RE = re.compile(
    r"""(?P<number>
            [-+]?\d{1,3}(?:[ ,\xa0]\d{3})+(?:\.\d+)?   # 1,200 / 1 200.5
          | [-+]?\d+(?:\.\d+)?                         # 1200 / 3.2
          | [-+]?\.\d+                                 # .82
        )
        \s*
        (?P<unit>[a-zA-Z\xb0\xb5\xb3/"'%]+(?:\s?[a-zA-Z0-9/]+)?)?""",
    re.VERBOSE,
)


class UnitConversionError(ValueError):
    """Raised when a value cannot be interpreted."""


def _clean_number(raw: str) -> Decimal:
    cleaned = raw.replace(" ", "").replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise UnitConversionError(f"not a number: {raw!r}") from exc


def parse_quantity(text: str | int | float | Decimal | None) -> tuple[Decimal, str | None] | None:
    """Split ``"1 200 USgpm"`` into ``(Decimal("1200"), "usgpm")``."""
    if text is None or text == "":
        return None
    if isinstance(text, (int, float, Decimal)):
        return Decimal(str(text)), None
    match = _NUMBER_RE.search(str(text).strip())
    if not match:
        return None
    number = _clean_number(match.group("number"))
    unit = (match.group("unit") or "").strip().lower().rstrip(".")
    return number, unit or None


def _convert(
    value: str | int | float | Decimal | None,
    table: dict[str, Decimal],
    default_unit: str,
) -> Decimal | None:
    parsed = parse_quantity(value)
    if parsed is None:
        return None
    number, unit = parsed
    key = (unit or default_unit).lower()
    factor = table.get(key)
    if factor is None:
        raise UnitConversionError(f"unsupported unit {unit!r} for this quantity")
    return number * factor


def to_m3h(value, default_unit: str = "m3/h") -> Decimal | None:
    return _convert(value, FLOW_TO_M3H, default_unit)


def to_metres(value, default_unit: str = "m") -> Decimal | None:
    return _convert(value, LENGTH_TO_M, default_unit)


def to_mm(value, default_unit: str = "mm") -> Decimal | None:
    return _convert(value, LENGTH_TO_MM, default_unit)


def to_kg(value, default_unit: str = "kg") -> Decimal | None:
    return _convert(value, MASS_TO_KG, default_unit)


def to_kw(value, default_unit: str = "kw") -> Decimal | None:
    return _convert(value, POWER_TO_KW, default_unit)


def to_bar(value, default_unit: str = "bar") -> Decimal | None:
    return _convert(value, PRESSURE_TO_BAR, default_unit)


def to_celsius(value) -> Decimal | None:
    """Handles degC, degF and K."""
    parsed = parse_quantity(value)
    if parsed is None:
        return None
    number, unit = parsed
    unit = (unit or "c").lower().lstrip("°").replace("deg", "").strip()
    if unit in {"c", "celsius", ""}:
        return number
    if unit in {"f", "fahrenheit"}:
        return (number - Decimal(32)) * Decimal(5) / Decimal(9)
    if unit in {"k", "kelvin"}:
        return number - Decimal("273.15")
    raise UnitConversionError(f"unsupported temperature unit {unit!r}")


def to_fraction(value) -> Decimal | None:
    """Percent-or-fraction to a 0-1 ratio. ``"92%"`` and ``0.92`` both give 0.92."""
    parsed = parse_quantity(value)
    if parsed is None:
        return None
    number, unit = parsed
    if unit == "%" or number > 1:
        return number / Decimal(100)
    return number


CONVERTERS = {
    "flow": to_m3h,
    "head": to_metres,
    "length_mm": to_mm,
    "mass": to_kg,
    "power": to_kw,
    "pressure": to_bar,
    "temperature": to_celsius,
    "ratio": to_fraction,
}

# Field suffix -> converter, so the extraction pipeline can normalise generically.
SUFFIX_CONVERTERS: dict[str, str] = {
    "_m3h": "flow",
    "_m": "head",
    "_mm": "length_mm",
    "_kg": "mass",
    "_kw": "power",
    "_barg": "pressure",
    "_c": "temperature",
}


def normalise_field(field_name: str, value) -> tuple[Decimal | None, str | None]:
    """Convert by field-name suffix. Returns ``(si_value, original_text)``."""
    for suffix, converter_key in SUFFIX_CONVERTERS.items():
        if field_name.endswith(suffix):
            original = str(value) if isinstance(value, str) else None
            return CONVERTERS[converter_key](value), original
    parsed = parse_quantity(value) if not isinstance(value, (int, float, Decimal)) else None
    if parsed:
        return parsed[0], str(value)
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)), None
    return None, None
