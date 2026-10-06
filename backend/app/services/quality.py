"""Data quality: deterministic validators plus the AI quality check.

The deterministic rules run on every write and are cheap, explainable and testable.
Gemma runs on top of them to catch the judgement calls a range check cannot - a value
copied from the wrong model in a catalogue, or a duty point that does not belong to the
declared pump type.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ai import DataQualityFlag
from app.models.enums import DataQualityFlagType, FlagSeverity

log = get_logger(__name__)

# Plausible envelopes for Oil & Gas service. Deliberately wide: the goal is catching
# unit mistakes and typos, not enforcing engineering judgement.
PLAUSIBLE_RANGES: dict[str, tuple[float, float, str]] = {
    "rated_capacity_m3h": (0.01, 30_000, "m3/h"),
    "rated_head_m": (0.5, 4_000, "m"),
    "npsh_required_m": (0.1, 60, "m"),
    "hydraulic_efficiency_pct": (5, 92, "%"),
    "bep_efficiency_pct": (5, 93, "%"),
    "rated_speed_rpm": (60, 25_000, "rpm"),
    "rated_power_kw": (0.05, 25_000, "kW"),
    "casing_design_pressure_barg": (1, 700, "barg"),
    "max_allowable_working_pressure_barg": (1, 700, "barg"),
    "hydrostatic_test_pressure_barg": (1.5, 1_100, "barg"),
    "fluid_temperature_max_c": (-100, 550, "degC"),
    "fluid_specific_gravity": (0.3, 2.5, "-"),
    "fluid_viscosity_cst": (0.2, 1_000_000, "cSt"),
    "dry_weight_kg": (1, 250_000, "kg"),
    "operating_weight_kg": (1, 300_000, "kg"),
    "shipping_weight_kg": (1, 350_000, "kg"),
    "standard_lead_time_weeks": (1, 160, "weeks"),
    "expedited_lead_time_weeks": (1, 160, "weeks"),
    "warranty_months": (0, 120, "months"),
    "mtbf_hours": (500, 400_000, "h"),
    "coating_dft_microns": (20, 3_000, "micron"),
    "parts_commonality_pct": (0, 100, "%"),
    "local_content_pct": (0, 100, "%"),
}

# Fields a procurement decision cannot responsibly be made without.
CRITICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "pump_models": ("model_code",),
    "pumps": ("pump_type", "applicable_standard"),
    "technical_specs": (
        "rated_capacity_m3h",
        "rated_head_m",
        "npsh_required_m",
        "material_class",
        "seal_system_type",
        "area_classification",
    ),
    "commercial_specs": ("base_price_amount", "payment_terms", "warranty_months"),
    "dimensional_specs": ("dry_weight_kg", "operating_weight_kg"),
    "delivery_specs": ("standard_lead_time_weeks", "country_of_origin"),
    "operational_specs": ("units_supplied", "qaqc_certifications"),
    "administrative_specs": ("legal_entity_name", "registration_number"),
}

# Unit-mistake signatures, keyed by the field-name suffix they can apply to.
#
# Keying by suffix matters: without it, dividing any out-of-range number by 3.28 lands
# inside some plausible range and every range breach gets misreported as a feet/metres
# mix-up. A ratio is only meaningful for the dimension the field actually measures.
UNIT_MISTAKE_RATIOS: dict[str, tuple[tuple[Decimal, str], ...]] = {
    "_m": ((Decimal("3.28084"), "value looks like feet stored as metres"),),
    "_mm": ((Decimal("25.4"), "value looks like inches stored as millimetres"),),
    "_m3h": (
        (Decimal("4.40287"), "value looks like USgpm stored as m3/h"),
        (Decimal("151.0"), "value looks like barrels per day stored as m3/h"),
    ),
    "_kg": (
        (Decimal("2.20462"), "value looks like pounds stored as kilograms"),
        (Decimal("0.001"), "value looks like tonnes stored as kilograms"),
    ),
    "_barg": (
        (Decimal("14.5038"), "value looks like psi stored as bar"),
        (Decimal("10.0"), "value looks like kPa stored as bar"),
    ),
    "_kw": ((Decimal("1.34102"), "value looks like horsepower stored as kW"),),
}


@dataclass
class Finding:
    flag_type: DataQualityFlagType
    severity: FlagSeverity
    message: str
    field_name: str | None = None
    detected_value: str | None = None
    expected_range: str | None = None
    suggested_fix: str | None = None


def _num(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def check_ranges(record: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for field_name, (low, high, unit) in PLAUSIBLE_RANGES.items():
        value = _num(record.get(field_name))
        if value is None:
            continue
        if value < Decimal(str(low)) or value > Decimal(str(high)):
            hint = _unit_mistake_hint(field_name, value, Decimal(str(low)), Decimal(str(high)))
            findings.append(
                Finding(
                    flag_type=(
                        DataQualityFlagType.UNIT_MISMATCH
                        if hint
                        else DataQualityFlagType.OUT_OF_RANGE
                    ),
                    severity=FlagSeverity.HIGH if hint else FlagSeverity.MEDIUM,
                    message=(
                        f"{field_name} = {value} {unit} is outside the plausible range "
                        f"{low}-{high} {unit}" + (f"; {hint}" if hint else "")
                    ),
                    field_name=field_name,
                    detected_value=str(value),
                    expected_range=f"{low} - {high} {unit}",
                    suggested_fix=(
                        "Check the unit on the source document" if hint else "Verify against source"
                    ),
                )
            )
    return findings


def _ratios_for_field(field_name: str) -> tuple[tuple[Decimal, str], ...]:
    """Longest matching suffix wins, so ``_m3h`` never falls through to ``_m``."""
    for suffix in sorted(UNIT_MISTAKE_RATIOS, key=len, reverse=True):
        if field_name.endswith(suffix):
            return UNIT_MISTAKE_RATIOS[suffix]
    return ()


def _unit_mistake_hint(field_name: str, value: Decimal, low: Decimal, high: Decimal) -> str | None:
    """If undoing a plausible unit confusion lands the value in range, say which one."""
    for factor, explanation in _ratios_for_field(field_name):
        if low <= value / factor <= high:
            return explanation
    return None


def check_cross_field(record: dict[str, Any]) -> list[Finding]:
    """Contradictions that only show up when two fields are read together."""
    findings: list[Finding] = []

    def add(message: str, field_name: str, severity=FlagSeverity.HIGH, fix: str | None = None):
        findings.append(
            Finding(
                flag_type=DataQualityFlagType.CONTRADICTION,
                severity=severity,
                message=message,
                field_name=field_name,
                suggested_fix=fix,
            )
        )

    dry = _num(record.get("dry_weight_kg"))
    operating = _num(record.get("operating_weight_kg"))
    shipping = _num(record.get("shipping_weight_kg"))
    if dry and operating and operating < dry:
        add(
            f"Operating weight ({operating} kg) is below dry weight ({dry} kg); "
            "a pump filled with liquid cannot weigh less",
            "operating_weight_kg",
        )
    if dry and shipping and shipping < dry:
        add(
            f"Shipping weight ({shipping} kg) is below dry weight ({dry} kg); "
            "packaging cannot reduce mass",
            "shipping_weight_kg",
        )

    standard_lt = _num(record.get("standard_lead_time_weeks"))
    expedited_lt = _num(record.get("expedited_lead_time_weeks"))
    if standard_lt and expedited_lt and expedited_lt > standard_lt:
        add(
            f"Expedited lead time ({expedited_lt} weeks) exceeds the standard lead time "
            f"({standard_lt} weeks)",
            "expedited_lead_time_weeks",
        )

    suction = _num(record.get("suction_pressure_barg"))
    discharge = _num(record.get("discharge_pressure_barg"))
    if suction is not None and discharge is not None and discharge <= suction:
        add(
            f"Discharge pressure ({discharge} barg) is not above suction pressure "
            f"({suction} barg); the pump would add no head",
            "discharge_pressure_barg",
        )

    npshr = _num(record.get("npsh_required_m"))
    npsha = _num(record.get("npsh_available_m"))
    if npshr and npsha and npshr >= npsha:
        add(
            f"NPSH required ({npshr} m) is not below NPSH available ({npsha} m); "
            "this duty point would cavitate",
            "npsh_required_m",
            severity=FlagSeverity.CRITICAL,
            fix="Confirm the available suction head for the installed case",
        )

    rated_flow = _num(record.get("rated_capacity_m3h"))
    min_flow = _num(record.get("min_capacity_m3h"))
    max_flow = _num(record.get("max_capacity_m3h"))
    if rated_flow and min_flow and rated_flow < min_flow:
        add("Rated capacity is below the stated minimum capacity", "rated_capacity_m3h")
    if rated_flow and max_flow and rated_flow > max_flow:
        add("Rated capacity is above the stated maximum capacity", "rated_capacity_m3h")

    mawp = _num(record.get("max_allowable_working_pressure_barg"))
    design_p = _num(record.get("casing_design_pressure_barg"))
    if mawp and design_p and mawp < design_p:
        add(
            f"MAWP ({mawp} barg) is below the casing design pressure ({design_p} barg)",
            "max_allowable_working_pressure_barg",
        )

    hydro = _num(record.get("hydrostatic_test_pressure_barg"))
    if hydro and design_p and hydro < design_p * Decimal("1.25"):
        findings.append(
            Finding(
                flag_type=DataQualityFlagType.SUSPICIOUS_VALUE,
                severity=FlagSeverity.MEDIUM,
                message=(
                    f"Hydrostatic test pressure ({hydro} barg) is below 1.25 x casing design "
                    f"pressure ({design_p} barg), which API 610 requires"
                ),
                field_name="hydrostatic_test_pressure_barg",
                suggested_fix="Check the test pressure on the datasheet or test report",
            )
        )

    # Certification consistency
    area = str(record.get("area_classification") or "")
    if record.get("atex_certified") and area == "safe_area":
        add(
            "ATEX certification declared for a safe-area installation",
            "atex_certified",
            severity=FlagSeverity.LOW,
            fix="Confirm the intended area classification",
        )
    seal = str(record.get("seal_system_type") or "")
    if seal in {"canned_motor", "magnetic_drive", "seal_less_other"} and record.get(
        "seal_piping_plan"
    ):
        add(
            f"A {seal} pump has no mechanical seal, yet an API 682 flush plan "
            f"({record['seal_piping_plan']}) is recorded",
            "seal_piping_plan",
            severity=FlagSeverity.MEDIUM,
        )

    return findings


def check_completeness(entity_type: str, record: dict[str, Any]) -> list[Finding]:
    required = CRITICAL_FIELDS.get(entity_type, ())
    findings = []
    for field_name in required:
        value = record.get(field_name)
        if value in (None, "", [], {}):
            findings.append(
                Finding(
                    flag_type=DataQualityFlagType.MISSING_REQUIRED_FIELD,
                    severity=FlagSeverity.MEDIUM,
                    message=f"{field_name} is required for procurement use but is empty",
                    field_name=field_name,
                    suggested_fix="Request from the vendor or run AI enrichment",
                )
            )
    return findings


def validate_record(entity_type: str, record: dict[str, Any]) -> list[Finding]:
    """All deterministic checks for one record."""
    return [
        *check_completeness(entity_type, record),
        *check_ranges(record),
        *check_cross_field(record),
    ]


def persist_findings(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    findings: list[Finding],
    detected_by: str = "validator",
    ai_job_id: uuid.UUID | None = None,
    replace_existing: bool = True,
) -> list[DataQualityFlag]:
    """Write findings as flags, replacing the previous unresolved set from this detector."""
    if replace_existing:
        stale = db.scalars(
            select(DataQualityFlag).where(
                DataQualityFlag.entity_type == entity_type,
                DataQualityFlag.entity_id == entity_id,
                DataQualityFlag.detected_by == detected_by,
                DataQualityFlag.is_resolved.is_(False),
            )
        ).all()
        for flag in stale:
            db.delete(flag)

    created: list[DataQualityFlag] = []
    for finding in findings:
        flag = DataQualityFlag(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=finding.field_name,
            flag_type=finding.flag_type,
            severity=finding.severity,
            message=finding.message,
            detected_value=finding.detected_value,
            expected_range=finding.expected_range,
            suggested_fix=finding.suggested_fix,
            detected_by=detected_by,
            ai_job_id=ai_job_id,
        )
        db.add(flag)
        created.append(flag)
    db.flush()
    return created


def run_ai_quality_check(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    record: dict[str, Any],
    client=None,
    user_id: uuid.UUID | None = None,
) -> list[DataQualityFlag]:
    """Ask Gemma for the judgement-call problems, then persist what it returns."""
    import json

    from app.ai import prompts
    from app.ai.openrouter import OpenRouterClient
    from app.models.enums import AiJobType
    from app.services import extraction

    client = client or OpenRouterClient()
    job, result, error = extraction.execute_ai_job(
        db,
        client,
        prompts.SYSTEM_QUALITY_CHECK,
        "Record under review:" + chr(10) + json.dumps(record, indent=2, default=str),
        job_kwargs={
            "tenant_id": tenant_id,
            "job_type": AiJobType.QUALITY_CHECK,
            "subject_type": entity_type,
            "subject_id": entity_id,
            "prompt_name": "quality_check",
            "request_payload": {"field_count": len(record)},
            "model": client.model,
            "user_id": user_id,
        },
    )
    if error is not None:
        log.warning("quality.ai_check_failed", error=str(error))
        return []

    raw_flags = ((result.data if result else None) or {}).get("flags") or []
    findings: list[Finding] = []
    for raw in raw_flags:
        if not isinstance(raw, dict) or not raw.get("message"):
            continue
        try:
            flag_type = DataQualityFlagType(raw.get("flag_type", "suspicious_value"))
        except ValueError:
            flag_type = DataQualityFlagType.SUSPICIOUS_VALUE
        try:
            severity = FlagSeverity(raw.get("severity", "medium"))
        except ValueError:
            severity = FlagSeverity.MEDIUM
        findings.append(
            Finding(
                flag_type=flag_type,
                severity=severity,
                message=str(raw["message"])[:2000],
                field_name=(raw.get("field_name") or None),
                detected_value=(
                    str(raw["detected_value"])[:500] if raw.get("detected_value") else None
                ),
                expected_range=(
                    str(raw["expected_range"])[:255] if raw.get("expected_range") else None
                ),
                suggested_fix=(str(raw["suggested_fix"]) if raw.get("suggested_fix") else None),
            )
        )

    return persist_findings(
        db,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        findings=findings,
        detected_by="ai",
        ai_job_id=job.id,
    )


def completeness_pct(entity_type: str, record: dict[str, Any], tracked: list[str] | None = None):
    """Share of tracked fields that carry a value, as a 0-1 ratio."""
    fields = tracked or [k for k in record if not k.startswith("_")]
    if not fields:
        return None
    populated = sum(1 for f in fields if record.get(f) not in (None, "", [], {}))
    return round(populated / len(fields), 4)
