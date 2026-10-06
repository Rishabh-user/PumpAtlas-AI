"""Controlled-vocabulary enforcement.

Enum columns are native PostgreSQL types, so an unrecognised value does not degrade
gracefully - it raises LookupError and aborts the transaction. Observed against a real
OpenRouter key: Gemma returned "610" for applicable_standard and "centrifugal" for
pump_type, which killed an entire discovery run mid-promotion.
"""

from __future__ import annotations

import pytest

from app.models.pump import Pump, PumpModel
from app.models.specs import TechnicalSpec
from app.models.vendor import Vendor
from app.services.vocabulary import coerce_enum, enum_values_for, raw_column_for


def allowed(entity, field):
    values = enum_values_for(entity, field)
    assert values, f"{field} is not an enum column"
    return values


def test_detects_enum_columns_and_ignores_plain_ones():
    pump = Pump()
    assert enum_values_for(pump, "applicable_standard")
    assert enum_values_for(pump, "pump_type")
    assert enum_values_for(pump, "name") is None
    assert enum_values_for(pump, "not_a_column_at_all") is None


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("api_610", "api_610"),  # already correct
        ("API 610", "api_610"),  # human formatting
        ("api-610", "api_610"),  # punctuation
        ("api610", "api_610"),  # no separator
        ("610", "api_610"),  # the value that broke a live run
        ("ISO 13709", "iso_13709"),
        ("  API 682  ", "api_682"),  # whitespace
        ("NFPA 20", "nfpa_20"),
    ],
)
def test_coerces_real_world_standard_spellings(supplied, expected):
    value, refusal = coerce_enum(supplied, allowed(Pump(), "applicable_standard"))
    assert value == expected, refusal


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("BB3", "between_bearings_bb3"),
        ("bb3", "between_bearings_bb3"),
        ("OH2", "centrifugal_oh2"),
        ("VS4", "vertically_suspended_vs4"),
    ],
)
def test_coerces_api_610_type_codes(supplied, expected):
    value, refusal = coerce_enum(supplied, allowed(Pump(), "pump_type"))
    assert value == expected, refusal


def test_refuses_an_unrecognised_value():
    value, refusal = coerce_enum("centrifugal", allowed(Pump(), "pump_type"))
    assert value is None
    assert "not in the controlled vocabulary" in refusal or "ambiguous" in refusal


def test_refuses_rather_than_guessing_when_ambiguous():
    """ "1" could be zone_1 or class_i_div_1. Picking one would be inventing data."""
    values = allowed(TechnicalSpec(), "area_classification")
    value, refusal = coerce_enum("1", values)
    assert value is None
    assert "ambiguous" in refusal


def test_null_and_empty_are_refused_not_coerced():
    values = allowed(Pump(), "pump_type")
    assert coerce_enum(None, values)[0] is None
    assert coerce_enum("", values)[0] is None
    assert coerce_enum("   ", values)[0] is None
    assert coerce_enum("!!!", values)[0] is None


def test_raw_companion_columns_are_found_where_they_exist():
    assert raw_column_for(Pump(), "pump_type") == "pump_type_raw"
    spec = TechnicalSpec()
    assert raw_column_for(spec, "driver_type") == "driver_type_raw"
    assert raw_column_for(spec, "seal_system_type") == "seal_system_type_raw"
    assert raw_column_for(spec, "area_classification") == "area_classification_raw"
    # No companion column defined for this one, so a bad value is simply refused.
    assert raw_column_for(Pump(), "applicable_standard") is None


def test_every_enum_column_with_a_raw_companion_is_consistent():
    """A *_raw column only makes sense beside an enum column."""
    for model in (Pump, PumpModel, TechnicalSpec, Vendor):
        for column in model.__table__.columns:
            if not column.name.endswith("_raw"):
                continue
            base = column.name.removesuffix("_raw")
            assert (
                base in model.__table__.columns
            ), f"{model.__tablename__}.{column.name} has no {base} column"
            assert (
                enum_values_for(model(), base) is not None
            ), f"{model.__tablename__}.{base} is not an enum, so {column.name} is odd"


# ---------------------------------------------------------------------------
# Weak-subject guard for unattended promotion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["610", "1", "0", "", "   ", "!!", "A", "12", None])
def test_unusable_subject_names_are_rejected(name):
    """Extracting a catalogue page unattended really did produce "610" and "1"."""
    from app.services.promotion import is_usable_subject_name

    assert is_usable_subject_name(name) is False


@pytest.mark.parametrize(
    "name",
    ["PumpWorks", "ITT Goulds", "MSD 4x8x10B", "HPX", "Sulzer Pumps Ltd", "BB3-200"],
)
def test_real_subject_names_are_accepted(name):
    from app.services.promotion import is_usable_subject_name

    assert is_usable_subject_name(name) is True


def test_weak_subject_error_is_a_promotion_error():
    """So the worker's existing handler already routes it back to the review queue."""
    from app.services.promotion import PromotionError, WeakSubjectError

    assert issubclass(WeakSubjectError, PromotionError)


def test_auto_promotion_runs_unattended():
    """The guard must be active on the unattended path and off for a human reviewer."""
    import inspect

    from app.workers import tasks

    source = inspect.getsource(tasks.extract_source_task)
    assert "unattended=True" in source, "auto-promotion is not using the stricter bar"
