"""Maintain the denormalised ``search_index`` rows.

Called after any promotion or manual edit. Reads the current version of each spec table
and flattens the filterable fields into one row per pump model. The tsvector itself is
built by the ``trg_search_index_vector`` database trigger, so indexing logic lives in
exactly one place.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ai import DataQualityFlag
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.models.specs import (
    AdministrativeSpec,
    CommercialSpec,
    DeliverySpec,
    DimensionalSpec,
    OperationalSpec,
    TechnicalSpec,
)
from app.models.vendor import Vendor
from app.services import completeness

log = get_logger(__name__)

INDEX_VERSION = "1.0.0"


def _current_spec(db: Session, spec_cls: type, pump_model_id: uuid.UUID) -> Any:
    return db.scalar(
        select(spec_cls)
        .where(spec_cls.pump_model_id == pump_model_id, spec_cls.is_current.is_(True))
        .order_by(spec_cls.version.desc())
        .limit(1)
    )


def _text_chunk(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            parts.extend(str(v) for v in value if v)
        elif isinstance(value, dict):
            parts.extend(str(v) for v in value.values() if v)
        else:
            parts.append(str(value))
    return " ".join(parts)


def collect_certifications(
    technical: TechnicalSpec | None, operational: OperationalSpec | None
) -> list[str]:
    certs: list[str] = []
    if technical:
        certs.extend(technical.third_party_certifications or [])
        if technical.marine_class_society:
            certs.append(technical.marine_class_society)
        if technical.atex_certified:
            certs.append("ATEX")
        if technical.iecex_certified:
            certs.append("IECEx")
        if technical.nace_mr0175_compliant:
            certs.append("NACE MR0175")
    if operational:
        certs.extend(operational.qaqc_certifications or [])
    # Preserve order, drop duplicates case-insensitively.
    seen: set[str] = set()
    unique: list[str] = []
    for cert in certs:
        key = str(cert).strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(str(cert).strip())
    return unique


def _enum_text(record: Any, field: str) -> str | None:
    """An enum column as plain text, whether or not it has been through the database.

    A value loaded from PostgreSQL arrives as an enum member, but one just assigned in
    the same session is still the string it was set to - SQLAlchemy does not coerce it
    until the round trip. Reading `.value` unconditionally therefore crashed whenever
    indexing ran in the same transaction as the write, which is exactly what AI pump
    discovery and the specification backfill both do:
    ``AttributeError: 'str' object has no attribute 'value'``.
    """
    if record is None:
        return None
    value = getattr(record, field, None)
    if not value:
        return None
    return getattr(value, "value", value)


def reindex_pump_model(db: Session, pump_model_id: uuid.UUID) -> SearchIndex | None:
    """Rebuild the search row for one pump model. Idempotent."""
    model = db.get(PumpModel, pump_model_id)
    if model is None or model.deleted_at is not None:
        stale = db.scalar(select(SearchIndex).where(SearchIndex.pump_model_id == pump_model_id))
        if stale is not None:
            db.delete(stale)
        return None

    pump = db.get(Pump, model.pump_id)
    vendor = db.get(Vendor, pump.vendor_id) if pump else None
    if pump is None or vendor is None:
        log.warning("indexing.orphan_pump_model", pump_model_id=str(pump_model_id))
        return None

    technical = _current_spec(db, TechnicalSpec, model.id)
    commercial = _current_spec(db, CommercialSpec, model.id)
    dimensional = _current_spec(db, DimensionalSpec, model.id)
    delivery = _current_spec(db, DeliverySpec, model.id)
    operational = _current_spec(db, OperationalSpec, model.id)
    administrative = _current_spec(db, AdministrativeSpec, model.id)

    open_flags = (
        db.scalar(
            select(func.count())
            .select_from(DataQualityFlag)
            .where(
                DataQualityFlag.entity_id.in_([model.id, pump.id, vendor.id]),
                DataQualityFlag.is_resolved.is_(False),
            )
        )
        or 0
    )

    row = db.scalar(select(SearchIndex).where(SearchIndex.pump_model_id == model.id))
    if row is None:
        row = SearchIndex(pump_model_id=model.id, pump_id=pump.id, vendor_id=vendor.id)
        db.add(row)

    row.tenant_id = model.tenant_id
    row.pump_id = pump.id
    row.vendor_id = vendor.id
    row.label = f"{vendor.name} - {pump.name} - {model.model_code}"
    row.vendor_name = vendor.name
    row.pump_name = pump.name
    row.model_code = model.model_code
    row.summary = pump.ai_summary or pump.description or vendor.ai_summary

    # ---------- categorical ----------
    row.vendor_country = vendor.country or vendor.hq_country
    row.manufacturing_countries = vendor.manufacturing_countries
    row.country_of_origin = delivery.country_of_origin if delivery else None
    row.pump_type = pump.pump_type
    row.applicable_standard = pump.applicable_standard
    row.service_application = pump.service_application
    row.area_classification = _enum_text(technical, "area_classification")
    row.seal_system_type = _enum_text(technical, "seal_system_type")
    row.driver_type = _enum_text(technical, "driver_type")
    row.material_class = technical.material_class if technical else None
    row.certifications = collect_certifications(technical, operational)
    row.incoterms_offered = delivery.incoterms_offered if delivery else None
    row.vendor_approval_status = vendor.approval_status
    row.vendor_tier = _enum_text(vendor, "vendor_tier")
    row.fpso_experience = (
        operational.fpso_experience if operational else vendor.fpso_offshore_experience
    )
    row.nace_compliant = technical.nace_mr0175_compliant if technical else None

    # ---------- numeric ----------
    row.rated_capacity_m3h = technical.rated_capacity_m3h if technical else None
    row.rated_head_m = technical.rated_head_m if technical else None
    row.npsh_required_m = technical.npsh_required_m if technical else None
    row.hydraulic_efficiency_pct = technical.hydraulic_efficiency_pct if technical else None
    row.rated_speed_rpm = technical.rated_speed_rpm if technical else None
    row.rated_power_kw = technical.rated_power_kw if technical else None
    row.fluid_temperature_max_c = technical.fluid_temperature_max_c if technical else None
    row.casing_design_pressure_barg = technical.casing_design_pressure_barg if technical else None
    row.base_price_usd = commercial.base_price_usd if commercial else None
    row.standard_lead_time_weeks = delivery.standard_lead_time_weeks if delivery else None
    row.expedited_lead_time_weeks = delivery.expedited_lead_time_weeks if delivery else None
    row.dry_weight_kg = dimensional.dry_weight_kg if dimensional else None
    row.operating_weight_kg = dimensional.operating_weight_kg if dimensional else None
    row.footprint_area_m2 = dimensional.footprint_area_m2 if dimensional else None
    row.on_time_delivery_pct = (
        delivery.historical_on_time_delivery_pct if delivery else vendor.on_time_delivery_pct
    )
    row.units_installed = operational.units_installed_operating if operational else None
    row.mtbf_hours = operational.mtbf_hours if operational else None

    # ---------- quality ----------
    row.confidence_level = model.confidence_level
    row.verification_status = model.verification_status

    # Recomputed here because this is the one place that already holds every current
    # spec, and it runs on every change. Computing it anywhere else would cost six more
    # queries against a database 300ms away; not computing it at all is what left the
    # column NULL on all 84 models, the quality dashboard averaging nothing and the
    # "sort by completeness" order a no-op.
    row.data_completeness_pct = completeness.refresh_model(
        db,
        model,
        pump,
        {
            "technical": technical,
            "commercial": commercial,
            "dimensional": dimensional,
            "delivery": delivery,
            "operational": operational,
            "administrative": administrative,
        },
    )
    row.open_flag_count = int(open_flags)
    row.is_shared_master = model.is_shared_master
    row.index_version = INDEX_VERSION
    row.indexed_at = datetime.now(UTC)

    # The haystack the tsvector is generated from by the DB trigger.
    row.searchable_text = _text_chunk(
        vendor.name,
        vendor.aliases,
        vendor.description,
        vendor.hq_city,
        pump.name,
        pump.product_family,
        pump.description,
        pump.handled_fluids,
        pump.additional_standards,
        pump.standard_edition,
        pump.pump_type_raw,
        model.size_designation,
        model.frame_size,
        model.tag_number,
        model.project_reference,
        technical.material_class if technical else None,
        technical.casing_material if technical else None,
        technical.impeller_material if technical else None,
        technical.seal_manufacturer if technical else None,
        technical.seal_piping_plan if technical else None,
        technical.api_610_type_code if technical else None,
        technical.driver_manufacturer if technical else None,
        technical.external_coating_spec if technical else None,
        technical.spares_interchangeable_with if technical else None,
        row.certifications,
        delivery.manufacturing_locations if delivery else None,
        operational.harsh_environment_experience if operational else None,
        operational.nearest_service_center if operational else None,
        administrative.legal_entity_name if administrative else None,
        administrative.local_agent_name if administrative else None,
    )
    db.flush()
    return row


def reindex_vendor(db: Session, vendor_id: uuid.UUID) -> int:
    """Reindex every model belonging to a vendor. Returns the number of rows touched."""
    model_ids = db.scalars(
        select(PumpModel.id)
        .join(Pump, Pump.id == PumpModel.pump_id)
        .where(Pump.vendor_id == vendor_id, PumpModel.deleted_at.is_(None))
    ).all()
    for model_id in model_ids:
        reindex_pump_model(db, model_id)
    return len(model_ids)


def reindex_all(db: Session, tenant_id: uuid.UUID | None = None, limit: int | None = None) -> int:
    query = select(PumpModel.id).where(PumpModel.deleted_at.is_(None))
    if tenant_id is not None:
        query = query.where(PumpModel.tenant_id == tenant_id)
    if limit:
        query = query.limit(limit)
    ids = db.scalars(query).all()
    for model_id in ids:
        reindex_pump_model(db, model_id)
    log.info("indexing.reindex_all", rows=len(ids), tenant_id=str(tenant_id) if tenant_id else None)
    return len(ids)
