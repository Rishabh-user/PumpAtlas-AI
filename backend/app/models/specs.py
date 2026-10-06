"""The six intelligence spec tables.

Design rules that apply to all of them:

* **SI-normalised columns.** Numeric columns carry an explicit unit suffix
  (``_m3h``, ``_m``, ``_kw``, ``_kg``, ``_mm``, ``_barg``, ``_c``, ``_usd``).
  Whatever unit the source used is preserved in ``source_units`` so a reviewer can
  always see the original figure.
* **Versioned, never overwritten.** Updating a spec inserts a new row with
  ``version = previous + 1`` and flips the old row's ``is_current`` to false. That is
  the change-tracking / version-history feature.
* **Traceable.** ``source_id`` and ``ai_job_id`` say where the row came from;
  per-field attribution lives in ``field_provenance``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey, Versioned
from app.models.enums import (
    AreaClassification,
    ConfidenceLevel,
    DriverType,
    Incoterm,
    SealSystemType,
    VerificationStatus,
)
from app.models.types import Json, Money, Quantity, Ratio, pg_enum

if TYPE_CHECKING:
    from app.models.pump import PumpModel


class SpecBase(UUIDPrimaryKey, Timestamps, TenantScoped, Versioned):
    """Columns shared by every spec table."""

    @declared_attr
    def pump_model_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("pump_models.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def source_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"))

    @declared_attr
    def ai_job_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_jobs.id", ondelete="SET NULL"))

    @declared_attr
    def created_by_user_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    @declared_attr
    def confidence_level(cls) -> Mapped[ConfidenceLevel]:  # noqa: N805
        return mapped_column(
            pg_enum(ConfidenceLevel, "confidence_level"),
            nullable=False,
            default=ConfidenceLevel.UNKNOWN,
        )

    @declared_attr
    def verification_status(cls) -> Mapped[VerificationStatus]:  # noqa: N805
        return mapped_column(
            pg_enum(VerificationStatus, "verification_status"),
            nullable=False,
            default=VerificationStatus.UNVERIFIED,
        )

    @declared_attr
    def source_units(cls) -> Mapped[dict]:  # noqa: N805
        return mapped_column(
            Json,
            nullable=False,
            default=dict,
            comment='Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"}',
        )

    @declared_attr
    def notes(cls) -> Mapped[str | None]:  # noqa: N805
        return mapped_column(Text)

    @declared_attr
    def extra(cls) -> Mapped[dict]:  # noqa: N805
        return mapped_column(
            Json, nullable=False, default=dict, comment="Fields not yet promoted to columns"
        )

    @declared_attr
    def data_submission_date(cls) -> Mapped[date | None]:  # noqa: N805
        return mapped_column(Date, comment="Date the supplier or analyst submitted this data")


class TechnicalSpec(SpecBase, Base):
    """Hydraulic, mechanical, material, certification and testing data."""

    __tablename__ = "technical_specs"
    __table_args__ = (
        UniqueConstraint("pump_model_id", "version"),
        Index("ix_technical_specs_current", "pump_model_id", "is_current"),
        Index("ix_technical_specs_duty", "rated_capacity_m3h", "rated_head_m"),
        Index("ix_technical_specs_area", "area_classification"),
    )

    # ---------- standard compliance ----------
    standard_compliance_notes: Mapped[str | None] = mapped_column(Text)
    api_610_type_code: Mapped[str | None] = mapped_column(
        String(16), comment="OH2 / BB3 / VS4 ... as declared on the datasheet"
    )
    deviations_to_standard: Mapped[str | None] = mapped_column(Text)

    # ---------- hydraulic duty point ----------
    rated_capacity_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    min_capacity_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    max_capacity_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    min_continuous_stable_flow_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    bep_capacity_m3h: Mapped[Decimal | None] = mapped_column(Quantity)
    rated_head_m: Mapped[Decimal | None] = mapped_column(Quantity)
    max_head_m: Mapped[Decimal | None] = mapped_column(Quantity)
    shutoff_head_m: Mapped[Decimal | None] = mapped_column(Quantity)
    differential_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)
    npsh_required_m: Mapped[Decimal | None] = mapped_column(Quantity)
    npsh_available_m: Mapped[Decimal | None] = mapped_column(Quantity)
    npsh_margin_m: Mapped[Decimal | None] = mapped_column(Quantity)
    hydraulic_efficiency_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    bep_efficiency_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    rated_power_kw: Mapped[Decimal | None] = mapped_column(Quantity)
    max_power_kw: Mapped[Decimal | None] = mapped_column(Quantity)
    specific_speed: Mapped[Decimal | None] = mapped_column(Quantity)
    suction_specific_speed: Mapped[Decimal | None] = mapped_column(Quantity)
    impeller_type: Mapped[str | None] = mapped_column(
        String(80), comment="closed | semi-open | open | vortex | double-suction"
    )
    impeller_diameter_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    number_of_vanes: Mapped[int | None] = mapped_column(Integer)
    suction_size_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    discharge_size_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    flange_rating: Mapped[str | None] = mapped_column(
        String(40), comment="e.g. ASME 300# RF, API 6A 5000 psi"
    )
    flange_facing: Mapped[str | None] = mapped_column(String(40))

    # ---------- speed and driver ----------
    rated_speed_rpm: Mapped[int | None] = mapped_column(Integer)
    min_speed_rpm: Mapped[int | None] = mapped_column(Integer)
    max_speed_rpm: Mapped[int | None] = mapped_column(Integer)
    is_variable_speed: Mapped[bool | None] = mapped_column(Boolean)
    driver_type: Mapped[DriverType | None] = mapped_column(pg_enum(DriverType, "driver_type"))
    driver_type_raw: Mapped[str | None] = mapped_column(String(160))
    driver_rated_power_kw: Mapped[Decimal | None] = mapped_column(Quantity)
    driver_manufacturer: Mapped[str | None] = mapped_column(String(160))
    driver_model: Mapped[str | None] = mapped_column(String(160))
    driver_voltage_v: Mapped[int | None] = mapped_column(Integer)
    driver_frequency_hz: Mapped[int | None] = mapped_column(Integer)
    driver_service_factor: Mapped[Decimal | None] = mapped_column(Quantity)
    driver_enclosure: Mapped[str | None] = mapped_column(
        String(40), comment="e.g. TEFC, WPII, Ex d IIB T4"
    )
    coupling_type: Mapped[str | None] = mapped_column(String(120))
    gearbox_required: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- materials of construction ----------
    material_class: Mapped[str | None] = mapped_column(
        String(24), comment="API 610 Table H.1 class, e.g. S-6, C-6, A-8, D-1"
    )
    casing_material: Mapped[str | None] = mapped_column(String(160))
    impeller_material: Mapped[str | None] = mapped_column(String(160))
    shaft_material: Mapped[str | None] = mapped_column(String(160))
    wear_parts_material: Mapped[str | None] = mapped_column(String(160))
    shaft_sleeve_material: Mapped[str | None] = mapped_column(String(160))
    gasket_material: Mapped[str | None] = mapped_column(String(160))
    fastener_material: Mapped[str | None] = mapped_column(String(160))
    nace_mr0175_compliant: Mapped[bool | None] = mapped_column(
        Boolean, comment="Sour service compliance (NACE MR0175 / ISO 15156)"
    )
    corrosion_allowance_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    material_certification: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. EN 10204 3.1 / 3.2"
    )

    # ---------- seal system ----------
    seal_system_type: Mapped[SealSystemType | None] = mapped_column(
        pg_enum(SealSystemType, "seal_system_type")
    )
    seal_system_type_raw: Mapped[str | None] = mapped_column(String(160))
    seal_api_682_category: Mapped[str | None] = mapped_column(
        String(24), comment="Category 1 / 2 / 3"
    )
    seal_arrangement: Mapped[str | None] = mapped_column(
        String(80), comment="single | dual pressurised | dual unpressurised"
    )
    seal_piping_plan: Mapped[str | None] = mapped_column(
        String(80), comment="API 682 flush plan, e.g. Plan 11 + Plan 52"
    )
    seal_manufacturer: Mapped[str | None] = mapped_column(String(160))
    seal_model: Mapped[str | None] = mapped_column(String(160))
    seal_face_materials: Mapped[str | None] = mapped_column(String(200))
    seal_elastomer: Mapped[str | None] = mapped_column(String(120))
    barrier_buffer_fluid: Mapped[str | None] = mapped_column(String(160))
    seal_support_system_scope: Mapped[str | None] = mapped_column(Text)

    # ---------- bearings and lubrication ----------
    radial_bearing_type: Mapped[str | None] = mapped_column(String(120))
    thrust_bearing_type: Mapped[str | None] = mapped_column(String(120))
    bearing_arrangement: Mapped[str | None] = mapped_column(String(120))
    bearing_manufacturer: Mapped[str | None] = mapped_column(String(160))
    bearing_life_hours: Mapped[int | None] = mapped_column(Integer)
    lubrication_type: Mapped[str | None] = mapped_column(
        String(80), comment="ring oil | flood | pressurised | grease | oil mist"
    )
    lubricant_grade: Mapped[str | None] = mapped_column(String(80))
    lube_oil_system_scope: Mapped[str | None] = mapped_column(Text)
    bearing_isolators: Mapped[str | None] = mapped_column(String(120))
    bearing_temperature_monitoring: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- area classification ----------
    area_classification: Mapped[AreaClassification | None] = mapped_column(
        pg_enum(AreaClassification, "area_classification")
    )
    area_classification_raw: Mapped[str | None] = mapped_column(String(160))
    gas_group: Mapped[str | None] = mapped_column(String(24), comment="IIA / IIB / IIC")
    temperature_class: Mapped[str | None] = mapped_column(String(16), comment="T1 - T6")
    equipment_protection_level: Mapped[str | None] = mapped_column(String(24))
    ingress_protection: Mapped[str | None] = mapped_column(String(16), comment="e.g. IP66")
    atex_certified: Mapped[bool | None] = mapped_column(Boolean)
    iecex_certified: Mapped[bool | None] = mapped_column(Boolean)
    ex_certificate_numbers: Mapped[list | None] = mapped_column(ARRAY(String(80)))

    # ---------- casing design rating ----------
    casing_type: Mapped[str | None] = mapped_column(
        String(80), comment="radially split | axially split | barrel | double casing"
    )
    casing_design_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)
    max_allowable_working_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)
    casing_design_temperature_min_c: Mapped[Decimal | None] = mapped_column(Quantity)
    casing_design_temperature_max_c: Mapped[Decimal | None] = mapped_column(Quantity)
    hydrostatic_test_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)
    pressure_class: Mapped[str | None] = mapped_column(
        String(40), comment="ASME/ANSI class or API rating of the casing"
    )
    casing_design_code: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. ASME VIII Div.1, PED 2014/68/EU"
    )
    nozzle_load_capability: Mapped[str | None] = mapped_column(
        String(160), comment="e.g. 2x API 610 Table 5 allowable"
    )

    # ---------- testing requirements ----------
    performance_test_required: Mapped[bool | None] = mapped_column(Boolean)
    performance_test_grade: Mapped[str | None] = mapped_column(
        String(40), comment="e.g. API 610 Table 16 / HI 14.6 grade 1B"
    )
    npsh_test_required: Mapped[bool | None] = mapped_column(Boolean)
    mechanical_run_test_required: Mapped[bool | None] = mapped_column(Boolean)
    mechanical_run_duration_hours: Mapped[Decimal | None] = mapped_column(Quantity)
    hydrostatic_test_required: Mapped[bool | None] = mapped_column(Boolean)
    string_test_required: Mapped[bool | None] = mapped_column(Boolean)
    complete_unit_test_required: Mapped[bool | None] = mapped_column(Boolean)
    nde_requirements: Mapped[str | None] = mapped_column(
        Text, comment="Non-destructive examination scope: RT / UT / MPI / DPI extents"
    )
    witness_level: Mapped[str | None] = mapped_column(
        String(40), comment="witnessed | observed | monitored | unwitnessed"
    )
    test_standard: Mapped[str | None] = mapped_column(String(120))
    noise_limit_dba: Mapped[Decimal | None] = mapped_column(Quantity)
    vibration_limit_mm_s: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- coating / painting ----------
    external_coating_spec: Mapped[str | None] = mapped_column(
        String(200), comment="e.g. NORSOK M-501 System 1"
    )
    internal_coating_spec: Mapped[str | None] = mapped_column(String(200))
    paint_system_standard: Mapped[str | None] = mapped_column(
        String(120), comment="NORSOK M-501 | ISO 12944 | client spec"
    )
    coating_dft_microns: Mapped[Decimal | None] = mapped_column(Quantity)
    surface_preparation: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. ISO 8501-1 Sa 2.5"
    )
    corrosion_category: Mapped[str | None] = mapped_column(
        String(24), comment="ISO 12944 category, e.g. CX offshore"
    )
    galvanic_protection: Mapped[str | None] = mapped_column(String(160))

    # ---------- instrumentation and controls ----------
    instrumentation_scope: Mapped[str | None] = mapped_column(Text)
    vibration_monitoring: Mapped[str | None] = mapped_column(
        String(160), comment="API 670 accelerometers / velocity probes / none"
    )
    api_670_compliant: Mapped[bool | None] = mapped_column(Boolean)
    temperature_monitoring: Mapped[str | None] = mapped_column(String(160))
    pressure_instrumentation: Mapped[str | None] = mapped_column(String(160))
    control_interface_protocol: Mapped[str | None] = mapped_column(
        String(120), comment="Modbus TCP | PROFIBUS DP | HART | FF | Ethernet/IP"
    )
    local_control_panel: Mapped[bool | None] = mapped_column(Boolean)
    junction_box_certification: Mapped[str | None] = mapped_column(String(120))
    condition_monitoring_ready: Mapped[bool | None] = mapped_column(Boolean)
    signal_list: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    # ---------- third-party / marine certification ----------
    marine_class_society: Mapped[str | None] = mapped_column(
        String(80), comment="DNV | ABS | LR | BV | ClassNK | RINA | none"
    )
    marine_certification_type: Mapped[str | None] = mapped_column(
        String(120), comment="Type approval | product certificate | unit certificate"
    )
    third_party_certifications: Mapped[list | None] = mapped_column(
        ARRAY(String(120)), comment="Free list, e.g. CE/PED, ATEX, IECEx, UKCA"
    )
    certificate_numbers: Mapped[list | None] = mapped_column(ARRAY(String(120)))
    certification_valid_until: Mapped[date | None] = mapped_column(Date)
    inspection_authority: Mapped[str | None] = mapped_column(String(120))

    # ---------- spares interchangeability ----------
    spares_interchangeable_with: Mapped[list | None] = mapped_column(
        ARRAY(String(160)), comment="Model codes sharing rotating elements / wear parts"
    )
    parts_commonality_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    common_rotating_element: Mapped[bool | None] = mapped_column(Boolean)
    interchangeability_notes: Mapped[str | None] = mapped_column(Text)
    obsolescence_risk: Mapped[str | None] = mapped_column(String(24), comment="low | medium | high")

    # ---------- operating envelope (for filtering) ----------
    fluid_handled: Mapped[str | None] = mapped_column(String(160))
    fluid_specific_gravity: Mapped[Decimal | None] = mapped_column(Quantity)
    fluid_viscosity_cst: Mapped[Decimal | None] = mapped_column(Quantity)
    fluid_temperature_min_c: Mapped[Decimal | None] = mapped_column(Quantity)
    fluid_temperature_max_c: Mapped[Decimal | None] = mapped_column(Quantity)
    solids_content_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    h2s_service: Mapped[bool | None] = mapped_column(Boolean)
    suction_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)
    discharge_pressure_barg: Mapped[Decimal | None] = mapped_column(Quantity)

    pump_model: Mapped[PumpModel] = relationship(back_populates="technical_specs")


class CommercialSpec(SpecBase, Base):
    """Pricing, terms, warranty and life-cycle economics."""

    __tablename__ = "commercial_specs"
    __table_args__ = (
        UniqueConstraint("pump_model_id", "version"),
        Index("ix_commercial_specs_current", "pump_model_id", "is_current"),
        Index("ix_commercial_specs_price", "base_price_usd"),
    )

    # ---------- base price ----------
    base_price_amount: Mapped[Decimal | None] = mapped_column(Money)
    base_price_currency: Mapped[str | None] = mapped_column(String(3), comment="ISO 4217")
    base_price_usd: Mapped[Decimal | None] = mapped_column(
        Money, comment="Converted at fx_rate_used for cross-vendor comparison"
    )
    fx_rate_used: Mapped[Decimal | None] = mapped_column(Quantity)
    fx_rate_date: Mapped[date | None] = mapped_column(Date)
    price_basis: Mapped[str | None] = mapped_column(
        String(200), comment="Scope covered by the price: bare shaft, package, skid"
    )
    price_validity_days: Mapped[int | None] = mapped_column(Integer)
    quotation_reference: Mapped[str | None] = mapped_column(String(160))
    quotation_date: Mapped[date | None] = mapped_column(Date)
    incoterm: Mapped[Incoterm | None] = mapped_column(pg_enum(Incoterm, "incoterm"))
    incoterm_named_place: Mapped[str | None] = mapped_column(String(160))

    # ---------- payment terms ----------
    payment_terms: Mapped[str | None] = mapped_column(
        Text, comment="e.g. 20% advance / 70% on delivery / 10% on FAC"
    )
    advance_payment_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    payment_days_net: Mapped[int | None] = mapped_column(Integer)
    letter_of_credit_required: Mapped[bool | None] = mapped_column(Boolean)
    retention_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    liquidated_damages_terms: Mapped[str | None] = mapped_column(Text)
    liquidated_damages_cap_pct: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- warranty ----------
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    warranty_basis: Mapped[str | None] = mapped_column(
        String(120), comment="from delivery | from commissioning | whichever is earlier"
    )
    warranty_scope: Mapped[str | None] = mapped_column(Text)
    extended_warranty_available: Mapped[bool | None] = mapped_column(Boolean)
    extended_warranty_cost_pct: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- spares pricing ----------
    spares_price_amount: Mapped[Decimal | None] = mapped_column(Money)
    spares_price_currency: Mapped[str | None] = mapped_column(String(3))
    commissioning_spares_usd: Mapped[Decimal | None] = mapped_column(Money)
    two_year_spares_usd: Mapped[Decimal | None] = mapped_column(Money)
    capital_spares_usd: Mapped[Decimal | None] = mapped_column(Money)
    spares_price_list: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Itemised spare part price list"
    )
    spares_discount_pct: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- escalation and discounts ----------
    price_escalation_formula: Mapped[str | None] = mapped_column(
        Text, comment="Contractual escalation clause as written"
    )
    escalation_index_reference: Mapped[str | None] = mapped_column(
        String(160), comment="e.g. CEPCI, Eurostat MIG, BLS PPI 3561"
    )
    escalation_base_date: Mapped[date | None] = mapped_column(Date)
    escalation_annual_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    discount_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    volume_discount_schedule: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment='e.g. {"5": 4.5, "10": 8.0} units to pct'
    )
    frame_agreement_reference: Mapped[str | None] = mapped_column(String(160))

    # ---------- benchmarking and life-cycle ----------
    historical_price_benchmark_usd: Mapped[Decimal | None] = mapped_column(Money)
    benchmark_source: Mapped[str | None] = mapped_column(String(200))
    benchmark_date: Mapped[date | None] = mapped_column(Date)
    benchmark_variance_pct: Mapped[Decimal | None] = mapped_column(
        Quantity, comment="Offer vs benchmark; negative means cheaper than benchmark"
    )
    lifecycle_cost_usd: Mapped[Decimal | None] = mapped_column(Money)
    lifecycle_period_years: Mapped[int | None] = mapped_column(Integer)
    energy_cost_per_year_usd: Mapped[Decimal | None] = mapped_column(Money)
    maintenance_cost_per_year_usd: Mapped[Decimal | None] = mapped_column(Money)
    lifecycle_assumptions: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    # ---------- taxes, duties, local content ----------
    taxes_included: Mapped[bool | None] = mapped_column(Boolean)
    tax_details: Mapped[str | None] = mapped_column(Text)
    import_duty_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    customs_hs_code: Mapped[str | None] = mapped_column(String(24))
    local_content_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    local_content_scheme: Mapped[str | None] = mapped_column(
        String(160), comment="e.g. NOGICD Nigeria, ICV Saudi Arabia, Petrobras local content"
    )
    local_content_certificate: Mapped[str | None] = mapped_column(String(160))
    withholding_tax_pct: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- vendor financial capability snapshot ----------
    financial_standing_summary: Mapped[str | None] = mapped_column(Text)
    bonding_capability: Mapped[str | None] = mapped_column(Text)
    insurance_capability: Mapped[str | None] = mapped_column(Text)
    parent_company_guarantee_available: Mapped[bool | None] = mapped_column(Boolean)

    pump_model: Mapped[PumpModel] = relationship(back_populates="commercial_specs")


class DimensionalSpec(SpecBase, Base):
    """Weights, envelope, lifting and foundation data - the FPSO topside constraint set."""

    __tablename__ = "dimensional_specs"
    __table_args__ = (
        UniqueConstraint("pump_model_id", "version"),
        Index("ix_dimensional_specs_current", "pump_model_id", "is_current"),
        Index("ix_dimensional_specs_weight", "dry_weight_kg"),
    )

    # ---------- weights ----------
    dry_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    operating_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    shipping_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    pump_only_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    driver_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    baseplate_weight_kg: Mapped[Decimal | None] = mapped_column(Quantity)
    max_maintenance_lift_weight_kg: Mapped[Decimal | None] = mapped_column(
        Quantity, comment="Heaviest single item to be lifted during maintenance"
    )
    max_maintenance_lift_item: Mapped[str | None] = mapped_column(String(160))

    # ---------- shipping envelope ----------
    crate_length_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    crate_width_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    crate_height_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    crate_volume_m3: Mapped[Decimal | None] = mapped_column(Quantity)
    number_of_packages: Mapped[int | None] = mapped_column(Integer)
    packaging_type: Mapped[str | None] = mapped_column(
        String(160), comment="seaworthy wooden case | vacuum barrier | container | skid"
    )
    packaging_standard: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. ISPM 15, MIL-STD-2073"
    )
    preservation_period_months: Mapped[int | None] = mapped_column(Integer)

    # ---------- footprint ----------
    baseplate_length_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    baseplate_width_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    baseplate_height_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    baseplate_type: Mapped[str | None] = mapped_column(
        String(120), comment="API 610 baseplate | skid | fabricated | grouted"
    )
    footprint_area_m2: Mapped[Decimal | None] = mapped_column(Quantity)
    overall_length_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    overall_width_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    overall_height_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    maintenance_access_envelope_mm: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Clearances needed per side for pull-out"
    )

    # ---------- centre of gravity and lifting ----------
    cog_x_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    cog_y_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    cog_z_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    cog_reference_datum: Mapped[str | None] = mapped_column(String(160))
    lifting_points_count: Mapped[int | None] = mapped_column(Integer)
    lifting_point_details: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    lifting_arrangement_standard: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. DNV 2.7-3, EN 13155"
    )
    certified_lifting_set_included: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- foundation loading ----------
    static_load_kn: Mapped[Decimal | None] = mapped_column(Quantity)
    dynamic_load_kn: Mapped[Decimal | None] = mapped_column(Quantity)
    torque_reaction_knm: Mapped[Decimal | None] = mapped_column(Quantity)
    anchor_bolt_count: Mapped[int | None] = mapped_column(Integer)
    anchor_bolt_size: Mapped[str | None] = mapped_column(String(40))
    foundation_loading_notes: Mapped[str | None] = mapped_column(Text)
    grouting_requirement: Mapped[str | None] = mapped_column(String(160))
    vibration_isolation_required: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- FPSO topside module envelope ----------
    fpso_module_space_envelope: Mapped[str | None] = mapped_column(
        Text, comment="Declared L x W x H envelope inside the topside module"
    )
    fpso_module_envelope_length_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    fpso_module_envelope_width_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    fpso_module_envelope_height_mm: Mapped[Decimal | None] = mapped_column(Quantity)
    deck_area_required_m2: Mapped[Decimal | None] = mapped_column(Quantity)
    module_integration_notes: Mapped[str | None] = mapped_column(Text)
    motion_design_criteria: Mapped[str | None] = mapped_column(
        String(200), comment="Vessel motions / accelerations the unit is designed for"
    )

    pump_model: Mapped[PumpModel] = relationship(back_populates="dimensional_specs")


class DeliverySpec(SpecBase, Base):
    """Lead time, logistics, FAT and export-control data."""

    __tablename__ = "delivery_specs"
    __table_args__ = (
        UniqueConstraint("pump_model_id", "version"),
        Index("ix_delivery_specs_current", "pump_model_id", "is_current"),
        Index("ix_delivery_specs_lead_time", "standard_lead_time_weeks"),
    )

    # ---------- lead time ----------
    standard_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    lead_time_basis: Mapped[str | None] = mapped_column(
        String(160), comment="from PO | from approved drawings | from LOI"
    )
    expedited_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    expedite_premium_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    expedite_premium_usd: Mapped[Decimal | None] = mapped_column(Money)
    expedite_conditions: Mapped[str | None] = mapped_column(Text)
    engineering_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    manufacturing_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- manufacturing footprint ----------
    manufacturing_locations: Mapped[list | None] = mapped_column(
        ARRAY(String(160)), comment="City, country per plant"
    )
    primary_manufacturing_country: Mapped[str | None] = mapped_column(String(2), index=True)
    assembly_location: Mapped[str | None] = mapped_column(String(160))
    testing_location: Mapped[str | None] = mapped_column(String(160))
    workshop_capacity_notes: Mapped[str | None] = mapped_column(Text)
    current_backlog_weeks: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- logistics ----------
    logistics_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    shipping_mode: Mapped[str | None] = mapped_column(
        String(80), comment="sea | air | road | multimodal"
    )
    port_of_loading: Mapped[str | None] = mapped_column(String(160))
    incoterms_offered: Mapped[list | None] = mapped_column(ARRAY(String(8)))
    preferred_incoterm: Mapped[Incoterm | None] = mapped_column(pg_enum(Incoterm, "incoterm"))
    freight_cost_estimate_usd: Mapped[Decimal | None] = mapped_column(Money)
    oversize_cargo: Mapped[bool | None] = mapped_column(Boolean)
    logistics_notes: Mapped[str | None] = mapped_column(Text)

    # ---------- documentation ----------
    documentation_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    final_documentation_weeks_after_delivery: Mapped[Decimal | None] = mapped_column(Quantity)
    document_deliverables_list: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    documentation_language: Mapped[str | None] = mapped_column(String(80))
    as_built_documentation_included: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- FAT ----------
    fat_lead_time_weeks: Mapped[Decimal | None] = mapped_column(
        Quantity, comment="Weeks from PO to FAT readiness"
    )
    fat_duration_days: Mapped[Decimal | None] = mapped_column(Quantity)
    fat_notice_period_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    fat_location: Mapped[str | None] = mapped_column(String(160))
    fat_witness_slots: Mapped[int | None] = mapped_column(Integer)
    sat_supported: Mapped[bool | None] = mapped_column(Boolean)
    fat_scheduling_notes: Mapped[str | None] = mapped_column(Text)

    # ---------- delivery performance ----------
    historical_on_time_delivery_pct: Mapped[Decimal | None] = mapped_column(Ratio)
    otd_sample_size: Mapped[int | None] = mapped_column(
        Integer, comment="Number of orders behind the OTD figure"
    )
    otd_measurement_period: Mapped[str | None] = mapped_column(String(120))
    average_delay_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    delivery_risk_notes: Mapped[str | None] = mapped_column(Text)

    # ---------- long-lead dependencies ----------
    long_lead_components: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment='e.g. {"castings": {"weeks": 22, "source": "EU foundry"}}',
    )
    critical_subsupplier_dependencies: Mapped[list | None] = mapped_column(ARRAY(String(200)))
    single_source_components: Mapped[list | None] = mapped_column(ARRAY(String(200)))
    forging_casting_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)

    # ---------- origin and export control ----------
    country_of_origin: Mapped[str | None] = mapped_column(String(2), index=True)
    export_control_classification: Mapped[str | None] = mapped_column(
        String(80), comment="e.g. EAR99, ECCN 2B999, EU dual-use item"
    )
    export_licence_required: Mapped[bool | None] = mapped_column(Boolean)
    export_licence_lead_time_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    restricted_destinations: Mapped[list | None] = mapped_column(ARRAY(String(2)))
    us_content_pct: Mapped[Decimal | None] = mapped_column(Quantity)
    export_control_notes: Mapped[str | None] = mapped_column(Text)

    pump_model: Mapped[PumpModel] = relationship(back_populates="delivery_specs")


class OperationalSpec(SpecBase, Base):
    """Track record, references, service network, HSE and vendor qualification."""

    __tablename__ = "operational_specs"
    __table_args__ = (
        UniqueConstraint("pump_model_id", "version"),
        Index("ix_operational_specs_current", "pump_model_id", "is_current"),
        Index("ix_operational_specs_fpso", "fpso_experience"),
    )

    # ---------- references and installed base ----------
    reference_list: Mapped[dict] = mapped_column(
        Json,
        nullable=False,
        default=dict,
        comment='[{"client":"...","project":"...","year":2021,"units":4,"country":"BR"}]',
    )
    reference_count: Mapped[int | None] = mapped_column(Integer)
    units_supplied: Mapped[int | None] = mapped_column(Integer)
    units_installed_operating: Mapped[int | None] = mapped_column(Integer)
    first_installation_year: Mapped[int | None] = mapped_column(Integer)
    cumulative_operating_hours: Mapped[int | None] = mapped_column(Integer)
    reference_contactable: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- reliability ----------
    mtbf_hours: Mapped[int | None] = mapped_column(Integer)
    mttr_hours: Mapped[Decimal | None] = mapped_column(Quantity)
    availability_pct: Mapped[Decimal | None] = mapped_column(Ratio)
    failure_rate_per_year: Mapped[Decimal | None] = mapped_column(Quantity)
    common_failure_modes: Mapped[str | None] = mapped_column(Text)
    reliability_data_source: Mapped[str | None] = mapped_column(
        String(200), comment="e.g. OREDA, client CMMS, vendor claim"
    )
    seal_mtbf_hours: Mapped[int | None] = mapped_column(Integer)
    overhaul_interval_hours: Mapped[int | None] = mapped_column(Integer)

    # ---------- offshore / FPSO experience ----------
    fpso_experience: Mapped[bool | None] = mapped_column(Boolean)
    fpso_units_supplied: Mapped[int | None] = mapped_column(Integer)
    fpso_project_references: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    offshore_experience_years: Mapped[int | None] = mapped_column(Integer)
    harsh_environment_experience: Mapped[str | None] = mapped_column(
        String(200), comment="North Sea, Arctic, deepwater Brazil, West Africa ..."
    )
    subsea_experience: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- after-sales ----------
    service_network_countries: Mapped[list | None] = mapped_column(ARRAY(String(2)))
    service_centers: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    nearest_service_center: Mapped[str | None] = mapped_column(String(200))
    response_time_hours: Mapped[Decimal | None] = mapped_column(Quantity)
    field_service_engineers_count: Mapped[int | None] = mapped_column(Integer)
    service_agreement_options: Mapped[str | None] = mapped_column(Text)
    remote_monitoring_offered: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- spares availability ----------
    post_warranty_spares_years: Mapped[int | None] = mapped_column(Integer)
    spares_availability_commitment: Mapped[str | None] = mapped_column(Text)
    spares_stock_locations: Mapped[list | None] = mapped_column(ARRAY(String(160)))
    typical_spares_delivery_weeks: Mapped[Decimal | None] = mapped_column(Quantity)
    obsolescence_management_policy: Mapped[str | None] = mapped_column(Text)

    # ---------- training and commissioning ----------
    training_offered: Mapped[bool | None] = mapped_column(Boolean)
    training_scope: Mapped[str | None] = mapped_column(Text)
    training_days_included: Mapped[Decimal | None] = mapped_column(Quantity)
    commissioning_support_included: Mapped[bool | None] = mapped_column(Boolean)
    commissioning_support_days: Mapped[Decimal | None] = mapped_column(Quantity)
    supervision_day_rate_usd: Mapped[Decimal | None] = mapped_column(Money)
    documentation_training_language: Mapped[str | None] = mapped_column(String(80))

    # ---------- HSE ----------
    hse_trir: Mapped[Decimal | None] = mapped_column(
        Quantity, comment="Total recordable incident rate"
    )
    hse_ltifr: Mapped[Decimal | None] = mapped_column(
        Quantity, comment="Lost time injury frequency rate"
    )
    hse_fatalities_last_5y: Mapped[int | None] = mapped_column(Integer)
    hse_incident_history: Mapped[str | None] = mapped_column(Text)
    hse_management_system: Mapped[str | None] = mapped_column(
        String(120), comment="e.g. ISO 45001 certified"
    )
    hse_audit_date: Mapped[date | None] = mapped_column(Date)

    # ---------- QA/QC and qualification ----------
    qaqc_certifications: Mapped[list | None] = mapped_column(
        ARRAY(String(120)), comment="ISO 9001, ISO 14001, API Q1, ASME U stamp ..."
    )
    quality_certificate_expiry: Mapped[date | None] = mapped_column(Date)
    itp_available: Mapped[bool | None] = mapped_column(
        Boolean, comment="Inspection and test plan can be supplied"
    )
    audit_history: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    ncr_history_notes: Mapped[str | None] = mapped_column(Text)
    vendor_approval_notes: Mapped[str | None] = mapped_column(Text)
    approved_vendor_list_membership: Mapped[list | None] = mapped_column(
        ARRAY(String(160)), comment="Operator AVLs the vendor sits on"
    )

    pump_model: Mapped[PumpModel] = relationship(back_populates="operational_specs")


class AdministrativeSpec(SpecBase, Base):
    """Legal entity, representation, ESG, cybersecurity and data-quality metadata.

    Scoped to a pump model like the other spec tables, but also carries ``vendor_id``
    because legal-entity and ESG facts are properties of the supplier. The API writes
    the vendor-level fields once and reuses them across that vendor's models.
    """

    __tablename__ = "administrative_specs"
    __table_args__ = (
        UniqueConstraint("pump_model_id", "version"),
        Index("ix_administrative_specs_current", "pump_model_id", "is_current"),
        Index("ix_administrative_specs_vendor", "vendor_id"),
    )

    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE")
    )

    # ---------- legal entity ----------
    legal_entity_name: Mapped[str | None] = mapped_column(String(255))
    legal_form: Mapped[str | None] = mapped_column(
        String(80), comment="GmbH | S.p.A. | Ltd | LLC | JSC ..."
    )
    registration_number: Mapped[str | None] = mapped_column(String(80))
    registration_country: Mapped[str | None] = mapped_column(String(2))
    registration_authority: Mapped[str | None] = mapped_column(String(200))
    tax_identification_number: Mapped[str | None] = mapped_column(String(80))
    vat_number: Mapped[str | None] = mapped_column(String(80))
    lei_code: Mapped[str | None] = mapped_column(String(20), comment="ISO 17442 legal entity id")
    registered_address: Mapped[str | None] = mapped_column(Text)
    incorporation_date: Mapped[date | None] = mapped_column(Date)
    ultimate_parent_company: Mapped[str | None] = mapped_column(String(255))
    ownership_structure: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    beneficial_ownership_disclosed: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- authorized representative / agent ----------
    authorized_representative_name: Mapped[str | None] = mapped_column(String(255))
    authorized_representative_title: Mapped[str | None] = mapped_column(String(160))
    authorized_representative_email: Mapped[str | None] = mapped_column(String(320))
    authorized_representative_phone: Mapped[str | None] = mapped_column(String(64))
    local_agent_name: Mapped[str | None] = mapped_column(String(255))
    local_agent_country: Mapped[str | None] = mapped_column(String(2))
    agency_agreement_reference: Mapped[str | None] = mapped_column(String(160))
    agency_agreement_expiry: Mapped[date | None] = mapped_column(Date)
    power_of_attorney_on_file: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- ESG / sustainability ----------
    esg_report_published: Mapped[bool | None] = mapped_column(Boolean)
    esg_report_url: Mapped[str | None] = mapped_column(String(500))
    esg_rating_provider: Mapped[str | None] = mapped_column(String(120))
    esg_rating: Mapped[str | None] = mapped_column(String(40))
    scope1_emissions_tco2e: Mapped[Decimal | None] = mapped_column(Quantity)
    scope2_emissions_tco2e: Mapped[Decimal | None] = mapped_column(Quantity)
    scope3_emissions_reported: Mapped[bool | None] = mapped_column(Boolean)
    net_zero_target_year: Mapped[int | None] = mapped_column(Integer)
    iso_14001_certified: Mapped[bool | None] = mapped_column(Boolean)
    iso_50001_certified: Mapped[bool | None] = mapped_column(Boolean)
    modern_slavery_statement: Mapped[bool | None] = mapped_column(Boolean)
    anti_bribery_policy: Mapped[bool | None] = mapped_column(Boolean)
    conflict_minerals_policy: Mapped[bool | None] = mapped_column(Boolean)
    diversity_disclosures: Mapped[str | None] = mapped_column(Text)

    # ---------- cybersecurity posture ----------
    iso_27001_certified: Mapped[bool | None] = mapped_column(Boolean)
    iec_62443_compliance: Mapped[str | None] = mapped_column(
        String(80), comment="Security level claimed for OT/control scope"
    )
    soc2_report_available: Mapped[bool | None] = mapped_column(Boolean)
    penetration_test_frequency: Mapped[str | None] = mapped_column(String(80))
    security_incident_history: Mapped[str | None] = mapped_column(Text)
    supply_chain_security_program: Mapped[str | None] = mapped_column(Text)
    remote_access_policy: Mapped[str | None] = mapped_column(Text)
    cyber_insurance: Mapped[bool | None] = mapped_column(Boolean)
    cybersecurity_questionnaire_completed: Mapped[bool | None] = mapped_column(Boolean)

    # ---------- data submission and quality ----------
    submitted_by_name: Mapped[str | None] = mapped_column(String(255))
    submitted_by_organisation: Mapped[str | None] = mapped_column(String(255))
    submission_channel: Mapped[str | None] = mapped_column(
        String(80), comment="portal | email | web crawl | api | interview"
    )
    source_reference: Mapped[str | None] = mapped_column(String(500))
    data_owner: Mapped[str | None] = mapped_column(String(160))
    next_review_due: Mapped[date | None] = mapped_column(Date)
    completeness_pct: Mapped[Decimal | None] = mapped_column(Ratio)
    verification_method: Mapped[str | None] = mapped_column(
        String(200), comment="How the record was verified: document, call, site audit"
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_policy: Mapped[str | None] = mapped_column(String(160))
    confidentiality_class: Mapped[str | None] = mapped_column(
        String(40), comment="public | internal | confidential | restricted"
    )

    pump_model: Mapped[PumpModel] = relationship(back_populates="administrative_specs")
