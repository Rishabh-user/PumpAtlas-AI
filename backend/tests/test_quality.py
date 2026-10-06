"""Deterministic data-quality rules. These run on every write, so they must be exact."""

from app.models.enums import DataQualityFlagType, FlagSeverity
from app.services import quality


def types_of(findings):
    return {f.flag_type for f in findings}


def fields_of(findings):
    return {f.field_name for f in findings}


def test_clean_record_produces_no_findings():
    record = {
        "rated_capacity_m3h": 272.5,
        "rated_head_m": 137.2,
        "npsh_required_m": 3.5,
        "npsh_available_m": 6.0,
        "hydraulic_efficiency_pct": 78,
        "rated_speed_rpm": 3560,
        "rated_power_kw": 160,
        "suction_pressure_barg": 2.0,
        "discharge_pressure_barg": 15.5,
        "casing_design_pressure_barg": 51,
        "max_allowable_working_pressure_barg": 51,
        "hydrostatic_test_pressure_barg": 77,
    }
    assert quality.check_ranges(record) == []
    assert quality.check_cross_field(record) == []


def test_head_in_feet_is_flagged_as_unit_mismatch():
    # 4500 ft accidentally stored as metres: 4500 / 3.28 = 1372 m, inside range
    findings = quality.check_ranges({"rated_head_m": 4500})
    assert DataQualityFlagType.UNIT_MISMATCH in types_of(findings)
    assert "feet" in findings[0].message


def test_out_of_range_without_unit_signature_is_out_of_range():
    # No unit confusion can turn 99% into a plausible efficiency, and _pct has no
    # ratio signature, so this must not be mislabelled as a unit mismatch.
    findings = quality.check_ranges({"hydraulic_efficiency_pct": 99})
    assert findings
    assert findings[0].flag_type is DataQualityFlagType.OUT_OF_RANGE


def test_unit_hint_is_scoped_to_the_field_dimension():
    # 900 barg is out of range; dividing by 3.28 lands in range, but feet-to-metres
    # is not a pressure conversion, so the hint must not claim it
    findings = quality.check_ranges({"casing_design_pressure_barg": 900})
    assert findings
    assert "feet" not in findings[0].message
    assert findings[0].flag_type is DataQualityFlagType.UNIT_MISMATCH  # psi -> bar
    assert "psi" in findings[0].message


def test_longest_suffix_wins_for_flow_fields():
    # rated_capacity_m3h must use the flow ratios, not the metres ratio
    findings = quality.check_ranges({"rated_capacity_m3h": 100_000})
    assert findings
    assert "USgpm" in findings[0].message or "barrels" in findings[0].message


def test_operating_weight_below_dry_weight():
    findings = quality.check_cross_field({"dry_weight_kg": 3200, "operating_weight_kg": 2900})
    assert "operating_weight_kg" in fields_of(findings)


def test_shipping_weight_below_dry_weight():
    findings = quality.check_cross_field({"dry_weight_kg": 3200, "shipping_weight_kg": 3000})
    assert "shipping_weight_kg" in fields_of(findings)


def test_expedited_lead_time_longer_than_standard():
    findings = quality.check_cross_field(
        {"standard_lead_time_weeks": 24, "expedited_lead_time_weeks": 30}
    )
    assert "expedited_lead_time_weeks" in fields_of(findings)


def test_cavitating_duty_point_is_critical():
    findings = quality.check_cross_field({"npsh_required_m": 7.0, "npsh_available_m": 5.0})
    assert findings[0].severity is FlagSeverity.CRITICAL


def test_discharge_not_above_suction():
    findings = quality.check_cross_field(
        {"suction_pressure_barg": 12, "discharge_pressure_barg": 11}
    )
    assert "discharge_pressure_barg" in fields_of(findings)


def test_hydrotest_below_api610_minimum():
    findings = quality.check_cross_field(
        {"casing_design_pressure_barg": 50, "hydrostatic_test_pressure_barg": 55}
    )
    assert any("1.25" in f.message for f in findings)


def test_sealless_pump_with_flush_plan():
    findings = quality.check_cross_field(
        {"seal_system_type": "canned_motor", "seal_piping_plan": "Plan 52"}
    )
    assert "seal_piping_plan" in fields_of(findings)


def test_atex_in_safe_area_is_low_severity():
    findings = quality.check_cross_field(
        {"atex_certified": True, "area_classification": "safe_area"}
    )
    assert findings[0].severity is FlagSeverity.LOW


def test_rated_flow_outside_min_max():
    low = quality.check_cross_field({"rated_capacity_m3h": 50, "min_capacity_m3h": 80})
    high = quality.check_cross_field({"rated_capacity_m3h": 500, "max_capacity_m3h": 400})
    assert low and high


def test_completeness_flags_missing_critical_fields():
    findings = quality.check_completeness("technical_specs", {"rated_capacity_m3h": 100})
    missing = fields_of(findings)
    assert "rated_head_m" in missing
    assert "material_class" in missing
    assert "rated_capacity_m3h" not in missing


def test_completeness_ignores_untracked_entity_types():
    assert quality.check_completeness("unknown_table", {}) == []


def test_validate_record_combines_all_checks():
    # operating < dry is a contradiction; shipping_weight is not tracked but
    # operating_weight_kg being present means the missing flag must come from elsewhere
    findings = quality.validate_record(
        "technical_specs", {"rated_capacity_m3h": 272, "rated_head_m": 4500}
    )
    assert types_of(findings) >= {
        DataQualityFlagType.UNIT_MISMATCH,
        DataQualityFlagType.MISSING_REQUIRED_FIELD,
    }


def test_completeness_pct():
    assert quality.completeness_pct("x", {"a": 1, "b": None, "c": "", "d": 4}) == 0.5
    assert quality.completeness_pct("x", {}) is None


def test_booleans_are_not_treated_as_numbers():
    # True would otherwise coerce to Decimal(1) and trip a range check
    assert quality.check_ranges({"rated_head_m": True}) == []
