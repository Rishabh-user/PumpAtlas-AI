"""Unit conversion is load-bearing: a bad factor silently corrupts intelligence data."""

from decimal import Decimal

import pytest

from app.utils import units


def close(actual, expected: str, tol: str = "1e-5") -> bool:
    """Decimal-safe comparison; pytest.approx does not mix floats with Decimal."""
    assert actual is not None
    return abs(Decimal(str(actual)) - Decimal(expected)) <= Decimal(tol) * abs(Decimal(expected))


def test_usgpm_to_m3h():
    assert close(units.to_m3h("1200 USgpm"), "272.54964")


def test_flow_thousands_separators():
    assert close(units.to_m3h("1,200 gpm"), "272.54964")
    assert units.to_m3h("1 200 m3/h") == Decimal(1200)


def test_head_feet_to_metres():
    assert close(units.to_metres("450 ft"), "137.16")


def test_bare_number_uses_default_unit():
    assert units.to_metres(210) == Decimal(210)
    assert units.to_m3h(Decimal("55.5")) == Decimal("55.5")


def test_mass_variants():
    assert units.to_kg("2.5 t") == Decimal(2500)
    assert close(units.to_kg("4400 lbs"), "1995.80656")


def test_power_hp_to_kw():
    assert close(units.to_kw("250 HP"), "186.424975")


def test_pressure_psi_to_bar():
    assert close(units.to_bar("740 psig"), "51.021224")
    assert close(units.to_bar("51 kg/cm2"), "50.013915")


def test_temperature_scales():
    assert close(units.to_celsius("350 degF"), "176.666")
    assert units.to_celsius("120 C") == Decimal(120)
    assert close(units.to_celsius("300 K"), "26.85")


def test_ratio_handles_percent_and_fraction():
    assert units.to_fraction("82%") == Decimal("0.82")
    assert units.to_fraction(0.82) == Decimal("0.82")
    assert units.to_fraction(82) == Decimal("0.82")


def test_unsupported_unit_raises():
    with pytest.raises(units.UnitConversionError):
        units.to_m3h("1200 furlongs/fortnight")


def test_none_and_blank_are_none():
    assert units.to_m3h(None) is None
    assert units.to_kg("") is None


def test_normalise_field_by_suffix():
    value, original = units.normalise_field("rated_capacity_m3h", "1200 USgpm")
    assert close(value, "272.54964")
    assert original == "1200 USgpm"

    value, _ = units.normalise_field("dry_weight_kg", "3.2 tonne")
    assert value == Decimal(3200)

    value, _ = units.normalise_field("rated_head_m", "450 ft")
    assert close(value, "137.16")


def test_normalise_field_passthrough_for_unsuffixed():
    value, _ = units.normalise_field("rated_speed_rpm", 3560)
    assert value == Decimal(3560)
