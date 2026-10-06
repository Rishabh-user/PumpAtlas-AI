# PumpAtlas AI - data dictionary

**GENERATED FILE** - do not edit by hand.
Regenerate with `python scripts/gen_data_dictionary.py`.

PostgreSQL is the system of record. 37 tables, 1157 columns,
63 brief requirements mapped, all verified present.

---

## 1. Requirements traceability

Every intelligence field named in the product brief, and the column that holds it.
`scripts/gen_data_dictionary.py` fails if any column listed here is missing from
the models, so this table cannot go stale.

### Technical data

| Required field | Columns |
| --- | --- |
| **Applicable standard** | `pumps.applicable_standard`<br>`pumps.additional_standards`<br>`pumps.standard_edition`<br>`technical_specs.api_610_type_code`<br>`technical_specs.standard_compliance_notes`<br>`technical_specs.deviations_to_standard` |
| **Pump type** | `pumps.pump_type`<br>`pumps.pump_type_raw` |
| **Capacity and head** | `technical_specs.rated_capacity_m3h`<br>`technical_specs.min_capacity_m3h`<br>`technical_specs.max_capacity_m3h`<br>`technical_specs.min_continuous_stable_flow_m3h`<br>`technical_specs.bep_capacity_m3h`<br>`technical_specs.rated_head_m`<br>`technical_specs.max_head_m`<br>`technical_specs.shutoff_head_m`<br>`technical_specs.differential_pressure_barg` |
| **NPSH required and efficiency** | `technical_specs.npsh_required_m`<br>`technical_specs.npsh_available_m`<br>`technical_specs.npsh_margin_m`<br>`technical_specs.hydraulic_efficiency_pct`<br>`technical_specs.bep_efficiency_pct` |
| **Speed and driver** | `technical_specs.rated_speed_rpm`<br>`technical_specs.min_speed_rpm`<br>`technical_specs.max_speed_rpm`<br>`technical_specs.is_variable_speed`<br>`technical_specs.driver_type`<br>`technical_specs.driver_rated_power_kw`<br>`technical_specs.driver_manufacturer`<br>`technical_specs.driver_voltage_v`<br>`technical_specs.driver_frequency_hz`<br>`technical_specs.driver_enclosure`<br>`technical_specs.coupling_type`<br>`technical_specs.gearbox_required` |
| **Materials of construction** | `technical_specs.material_class`<br>`technical_specs.casing_material`<br>`technical_specs.impeller_material`<br>`technical_specs.shaft_material`<br>`technical_specs.wear_parts_material`<br>`technical_specs.gasket_material`<br>`technical_specs.fastener_material`<br>`technical_specs.nace_mr0175_compliant`<br>`technical_specs.corrosion_allowance_mm`<br>`technical_specs.material_certification` |
| **Seal system** | `technical_specs.seal_system_type`<br>`technical_specs.seal_api_682_category`<br>`technical_specs.seal_arrangement`<br>`technical_specs.seal_piping_plan`<br>`technical_specs.seal_manufacturer`<br>`technical_specs.seal_face_materials`<br>`technical_specs.seal_elastomer`<br>`technical_specs.barrier_buffer_fluid` |
| **Bearing type and lubrication** | `technical_specs.radial_bearing_type`<br>`technical_specs.thrust_bearing_type`<br>`technical_specs.bearing_arrangement`<br>`technical_specs.bearing_life_hours`<br>`technical_specs.lubrication_type`<br>`technical_specs.lubricant_grade`<br>`technical_specs.lube_oil_system_scope`<br>`technical_specs.bearing_isolators` |
| **Area classification** | `technical_specs.area_classification`<br>`technical_specs.gas_group`<br>`technical_specs.temperature_class`<br>`technical_specs.equipment_protection_level`<br>`technical_specs.ingress_protection`<br>`technical_specs.atex_certified`<br>`technical_specs.iecex_certified`<br>`technical_specs.ex_certificate_numbers` |
| **Casing design rating** | `technical_specs.casing_type`<br>`technical_specs.casing_design_pressure_barg`<br>`technical_specs.max_allowable_working_pressure_barg`<br>`technical_specs.casing_design_temperature_min_c`<br>`technical_specs.casing_design_temperature_max_c`<br>`technical_specs.hydrostatic_test_pressure_barg`<br>`technical_specs.pressure_class`<br>`technical_specs.casing_design_code`<br>`technical_specs.nozzle_load_capability` |
| **Testing requirements** | `technical_specs.performance_test_required`<br>`technical_specs.performance_test_grade`<br>`technical_specs.npsh_test_required`<br>`technical_specs.mechanical_run_test_required`<br>`technical_specs.hydrostatic_test_required`<br>`technical_specs.string_test_required`<br>`technical_specs.complete_unit_test_required`<br>`technical_specs.nde_requirements`<br>`technical_specs.witness_level`<br>`technical_specs.test_standard` |
| **Coating / painting specification** | `technical_specs.external_coating_spec`<br>`technical_specs.internal_coating_spec`<br>`technical_specs.paint_system_standard`<br>`technical_specs.coating_dft_microns`<br>`technical_specs.surface_preparation`<br>`technical_specs.corrosion_category`<br>`technical_specs.galvanic_protection` |
| **Instrumentation and controls interface** | `technical_specs.instrumentation_scope`<br>`technical_specs.vibration_monitoring`<br>`technical_specs.api_670_compliant`<br>`technical_specs.temperature_monitoring`<br>`technical_specs.pressure_instrumentation`<br>`technical_specs.control_interface_protocol`<br>`technical_specs.local_control_panel`<br>`technical_specs.junction_box_certification`<br>`technical_specs.condition_monitoring_ready`<br>`technical_specs.signal_list` |
| **Third-party / marine certification** | `technical_specs.marine_class_society`<br>`technical_specs.marine_certification_type`<br>`technical_specs.third_party_certifications`<br>`technical_specs.certificate_numbers`<br>`technical_specs.certification_valid_until`<br>`technical_specs.inspection_authority` |
| **Spares interchangeability** | `technical_specs.spares_interchangeable_with`<br>`technical_specs.parts_commonality_pct`<br>`technical_specs.common_rotating_element`<br>`technical_specs.interchangeability_notes`<br>`technical_specs.obsolescence_risk` |

### Commercial data

| Required field | Columns |
| --- | --- |
| **Base price and terms** | `commercial_specs.base_price_amount`<br>`commercial_specs.base_price_currency`<br>`commercial_specs.base_price_usd`<br>`commercial_specs.price_basis`<br>`commercial_specs.price_validity_days`<br>`commercial_specs.quotation_reference`<br>`commercial_specs.quotation_date`<br>`commercial_specs.incoterm`<br>`commercial_specs.incoterm_named_place` |
| **Payment terms** | `commercial_specs.payment_terms`<br>`commercial_specs.advance_payment_pct`<br>`commercial_specs.payment_days_net`<br>`commercial_specs.letter_of_credit_required`<br>`commercial_specs.retention_pct`<br>`commercial_specs.liquidated_damages_terms`<br>`commercial_specs.liquidated_damages_cap_pct` |
| **Warranty** | `commercial_specs.warranty_months`<br>`commercial_specs.warranty_basis`<br>`commercial_specs.warranty_scope`<br>`commercial_specs.extended_warranty_available`<br>`commercial_specs.extended_warranty_cost_pct` |
| **Spares pricing** | `commercial_specs.spares_price_amount`<br>`commercial_specs.spares_price_currency`<br>`commercial_specs.commissioning_spares_usd`<br>`commercial_specs.two_year_spares_usd`<br>`commercial_specs.capital_spares_usd`<br>`commercial_specs.spares_price_list`<br>`commercial_specs.spares_discount_pct` |
| **Price escalation formula** | `commercial_specs.price_escalation_formula`<br>`commercial_specs.escalation_index_reference`<br>`commercial_specs.escalation_base_date`<br>`commercial_specs.escalation_annual_pct` |
| **Discount / volume pricing** | `commercial_specs.discount_pct`<br>`commercial_specs.volume_discount_schedule`<br>`commercial_specs.frame_agreement_reference` |
| **Historical price benchmark** | `commercial_specs.historical_price_benchmark_usd`<br>`commercial_specs.benchmark_source`<br>`commercial_specs.benchmark_date`<br>`commercial_specs.benchmark_variance_pct` |
| **Life-cycle cost estimate** | `commercial_specs.lifecycle_cost_usd`<br>`commercial_specs.lifecycle_period_years`<br>`commercial_specs.energy_cost_per_year_usd`<br>`commercial_specs.maintenance_cost_per_year_usd`<br>`commercial_specs.lifecycle_assumptions` |
| **Taxes, duties and local content** | `commercial_specs.taxes_included`<br>`commercial_specs.tax_details`<br>`commercial_specs.import_duty_pct`<br>`commercial_specs.customs_hs_code`<br>`commercial_specs.local_content_pct`<br>`commercial_specs.local_content_scheme`<br>`commercial_specs.local_content_certificate`<br>`commercial_specs.withholding_tax_pct` |
| **Financial standing** | `vendors.annual_revenue_usd`<br>`vendors.revenue_year`<br>`vendors.employee_count`<br>`vendors.credit_rating`<br>`vendors.credit_rating_agency`<br>`vendors.dun_bradstreet_number`<br>`vendors.financial_standing_notes`<br>`commercial_specs.financial_standing_summary`<br>`commercial_specs.parent_company_guarantee_available` |
| **Bonding and insurance capability** | `vendors.bonding_capacity_usd`<br>`vendors.can_provide_performance_bond`<br>`vendors.can_provide_advance_payment_guarantee`<br>`vendors.insurance_coverage_usd`<br>`vendors.insurance_details`<br>`commercial_specs.bonding_capability`<br>`commercial_specs.insurance_capability` |

### Weight and dimensional data

| Required field | Columns |
| --- | --- |
| **Dry weight** | `dimensional_specs.dry_weight_kg`<br>`dimensional_specs.pump_only_weight_kg`<br>`dimensional_specs.driver_weight_kg`<br>`dimensional_specs.baseplate_weight_kg` |
| **Operating weight** | `dimensional_specs.operating_weight_kg` |
| **Shipping weight and crate dimensions** | `dimensional_specs.shipping_weight_kg`<br>`dimensional_specs.crate_length_mm`<br>`dimensional_specs.crate_width_mm`<br>`dimensional_specs.crate_height_mm`<br>`dimensional_specs.crate_volume_m3`<br>`dimensional_specs.number_of_packages` |
| **Footprint / baseplate dimensions** | `dimensional_specs.baseplate_length_mm`<br>`dimensional_specs.baseplate_width_mm`<br>`dimensional_specs.baseplate_height_mm`<br>`dimensional_specs.baseplate_type`<br>`dimensional_specs.footprint_area_m2`<br>`dimensional_specs.overall_length_mm`<br>`dimensional_specs.overall_width_mm`<br>`dimensional_specs.overall_height_mm`<br>`dimensional_specs.maintenance_access_envelope_mm` |
| **Centre of gravity and lifting points** | `dimensional_specs.cog_x_mm`<br>`dimensional_specs.cog_y_mm`<br>`dimensional_specs.cog_z_mm`<br>`dimensional_specs.cog_reference_datum`<br>`dimensional_specs.lifting_points_count`<br>`dimensional_specs.lifting_point_details`<br>`dimensional_specs.lifting_arrangement_standard`<br>`dimensional_specs.certified_lifting_set_included` |
| **Foundation loading requirements** | `dimensional_specs.static_load_kn`<br>`dimensional_specs.dynamic_load_kn`<br>`dimensional_specs.torque_reaction_knm`<br>`dimensional_specs.anchor_bolt_count`<br>`dimensional_specs.anchor_bolt_size`<br>`dimensional_specs.foundation_loading_notes`<br>`dimensional_specs.grouting_requirement`<br>`dimensional_specs.vibration_isolation_required` |
| **Maximum maintenance lift weight** | `dimensional_specs.max_maintenance_lift_weight_kg`<br>`dimensional_specs.max_maintenance_lift_item` |
| **Packaging type** | `dimensional_specs.packaging_type`<br>`dimensional_specs.packaging_standard`<br>`dimensional_specs.preservation_period_months` |
| **FPSO topside module space envelope** | `dimensional_specs.fpso_module_space_envelope`<br>`dimensional_specs.fpso_module_envelope_length_mm`<br>`dimensional_specs.fpso_module_envelope_width_mm`<br>`dimensional_specs.fpso_module_envelope_height_mm`<br>`dimensional_specs.deck_area_required_m2`<br>`dimensional_specs.module_integration_notes`<br>`dimensional_specs.motion_design_criteria` |

### Delivery data

| Required field | Columns |
| --- | --- |
| **Standard lead time** | `delivery_specs.standard_lead_time_weeks`<br>`delivery_specs.lead_time_basis`<br>`delivery_specs.engineering_lead_time_weeks`<br>`delivery_specs.manufacturing_lead_time_weeks` |
| **Expedited lead time and premium** | `delivery_specs.expedited_lead_time_weeks`<br>`delivery_specs.expedite_premium_pct`<br>`delivery_specs.expedite_premium_usd`<br>`delivery_specs.expedite_conditions` |
| **Manufacturing locations** | `delivery_specs.manufacturing_locations`<br>`delivery_specs.primary_manufacturing_country`<br>`delivery_specs.assembly_location`<br>`delivery_specs.testing_location`<br>`delivery_specs.workshop_capacity_notes`<br>`delivery_specs.current_backlog_weeks`<br>`vendors.manufacturing_countries` |
| **Logistics / shipping lead time** | `delivery_specs.logistics_lead_time_weeks`<br>`delivery_specs.shipping_mode`<br>`delivery_specs.port_of_loading`<br>`delivery_specs.freight_cost_estimate_usd`<br>`delivery_specs.oversize_cargo`<br>`delivery_specs.logistics_notes` |
| **Incoterms offered** | `delivery_specs.incoterms_offered`<br>`delivery_specs.preferred_incoterm` |
| **Documentation lead time** | `delivery_specs.documentation_lead_time_weeks`<br>`delivery_specs.final_documentation_weeks_after_delivery`<br>`delivery_specs.document_deliverables_list`<br>`delivery_specs.documentation_language`<br>`delivery_specs.as_built_documentation_included` |
| **FAT scheduling and duration** | `delivery_specs.fat_lead_time_weeks`<br>`delivery_specs.fat_duration_days`<br>`delivery_specs.fat_notice_period_weeks`<br>`delivery_specs.fat_location`<br>`delivery_specs.fat_witness_slots`<br>`delivery_specs.sat_supported`<br>`delivery_specs.fat_scheduling_notes` |
| **Historical on-time delivery %** | `delivery_specs.historical_on_time_delivery_pct`<br>`delivery_specs.otd_sample_size`<br>`delivery_specs.otd_measurement_period`<br>`delivery_specs.average_delay_weeks`<br>`delivery_specs.delivery_risk_notes`<br>`vendors.on_time_delivery_pct` |
| **Long-lead sub-component dependencies** | `delivery_specs.long_lead_components`<br>`delivery_specs.critical_subsupplier_dependencies`<br>`delivery_specs.single_source_components`<br>`delivery_specs.forging_casting_lead_time_weeks` |
| **Country of origin / export control** | `delivery_specs.country_of_origin`<br>`delivery_specs.export_control_classification`<br>`delivery_specs.export_licence_required`<br>`delivery_specs.export_licence_lead_time_weeks`<br>`delivery_specs.restricted_destinations`<br>`delivery_specs.us_content_pct`<br>`delivery_specs.export_control_notes` |

### Operational and track record data

| Required field | Columns |
| --- | --- |
| **Reference list** | `operational_specs.reference_list`<br>`operational_specs.reference_count`<br>`operational_specs.reference_contactable` |
| **Units supplied / installed** | `operational_specs.units_supplied`<br>`operational_specs.units_installed_operating`<br>`operational_specs.first_installation_year`<br>`operational_specs.cumulative_operating_hours`<br>`vendors.total_units_supplied` |
| **Reliability data** | `operational_specs.mtbf_hours`<br>`operational_specs.mttr_hours`<br>`operational_specs.availability_pct`<br>`operational_specs.failure_rate_per_year`<br>`operational_specs.common_failure_modes`<br>`operational_specs.reliability_data_source`<br>`operational_specs.seal_mtbf_hours`<br>`operational_specs.overhaul_interval_hours` |
| **FPSO / offshore experience** | `operational_specs.fpso_experience`<br>`operational_specs.fpso_units_supplied`<br>`operational_specs.fpso_project_references`<br>`operational_specs.offshore_experience_years`<br>`operational_specs.harsh_environment_experience`<br>`operational_specs.subsea_experience`<br>`vendors.fpso_offshore_experience` |
| **After-sales service network** | `operational_specs.service_network_countries`<br>`operational_specs.service_centers`<br>`operational_specs.nearest_service_center`<br>`operational_specs.response_time_hours`<br>`operational_specs.field_service_engineers_count`<br>`operational_specs.service_agreement_options`<br>`operational_specs.remote_monitoring_offered` |
| **Post-warranty spares availability** | `operational_specs.post_warranty_spares_years`<br>`operational_specs.spares_availability_commitment`<br>`operational_specs.spares_stock_locations`<br>`operational_specs.typical_spares_delivery_weeks`<br>`operational_specs.obsolescence_management_policy` |
| **Training and commissioning support** | `operational_specs.training_offered`<br>`operational_specs.training_scope`<br>`operational_specs.training_days_included`<br>`operational_specs.commissioning_support_included`<br>`operational_specs.commissioning_support_days`<br>`operational_specs.supervision_day_rate_usd`<br>`operational_specs.documentation_training_language` |
| **HSE performance and incident history** | `operational_specs.hse_trir`<br>`operational_specs.hse_ltifr`<br>`operational_specs.hse_fatalities_last_5y`<br>`operational_specs.hse_incident_history`<br>`operational_specs.hse_management_system`<br>`operational_specs.hse_audit_date` |
| **QA/QC certifications** | `operational_specs.qaqc_certifications`<br>`operational_specs.quality_certificate_expiry`<br>`operational_specs.itp_available`<br>`operational_specs.audit_history`<br>`operational_specs.ncr_history_notes` |
| **Vendor approval status** | `vendors.approval_status`<br>`vendors.approval_expiry`<br>`vendors.approved_by_user_id`<br>`operational_specs.vendor_approval_notes`<br>`operational_specs.approved_vendor_list_membership` |
| **Vendor tier / category** | `vendors.vendor_tier`<br>`vendors.vendor_category` |
| **Sanctions / geopolitical screening status** | `vendors.sanctions_status`<br>`vendors.sanctions_screened_at`<br>`vendors.sanctions_notes`<br>`vendors.geopolitical_risk_notes` |

### Administrative and data-quality data

| Required field | Columns |
| --- | --- |
| **Legal entity and registration details** | `administrative_specs.legal_entity_name`<br>`administrative_specs.legal_form`<br>`administrative_specs.registration_number`<br>`administrative_specs.registration_country`<br>`administrative_specs.registration_authority`<br>`administrative_specs.tax_identification_number`<br>`administrative_specs.vat_number`<br>`administrative_specs.lei_code`<br>`administrative_specs.registered_address`<br>`administrative_specs.incorporation_date`<br>`administrative_specs.ultimate_parent_company`<br>`administrative_specs.ownership_structure`<br>`administrative_specs.beneficial_ownership_disclosed` |
| **Authorized representative / agent** | `administrative_specs.authorized_representative_name`<br>`administrative_specs.authorized_representative_title`<br>`administrative_specs.authorized_representative_email`<br>`administrative_specs.authorized_representative_phone`<br>`administrative_specs.local_agent_name`<br>`administrative_specs.local_agent_country`<br>`administrative_specs.agency_agreement_reference`<br>`administrative_specs.agency_agreement_expiry`<br>`administrative_specs.power_of_attorney_on_file`<br>`vendor_contacts.contact_role`<br>`vendor_contacts.company_name`<br>`vendor_contacts.territory`<br>`vendor_contacts.agency_agreement_valid_until` |
| **ESG / sustainability disclosures** | `administrative_specs.esg_report_published`<br>`administrative_specs.esg_report_url`<br>`administrative_specs.esg_rating_provider`<br>`administrative_specs.esg_rating`<br>`administrative_specs.scope1_emissions_tco2e`<br>`administrative_specs.scope2_emissions_tco2e`<br>`administrative_specs.scope3_emissions_reported`<br>`administrative_specs.net_zero_target_year`<br>`administrative_specs.iso_14001_certified`<br>`administrative_specs.iso_50001_certified`<br>`administrative_specs.modern_slavery_statement`<br>`administrative_specs.anti_bribery_policy`<br>`administrative_specs.conflict_minerals_policy`<br>`administrative_specs.diversity_disclosures` |
| **Cybersecurity posture** | `administrative_specs.iso_27001_certified`<br>`administrative_specs.iec_62443_compliance`<br>`administrative_specs.soc2_report_available`<br>`administrative_specs.penetration_test_frequency`<br>`administrative_specs.security_incident_history`<br>`administrative_specs.supply_chain_security_program`<br>`administrative_specs.remote_access_policy`<br>`administrative_specs.cyber_insurance`<br>`administrative_specs.cybersecurity_questionnaire_completed` |
| **Data submission date and source** | `administrative_specs.data_submission_date`<br>`administrative_specs.submitted_by_name`<br>`administrative_specs.submitted_by_organisation`<br>`administrative_specs.submission_channel`<br>`administrative_specs.source_reference`<br>`administrative_specs.data_owner`<br>`sources.source_type`<br>`sources.source_url`<br>`sources.captured_at`<br>`sources.content_hash`<br>`field_provenance.source_id`<br>`field_provenance.evidence_quote`<br>`field_provenance.evidence_locator` |
| **Data confidence / verification level** | `vendors.confidence_level`<br>`vendors.verification_status`<br>`pump_models.confidence_level`<br>`pump_models.verification_status`<br>`technical_specs.confidence_level`<br>`technical_specs.verification_status`<br>`administrative_specs.verification_method`<br>`administrative_specs.verified_by_user_id`<br>`administrative_specs.verified_at`<br>`administrative_specs.completeness_pct`<br>`field_provenance.confidence_level`<br>`field_provenance.confidence_score`<br>`confidence_scores.score`<br>`data_quality_flags.flag_type` |

## 2. Table reference

Generated from `backend/app/models`. Units are carried in column names
(`_m3h`, `_m`, `_kw`, `_kg`, `_mm`, `_barg`, `_c`, `_usd`); values are stored in SI
with the original figure preserved in `source_units` and
`field_provenance.original_value`.

### `administrative_specs`

Legal entity, representation, ESG, cyber and data quality.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `vendor_id` | UUID | yes | FK to `vendors.id`. |
| `legal_entity_name` | VARCHAR(255) | yes |  |
| `legal_form` | VARCHAR(80) | yes | GmbH \| S.p.A. \| Ltd \| LLC \| JSC ... |
| `registration_number` | VARCHAR(80) | yes |  |
| `registration_country` | VARCHAR(2) | yes |  |
| `registration_authority` | VARCHAR(200) | yes |  |
| `tax_identification_number` | VARCHAR(80) | yes |  |
| `vat_number` | VARCHAR(80) | yes |  |
| `lei_code` | VARCHAR(20) | yes | ISO 17442 legal entity id |
| `registered_address` | TEXT | yes |  |
| `incorporation_date` | DATE | yes |  |
| `ultimate_parent_company` | VARCHAR(255) | yes |  |
| `ownership_structure` | JSONB | no |  |
| `beneficial_ownership_disclosed` | BOOLEAN | yes |  |
| `authorized_representative_name` | VARCHAR(255) | yes |  |
| `authorized_representative_title` | VARCHAR(160) | yes |  |
| `authorized_representative_email` | VARCHAR(320) | yes |  |
| `authorized_representative_phone` | VARCHAR(64) | yes |  |
| `local_agent_name` | VARCHAR(255) | yes |  |
| `local_agent_country` | VARCHAR(2) | yes |  |
| `agency_agreement_reference` | VARCHAR(160) | yes |  |
| `agency_agreement_expiry` | DATE | yes |  |
| `power_of_attorney_on_file` | BOOLEAN | yes |  |
| `esg_report_published` | BOOLEAN | yes |  |
| `esg_report_url` | VARCHAR(500) | yes |  |
| `esg_rating_provider` | VARCHAR(120) | yes |  |
| `esg_rating` | VARCHAR(40) | yes |  |
| `scope1_emissions_tco2e` | NUMERIC(18, 6) | yes |  |
| `scope2_emissions_tco2e` | NUMERIC(18, 6) | yes |  |
| `scope3_emissions_reported` | BOOLEAN | yes |  |
| `net_zero_target_year` | INTEGER | yes |  |
| `iso_14001_certified` | BOOLEAN | yes |  |
| `iso_50001_certified` | BOOLEAN | yes |  |
| `modern_slavery_statement` | BOOLEAN | yes |  |
| `anti_bribery_policy` | BOOLEAN | yes |  |
| `conflict_minerals_policy` | BOOLEAN | yes |  |
| `diversity_disclosures` | TEXT | yes |  |
| `iso_27001_certified` | BOOLEAN | yes |  |
| `iec_62443_compliance` | VARCHAR(80) | yes | Security level claimed for OT/control scope |
| `soc2_report_available` | BOOLEAN | yes |  |
| `penetration_test_frequency` | VARCHAR(80) | yes |  |
| `security_incident_history` | TEXT | yes |  |
| `supply_chain_security_program` | TEXT | yes |  |
| `remote_access_policy` | TEXT | yes |  |
| `cyber_insurance` | BOOLEAN | yes |  |
| `cybersecurity_questionnaire_completed` | BOOLEAN | yes |  |
| `submitted_by_name` | VARCHAR(255) | yes |  |
| `submitted_by_organisation` | VARCHAR(255) | yes |  |
| `submission_channel` | VARCHAR(80) | yes | portal \| email \| web crawl \| api \| interview |
| `source_reference` | VARCHAR(500) | yes |  |
| `data_owner` | VARCHAR(160) | yes |  |
| `next_review_due` | DATE | yes |  |
| `completeness_pct` | NUMERIC(5, 4) | yes |  |
| `verification_method` | VARCHAR(200) | yes | How the record was verified: document, call, site audit |
| `verified_by_user_id` | UUID | yes | FK to `users.id`. |
| `verified_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `retention_policy` | VARCHAR(160) | yes |  |
| `confidentiality_class` | VARCHAR(40) | yes | public \| internal \| confidential \| restricted |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `source_units` | JSONB | no | Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"} |
| `notes` | TEXT | yes |  |
| `extra` | JSONB | no | Fields not yet promoted to columns |
| `data_submission_date` | DATE | yes | Date the supplier or analyst submitted this data |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `version` | INTEGER | no |  |
| `is_current` | BOOLEAN | no |  |
| `superseded_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `schema_version` | VARCHAR | no |  |

### `ai_jobs`

Every AI or web-search call, with tokens, cost, latency and prompt version.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `job_type` | ai_job_type | no |  |
| `status` | ai_job_status | no |  |
| `provider` | VARCHAR(40) | no | openrouter \| parallel |
| `model` | VARCHAR(160) | yes |  |
| `prompt_name` | VARCHAR(120) | yes | Named template used, e.g. extract_technical_v3 |
| `prompt_version` | VARCHAR(24) | yes |  |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `document_id` | UUID | yes | FK to `documents.id`. |
| `import_batch_id` | UUID | yes | FK to `import_batches.id`. |
| `subject_type` | VARCHAR(60) | yes | vendor \| pump \| pump_model \| technical_spec \| ... |
| `subject_id` | UUID | yes |  |
| `request_payload` | JSONB | no |  |
| `response_payload` | JSONB | no |  |
| `raw_response_text` | TEXT | yes | Verbatim model output, kept for audit and re-parsing |
| `prompt_tokens` | INTEGER | yes |  |
| `completion_tokens` | INTEGER | yes |  |
| `cost_usd` | NUMERIC(12, 6) | yes |  |
| `latency_ms` | INTEGER | yes |  |
| `attempt` | INTEGER | no |  |
| `celery_task_id` | VARCHAR(120) | yes |  |
| `started_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `finished_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `error_message` | TEXT | yes |  |
| `triggered_by_user_id` | UUID | yes | FK to `users.id`. |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `ai_provider_configs`

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `label` | VARCHAR(120) | no |  |
| `provider` | VARCHAR(40) | no |  |
| `role` | VARCHAR(20) | no |  |
| `model` | VARCHAR(120) | yes |  |
| `encrypted_api_key` | TEXT | no |  |
| `key_hint` | VARCHAR(24) | yes |  |
| `base_url` | VARCHAR(255) | yes |  |
| `timeout_seconds` | INTEGER | yes |  |
| `is_active` | BOOLEAN | no |  |
| `last_checked_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `last_check_ok` | BOOLEAN | yes |  |
| `last_check_detail` | TEXT | yes |  |
| `created_by_user_id` | UUID | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |

### `ai_suggestions`

Field-level proposals awaiting approval on the AI review screen.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `entity_type` | VARCHAR(60) | no |  |
| `entity_id` | UUID | no |  |
| `field_name` | VARCHAR(120) | no |  |
| `suggestion_kind` | VARCHAR(40) | no | fill_missing \| normalize \| correct \| enrich \| flag_removal |
| `current_value` | TEXT | yes |  |
| `suggested_value` | TEXT | yes |  |
| `suggested_value_json` | JSONB | no |  |
| `rationale` | TEXT | yes |  |
| `evidence_quote` | TEXT | yes |  |
| `confidence_score` | NUMERIC(5, 4) | yes |  |
| `confidence_level` | confidence_level | no |  |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `extracted_entity_id` | UUID | yes | FK to `extracted_entities.id`. |
| `decision` | review_decision | no |  |
| `decided_by_user_id` | UUID | yes | FK to `users.id`. |
| `decided_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `applied_value` | TEXT | yes | What was actually written, if the reviewer edited the suggestion |
| `decision_notes` | TEXT | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `api_keys`

Machine credentials for API-first integrations. Only hashes are stored.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `name` | VARCHAR(160) | no |  |
| `prefix` | VARCHAR(16) | no |  |
| `hashed_key` | VARCHAR(255) | no |  |
| `scopes` | JSONB | no |  |
| `is_active` | BOOLEAN | no |  |
| `last_used_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `expires_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |

### `audit_logs`

Append-only audit trail. Highest-volume table; partition by month.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | BIGINT | no | Primary key. |
| `occurred_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `action` | audit_action | no |  |
| `entity_type` | VARCHAR(60) | yes |  |
| `entity_id` | UUID | yes |  |
| `entity_label` | VARCHAR(500) | yes | Human-readable subject, kept even if the row is later deleted |
| `user_id` | UUID | yes | FK to `users.id`. |
| `user_email` | VARCHAR(320) | yes |  |
| `actor_type` | VARCHAR(24) | no | user \| system \| worker \| api_key |
| `api_key_id` | UUID | yes | FK to `api_keys.id`. |
| `summary` | TEXT | yes |  |
| `changes` | JSONB | no | {"field": {"from": "...", "to": "..."}} - the diff that was applied |
| `context` | JSONB | no | Route, job id, batch id, reason |
| `request_id` | VARCHAR(64) | yes |  |
| `ip_address` | INET | yes |  |
| `user_agent` | VARCHAR(500) | yes |  |
| `http_method` | VARCHAR(10) | yes |  |
| `http_path` | VARCHAR(500) | yes |  |
| `status_code` | INTEGER | yes |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `commercial_specs`

Pricing, terms, warranty, escalation and life-cycle economics.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `base_price_amount` | NUMERIC(18, 2) | yes |  |
| `base_price_currency` | VARCHAR(3) | yes | ISO 4217 |
| `base_price_usd` | NUMERIC(18, 2) | yes | Converted at fx_rate_used for cross-vendor comparison |
| `fx_rate_used` | NUMERIC(18, 6) | yes |  |
| `fx_rate_date` | DATE | yes |  |
| `price_basis` | VARCHAR(200) | yes | Scope covered by the price: bare shaft, package, skid |
| `price_validity_days` | INTEGER | yes |  |
| `quotation_reference` | VARCHAR(160) | yes |  |
| `quotation_date` | DATE | yes |  |
| `incoterm` | incoterm | yes |  |
| `incoterm_named_place` | VARCHAR(160) | yes |  |
| `payment_terms` | TEXT | yes | e.g. 20% advance / 70% on delivery / 10% on FAC |
| `advance_payment_pct` | NUMERIC(18, 6) | yes |  |
| `payment_days_net` | INTEGER | yes |  |
| `letter_of_credit_required` | BOOLEAN | yes |  |
| `retention_pct` | NUMERIC(18, 6) | yes |  |
| `liquidated_damages_terms` | TEXT | yes |  |
| `liquidated_damages_cap_pct` | NUMERIC(18, 6) | yes |  |
| `warranty_months` | INTEGER | yes |  |
| `warranty_basis` | VARCHAR(120) | yes | from delivery \| from commissioning \| whichever is earlier |
| `warranty_scope` | TEXT | yes |  |
| `extended_warranty_available` | BOOLEAN | yes |  |
| `extended_warranty_cost_pct` | NUMERIC(18, 6) | yes |  |
| `spares_price_amount` | NUMERIC(18, 2) | yes |  |
| `spares_price_currency` | VARCHAR(3) | yes |  |
| `commissioning_spares_usd` | NUMERIC(18, 2) | yes |  |
| `two_year_spares_usd` | NUMERIC(18, 2) | yes |  |
| `capital_spares_usd` | NUMERIC(18, 2) | yes |  |
| `spares_price_list` | JSONB | no | Itemised spare part price list |
| `spares_discount_pct` | NUMERIC(18, 6) | yes |  |
| `price_escalation_formula` | TEXT | yes | Contractual escalation clause as written |
| `escalation_index_reference` | VARCHAR(160) | yes | e.g. CEPCI, Eurostat MIG, BLS PPI 3561 |
| `escalation_base_date` | DATE | yes |  |
| `escalation_annual_pct` | NUMERIC(18, 6) | yes |  |
| `discount_pct` | NUMERIC(18, 6) | yes |  |
| `volume_discount_schedule` | JSONB | no | e.g. {"5": 4.5, "10": 8.0} units to pct |
| `frame_agreement_reference` | VARCHAR(160) | yes |  |
| `historical_price_benchmark_usd` | NUMERIC(18, 2) | yes |  |
| `benchmark_source` | VARCHAR(200) | yes |  |
| `benchmark_date` | DATE | yes |  |
| `benchmark_variance_pct` | NUMERIC(18, 6) | yes | Offer vs benchmark; negative means cheaper than benchmark |
| `lifecycle_cost_usd` | NUMERIC(18, 2) | yes |  |
| `lifecycle_period_years` | INTEGER | yes |  |
| `energy_cost_per_year_usd` | NUMERIC(18, 2) | yes |  |
| `maintenance_cost_per_year_usd` | NUMERIC(18, 2) | yes |  |
| `lifecycle_assumptions` | JSONB | no |  |
| `taxes_included` | BOOLEAN | yes |  |
| `tax_details` | TEXT | yes |  |
| `import_duty_pct` | NUMERIC(18, 6) | yes |  |
| `customs_hs_code` | VARCHAR(24) | yes |  |
| `local_content_pct` | NUMERIC(18, 6) | yes |  |
| `local_content_scheme` | VARCHAR(160) | yes | e.g. NOGICD Nigeria, ICV Saudi Arabia, Petrobras local content |
| `local_content_certificate` | VARCHAR(160) | yes |  |
| `withholding_tax_pct` | NUMERIC(18, 6) | yes |  |
| `financial_standing_summary` | TEXT | yes |  |
| `bonding_capability` | TEXT | yes |  |
| `insurance_capability` | TEXT | yes |  |
| `parent_company_guarantee_available` | BOOLEAN | yes |  |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `source_units` | JSONB | no | Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"} |
| `notes` | TEXT | yes |  |
| `extra` | JSONB | no | Fields not yet promoted to columns |
| `data_submission_date` | DATE | yes | Date the supplier or analyst submitted this data |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `version` | INTEGER | no |  |
| `is_current` | BOOLEAN | no |  |
| `superseded_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `schema_version` | VARCHAR | no |  |

### `comparison_items`

One scored candidate inside a comparison.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `comparison_id` | UUID | no | FK to `comparisons.id`. |
| `pump_model_id` | UUID | yes | FK to `pump_models.id`. |
| `vendor_id` | UUID | yes | FK to `vendors.id`. |
| `position` | INTEGER | no |  |
| `technical_score` | NUMERIC(6, 3) | yes |  |
| `commercial_score` | NUMERIC(6, 3) | yes |  |
| `delivery_risk_score` | NUMERIC(6, 3) | yes |  |
| `data_confidence_score` | NUMERIC(6, 3) | yes |  |
| `overall_score` | NUMERIC(6, 3) | yes |  |
| `rank` | INTEGER | yes |  |
| `score_breakdown` | JSONB | no |  |
| `disqualified` | BOOLEAN | no |  |
| `disqualification_reason` | VARCHAR(500) | yes |  |
| `reviewer_notes` | TEXT | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `comparisons`

Saved side-by-side evaluations - the procurement deliverable.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | VARCHAR(255) | no |  |
| `description` | TEXT | yes |  |
| `requirement_profile_id` | UUID | yes | FK to `requirement_profiles.id`. |
| `comparison_kind` | VARCHAR(40) | no | pump_model \| vendor |
| `fields_shown` | JSONB | no |  |
| `snapshot` | JSONB | no | Frozen values as displayed, so a decision record stays reproducible |
| `recommendation` | TEXT | yes |  |
| `ai_narrative` | TEXT | yes |  |
| `status` | VARCHAR(24) | no | draft \| final \| archived |
| `is_shared_in_tenant` | BOOLEAN | no |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `finalised_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `confidence_scores`

Stored scorecards: technical, commercial, delivery, data confidence.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `entity_type` | VARCHAR(60) | no |  |
| `entity_id` | UUID | no |  |
| `scorecard_kind` | scorecard_kind | no |  |
| `score` | NUMERIC(6, 3) | no | 0.000 - 100.000 |
| `grade` | VARCHAR(4) | yes | A / B / C / D / E |
| `breakdown` | JSONB | no | Per-criterion contributions: {"npsh_margin": {"score": 80, "weight": 0.1}} |
| `weighting_profile` | JSONB | no |  |
| `requirement_profile_id` | UUID | yes | FK to `requirement_profiles.id`. NULL means scored against platform defaults |
| `fields_evaluated` | INTEGER | yes |  |
| `fields_missing` | INTEGER | yes |  |
| `computed_by_version` | VARCHAR(24) | yes |  |
| `computed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `is_stale` | BOOLEAN | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `crawl_schedules`

Scheduled crawl and periodic web-search targets.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | VARCHAR(255) | no |  |
| `target_type` | VARCHAR(40) | no | url \| sitemap \| vendor_site \| parallel_query |
| `target` | VARCHAR(2000) | no |  |
| `vendor_id` | UUID | yes | FK to `vendors.id`. |
| `cron_expression` | VARCHAR(120) | no |  |
| `max_depth` | INTEGER | no |  |
| `max_pages` | INTEGER | no |  |
| `include_patterns` | JSONB | no |  |
| `exclude_patterns` | JSONB | no |  |
| `auto_extract` | BOOLEAN | no |  |
| `is_active` | BOOLEAN | no |  |
| `last_run_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `last_run_status` | VARCHAR(40) | yes |  |
| `next_run_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `data_quality_flags`

Contradictions, out-of-range values, staleness, duplicate suspicion.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `entity_type` | VARCHAR(60) | no |  |
| `entity_id` | UUID | no |  |
| `field_name` | VARCHAR(120) | yes |  |
| `flag_type` | data_quality_flag_type | no |  |
| `severity` | flag_severity | no |  |
| `message` | TEXT | no |  |
| `detected_value` | VARCHAR(500) | yes |  |
| `expected_range` | VARCHAR(255) | yes |  |
| `conflicting_entity_type` | VARCHAR(60) | yes |  |
| `conflicting_entity_id` | UUID | yes |  |
| `conflicting_value` | VARCHAR(500) | yes |  |
| `detected_by` | VARCHAR(40) | no | validator \| ai \| user |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `suggested_fix` | TEXT | yes |  |
| `is_resolved` | BOOLEAN | no |  |
| `resolution` | VARCHAR(40) | yes | corrected \| accepted_as_is \| false_positive \| deferred |
| `resolved_by_user_id` | UUID | yes | FK to `users.id`. |
| `resolved_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `resolution_notes` | TEXT | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `delivery_specs`

Lead time, logistics, FAT and export control.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `standard_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `lead_time_basis` | VARCHAR(160) | yes | from PO \| from approved drawings \| from LOI |
| `expedited_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `expedite_premium_pct` | NUMERIC(18, 6) | yes |  |
| `expedite_premium_usd` | NUMERIC(18, 2) | yes |  |
| `expedite_conditions` | TEXT | yes |  |
| `engineering_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `manufacturing_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `manufacturing_locations` | VARCHAR(160)[] | yes | City, country per plant |
| `primary_manufacturing_country` | VARCHAR(2) | yes |  |
| `assembly_location` | VARCHAR(160) | yes |  |
| `testing_location` | VARCHAR(160) | yes |  |
| `workshop_capacity_notes` | TEXT | yes |  |
| `current_backlog_weeks` | NUMERIC(18, 6) | yes |  |
| `logistics_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `shipping_mode` | VARCHAR(80) | yes | sea \| air \| road \| multimodal |
| `port_of_loading` | VARCHAR(160) | yes |  |
| `incoterms_offered` | VARCHAR(8)[] | yes |  |
| `preferred_incoterm` | incoterm | yes |  |
| `freight_cost_estimate_usd` | NUMERIC(18, 2) | yes |  |
| `oversize_cargo` | BOOLEAN | yes |  |
| `logistics_notes` | TEXT | yes |  |
| `documentation_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `final_documentation_weeks_after_delivery` | NUMERIC(18, 6) | yes |  |
| `document_deliverables_list` | JSONB | no |  |
| `documentation_language` | VARCHAR(80) | yes |  |
| `as_built_documentation_included` | BOOLEAN | yes |  |
| `fat_lead_time_weeks` | NUMERIC(18, 6) | yes | Weeks from PO to FAT readiness |
| `fat_duration_days` | NUMERIC(18, 6) | yes |  |
| `fat_notice_period_weeks` | NUMERIC(18, 6) | yes |  |
| `fat_location` | VARCHAR(160) | yes |  |
| `fat_witness_slots` | INTEGER | yes |  |
| `sat_supported` | BOOLEAN | yes |  |
| `fat_scheduling_notes` | TEXT | yes |  |
| `historical_on_time_delivery_pct` | NUMERIC(5, 4) | yes |  |
| `otd_sample_size` | INTEGER | yes | Number of orders behind the OTD figure |
| `otd_measurement_period` | VARCHAR(120) | yes |  |
| `average_delay_weeks` | NUMERIC(18, 6) | yes |  |
| `delivery_risk_notes` | TEXT | yes |  |
| `long_lead_components` | JSONB | no | e.g. {"castings": {"weeks": 22, "source": "EU foundry"}} |
| `critical_subsupplier_dependencies` | VARCHAR(200)[] | yes |  |
| `single_source_components` | VARCHAR(200)[] | yes |  |
| `forging_casting_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `country_of_origin` | VARCHAR(2) | yes |  |
| `export_control_classification` | VARCHAR(80) | yes | e.g. EAR99, ECCN 2B999, EU dual-use item |
| `export_licence_required` | BOOLEAN | yes |  |
| `export_licence_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `restricted_destinations` | VARCHAR(2)[] | yes |  |
| `us_content_pct` | NUMERIC(18, 6) | yes |  |
| `export_control_notes` | TEXT | yes |  |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `source_units` | JSONB | no | Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"} |
| `notes` | TEXT | yes |  |
| `extra` | JSONB | no | Fields not yet promoted to columns |
| `data_submission_date` | DATE | yes | Date the supplier or analyst submitted this data |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `version` | INTEGER | no |  |
| `is_current` | BOOLEAN | no |  |
| `superseded_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `schema_version` | VARCHAR | no |  |

### `dimensional_specs`

Weights, envelope, lifting and foundation loading.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `dry_weight_kg` | NUMERIC(18, 6) | yes |  |
| `operating_weight_kg` | NUMERIC(18, 6) | yes |  |
| `shipping_weight_kg` | NUMERIC(18, 6) | yes |  |
| `pump_only_weight_kg` | NUMERIC(18, 6) | yes |  |
| `driver_weight_kg` | NUMERIC(18, 6) | yes |  |
| `baseplate_weight_kg` | NUMERIC(18, 6) | yes |  |
| `max_maintenance_lift_weight_kg` | NUMERIC(18, 6) | yes | Heaviest single item to be lifted during maintenance |
| `max_maintenance_lift_item` | VARCHAR(160) | yes |  |
| `crate_length_mm` | NUMERIC(18, 6) | yes |  |
| `crate_width_mm` | NUMERIC(18, 6) | yes |  |
| `crate_height_mm` | NUMERIC(18, 6) | yes |  |
| `crate_volume_m3` | NUMERIC(18, 6) | yes |  |
| `number_of_packages` | INTEGER | yes |  |
| `packaging_type` | VARCHAR(160) | yes | seaworthy wooden case \| vacuum barrier \| container \| skid |
| `packaging_standard` | VARCHAR(120) | yes | e.g. ISPM 15, MIL-STD-2073 |
| `preservation_period_months` | INTEGER | yes |  |
| `baseplate_length_mm` | NUMERIC(18, 6) | yes |  |
| `baseplate_width_mm` | NUMERIC(18, 6) | yes |  |
| `baseplate_height_mm` | NUMERIC(18, 6) | yes |  |
| `baseplate_type` | VARCHAR(120) | yes | API 610 baseplate \| skid \| fabricated \| grouted |
| `footprint_area_m2` | NUMERIC(18, 6) | yes |  |
| `overall_length_mm` | NUMERIC(18, 6) | yes |  |
| `overall_width_mm` | NUMERIC(18, 6) | yes |  |
| `overall_height_mm` | NUMERIC(18, 6) | yes |  |
| `maintenance_access_envelope_mm` | JSONB | no | Clearances needed per side for pull-out |
| `cog_x_mm` | NUMERIC(18, 6) | yes |  |
| `cog_y_mm` | NUMERIC(18, 6) | yes |  |
| `cog_z_mm` | NUMERIC(18, 6) | yes |  |
| `cog_reference_datum` | VARCHAR(160) | yes |  |
| `lifting_points_count` | INTEGER | yes |  |
| `lifting_point_details` | JSONB | no |  |
| `lifting_arrangement_standard` | VARCHAR(120) | yes | e.g. DNV 2.7-3, EN 13155 |
| `certified_lifting_set_included` | BOOLEAN | yes |  |
| `static_load_kn` | NUMERIC(18, 6) | yes |  |
| `dynamic_load_kn` | NUMERIC(18, 6) | yes |  |
| `torque_reaction_knm` | NUMERIC(18, 6) | yes |  |
| `anchor_bolt_count` | INTEGER | yes |  |
| `anchor_bolt_size` | VARCHAR(40) | yes |  |
| `foundation_loading_notes` | TEXT | yes |  |
| `grouting_requirement` | VARCHAR(160) | yes |  |
| `vibration_isolation_required` | BOOLEAN | yes |  |
| `fpso_module_space_envelope` | TEXT | yes | Declared L x W x H envelope inside the topside module |
| `fpso_module_envelope_length_mm` | NUMERIC(18, 6) | yes |  |
| `fpso_module_envelope_width_mm` | NUMERIC(18, 6) | yes |  |
| `fpso_module_envelope_height_mm` | NUMERIC(18, 6) | yes |  |
| `deck_area_required_m2` | NUMERIC(18, 6) | yes |  |
| `module_integration_notes` | TEXT | yes |  |
| `motion_design_criteria` | VARCHAR(200) | yes | Vessel motions / accelerations the unit is designed for |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `source_units` | JSONB | no | Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"} |
| `notes` | TEXT | yes |  |
| `extra` | JSONB | no | Fields not yet promoted to columns |
| `data_submission_date` | DATE | yes | Date the supplier or analyst submitted this data |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `version` | INTEGER | no |  |
| `is_current` | BOOLEAN | no |  |
| `superseded_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `schema_version` | VARCHAR | no |  |

### `documents`

Binary artefacts in object storage, with checksums.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `vendor_id` | UUID | yes | FK to `vendors.id`. |
| `pump_id` | UUID | yes | FK to `pumps.id`. |
| `pump_model_id` | UUID | yes | FK to `pump_models.id`. |
| `document_kind` | document_kind | no |  |
| `filename` | VARCHAR(500) | no |  |
| `storage_key` | VARCHAR(1000) | no | S3 object key (or local path in dev) |
| `storage_bucket` | VARCHAR(160) | yes |  |
| `mime_type` | VARCHAR(160) | yes |  |
| `size_bytes` | BIGINT | yes |  |
| `checksum_sha256` | VARCHAR(64) | yes |  |
| `page_count` | INTEGER | yes |  |
| `extracted_text` | TEXT | yes |  |
| `ocr_applied` | BOOLEAN | no |  |
| `is_confidential` | BOOLEAN | no |  |
| `document_date` | TIMESTAMP WITH TIME ZONE | yes |  |
| `revision` | VARCHAR(40) | yes |  |
| `uploaded_by_user_id` | UUID | yes | FK to `users.id`. |
| `doc_metadata` | JSONB | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `duplicate_candidates`

Suspected duplicate pairs, with the signals that flagged them.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `entity_type` | VARCHAR(60) | no |  |
| `entity_id_a` | UUID | no |  |
| `entity_id_b` | UUID | no |  |
| `similarity_score` | NUMERIC(5, 4) | no |  |
| `match_signals` | JSONB | no | {"normalized_name": 1.0, "duty_point": 0.97, "trigram": 0.88} |
| `detection_method` | VARCHAR(40) | no | deterministic \| ai \| manual |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `status` | VARCHAR(40) | no | open \| merged \| distinct \| deferred |
| `merged_into_id` | UUID | yes |  |
| `reviewed_by_user_id` | UUID | yes | FK to `users.id`. |
| `reviewed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `notes` | TEXT | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `extracted_entities`

Candidate records from the model, awaiting human review.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `entity_type` | VARCHAR(60) | no | vendor \| pump \| pump_model \| technical_spec \| commercial_spec \| ... |
| `payload` | JSONB | no | Normalised candidate record |
| `raw_payload` | JSONB | no | Pre-normalisation model output |
| `field_confidences` | JSONB | no | {"rated_head_m": 0.82, ...} |
| `evidence_spans` | JSONB | no | {"rated_head_m": {"quote": "...", "char_start": 1420}} - traceability |
| `overall_confidence` | NUMERIC(5, 4) | yes |  |
| `confidence_level` | confidence_level | no |  |
| `review_decision` | review_decision | no |  |
| `reviewed_by_user_id` | UUID | yes | FK to `users.id`. |
| `reviewed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `review_notes` | TEXT | yes |  |
| `reviewer_edits` | JSONB | no | Field-level corrections a human made |
| `target_type` | VARCHAR(60) | yes | Set on promotion: which table received the data |
| `target_id` | UUID | yes |  |
| `promoted_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `field_provenance`

Per-field lineage. The answer to 'where did this number come from?'.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `entity_type` | VARCHAR(60) | no |  |
| `entity_id` | UUID | no |  |
| `field_name` | VARCHAR(120) | no |  |
| `value_text` | TEXT | yes | Written value rendered as text, for diffing and audit |
| `previous_value_text` | TEXT | yes |  |
| `value_origin` | value_origin | no |  |
| `confidence_level` | confidence_level | no |  |
| `confidence_score` | NUMERIC(5, 4) | yes |  |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `document_id` | UUID | yes | FK to `documents.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `extracted_entity_id` | UUID | yes | FK to `extracted_entities.id`. |
| `model_used` | VARCHAR(160) | yes |  |
| `evidence_quote` | TEXT | yes | Verbatim snippet from the source that supports the value |
| `evidence_locator` | VARCHAR(255) | yes | Page number, cell reference, char offset or CSS selector |
| `original_value` | VARCHAR(500) | yes | Value as printed in the source, before unit normalisation |
| `original_unit` | VARCHAR(40) | yes |  |
| `normalization_note` | TEXT | yes |  |
| `changed_by_user_id` | UUID | yes | FK to `users.id`. |
| `is_current` | BOOLEAN | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `import_batches`

One ingestion run. Drives the import queue screen.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | VARCHAR(255) | no |  |
| `import_mode` | VARCHAR(40) | no | file_upload \| url_list \| scheduled_crawl \| api_sync \| web_search \| manual_form |
| `source_type` | source_type | no |  |
| `status` | ingestion_status | no |  |
| `total_items` | INTEGER | no |  |
| `processed_items` | INTEGER | no |  |
| `failed_items` | INTEGER | no |  |
| `promoted_items` | INTEGER | no |  |
| `needs_review_items` | INTEGER | no |  |
| `config` | JSONB | no | Crawl scope, mapping profile, AI options |
| `auto_promote` | BOOLEAN | no | Promote high-confidence extractions without human review |
| `started_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `finished_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `error_summary` | TEXT | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `operational_specs`

Track record, references, service network, HSE and QA/QC.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `reference_list` | JSONB | no | [{"client":"...","project":"...","year":2021,"units":4,"country":"BR"}] |
| `reference_count` | INTEGER | yes |  |
| `units_supplied` | INTEGER | yes |  |
| `units_installed_operating` | INTEGER | yes |  |
| `first_installation_year` | INTEGER | yes |  |
| `cumulative_operating_hours` | INTEGER | yes |  |
| `reference_contactable` | BOOLEAN | yes |  |
| `mtbf_hours` | INTEGER | yes |  |
| `mttr_hours` | NUMERIC(18, 6) | yes |  |
| `availability_pct` | NUMERIC(5, 4) | yes |  |
| `failure_rate_per_year` | NUMERIC(18, 6) | yes |  |
| `common_failure_modes` | TEXT | yes |  |
| `reliability_data_source` | VARCHAR(200) | yes | e.g. OREDA, client CMMS, vendor claim |
| `seal_mtbf_hours` | INTEGER | yes |  |
| `overhaul_interval_hours` | INTEGER | yes |  |
| `fpso_experience` | BOOLEAN | yes |  |
| `fpso_units_supplied` | INTEGER | yes |  |
| `fpso_project_references` | JSONB | no |  |
| `offshore_experience_years` | INTEGER | yes |  |
| `harsh_environment_experience` | VARCHAR(200) | yes | North Sea, Arctic, deepwater Brazil, West Africa ... |
| `subsea_experience` | BOOLEAN | yes |  |
| `service_network_countries` | VARCHAR(2)[] | yes |  |
| `service_centers` | JSONB | no |  |
| `nearest_service_center` | VARCHAR(200) | yes |  |
| `response_time_hours` | NUMERIC(18, 6) | yes |  |
| `field_service_engineers_count` | INTEGER | yes |  |
| `service_agreement_options` | TEXT | yes |  |
| `remote_monitoring_offered` | BOOLEAN | yes |  |
| `post_warranty_spares_years` | INTEGER | yes |  |
| `spares_availability_commitment` | TEXT | yes |  |
| `spares_stock_locations` | VARCHAR(160)[] | yes |  |
| `typical_spares_delivery_weeks` | NUMERIC(18, 6) | yes |  |
| `obsolescence_management_policy` | TEXT | yes |  |
| `training_offered` | BOOLEAN | yes |  |
| `training_scope` | TEXT | yes |  |
| `training_days_included` | NUMERIC(18, 6) | yes |  |
| `commissioning_support_included` | BOOLEAN | yes |  |
| `commissioning_support_days` | NUMERIC(18, 6) | yes |  |
| `supervision_day_rate_usd` | NUMERIC(18, 2) | yes |  |
| `documentation_training_language` | VARCHAR(80) | yes |  |
| `hse_trir` | NUMERIC(18, 6) | yes | Total recordable incident rate |
| `hse_ltifr` | NUMERIC(18, 6) | yes | Lost time injury frequency rate |
| `hse_fatalities_last_5y` | INTEGER | yes |  |
| `hse_incident_history` | TEXT | yes |  |
| `hse_management_system` | VARCHAR(120) | yes | e.g. ISO 45001 certified |
| `hse_audit_date` | DATE | yes |  |
| `qaqc_certifications` | VARCHAR(120)[] | yes | ISO 9001, ISO 14001, API Q1, ASME U stamp ... |
| `quality_certificate_expiry` | DATE | yes |  |
| `itp_available` | BOOLEAN | yes | Inspection and test plan can be supplied |
| `audit_history` | JSONB | no |  |
| `ncr_history_notes` | TEXT | yes |  |
| `vendor_approval_notes` | TEXT | yes |  |
| `approved_vendor_list_membership` | VARCHAR(160)[] | yes | Operator AVLs the vendor sits on |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `source_units` | JSONB | no | Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"} |
| `notes` | TEXT | yes |  |
| `extra` | JSONB | no | Fields not yet promoted to columns |
| `data_submission_date` | DATE | yes | Date the supplier or analyst submitted this data |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `version` | INTEGER | no |  |
| `is_current` | BOOLEAN | no |  |
| `superseded_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `schema_version` | VARCHAR | no |  |

### `pump_models`

Orderable configurations. Every spec table hangs off this row.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `pump_id` | UUID | no | FK to `pumps.id`. |
| `model_code` | VARCHAR(160) | no |  |
| `size_designation` | VARCHAR(120) | yes | Suction x discharge x nominal impeller, e.g. 4x6x11 |
| `frame_size` | VARCHAR(80) | yes |  |
| `stages` | INTEGER | yes |  |
| `orientation` | VARCHAR(32) | yes | horizontal \| vertical \| inline |
| `generation` | VARCHAR(64) | yes |  |
| `tag_number` | VARCHAR(80) | yes | Client tag when the record came from a project datasheet |
| `project_reference` | VARCHAR(255) | yes |  |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `data_completeness_pct` | FLOAT | yes | Share of required intelligence fields populated; recomputed by worker |
| `primary_source_id` | UUID | yes | FK to `sources.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `last_reviewed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `is_shared_master` | BOOLEAN | no |  |
| `merged_into_pump_model_id` | UUID | yes | FK to `pump_models.id`. |
| `extra` | JSONB | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `pumps`

Vendor product lines, e.g. a named API 610 family.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `vendor_id` | UUID | no | FK to `vendors.id`. |
| `name` | VARCHAR(255) | no |  |
| `normalized_name` | VARCHAR(255) | no |  |
| `product_family` | VARCHAR(160) | yes |  |
| `pump_type` | pump_type | no |  |
| `pump_type_raw` | VARCHAR(255) | yes | Original uncontrolled string as captured from the source |
| `applicable_standard` | applicable_standard | no |  |
| `additional_standards` | VARCHAR(64)[] | yes |  |
| `standard_edition` | VARCHAR(64) | yes | e.g. API 610 12th Edition / ISO 13709:2009 |
| `service_application` | VARCHAR(255) | yes | e.g. crude export, produced water injection, firewater |
| `handled_fluids` | VARCHAR(120)[] | yes |  |
| `description` | TEXT | yes |  |
| `ai_summary` | TEXT | yes |  |
| `is_discontinued` | BOOLEAN | no |  |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `primary_source_id` | UUID | yes | FK to `sources.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `is_shared_master` | BOOLEAN | no |  |
| `merged_into_pump_id` | UUID | yes | FK to `pumps.id`. |
| `extra` | JSONB | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `record_versions`

Full-row snapshots for change tracking and rollback.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `entity_type` | VARCHAR(60) | no |  |
| `entity_id` | UUID | no |  |
| `version` | INTEGER | no |  |
| `operation` | VARCHAR(16) | no | insert \| update \| delete \| merge |
| `snapshot` | JSONB | no |  |
| `diff` | JSONB | no |  |
| `changed_by_user_id` | UUID | yes | FK to `users.id`. |
| `change_reason` | VARCHAR(500) | yes |  |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `schema_version` | VARCHAR(24) | yes |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `id` | UUID | no | Primary key. |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `requirement_profiles`

The buyer's duty point and acceptance criteria.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | VARCHAR(255) | no |  |
| `description` | TEXT | yes |  |
| `project_name` | VARCHAR(255) | yes |  |
| `tag_number` | VARCHAR(80) | yes |  |
| `required_capacity_m3h` | NUMERIC(18, 6) | yes |  |
| `required_head_m` | NUMERIC(18, 6) | yes |  |
| `max_npshr_m` | NUMERIC(18, 6) | yes |  |
| `min_efficiency_pct` | NUMERIC(18, 6) | yes |  |
| `fluid` | VARCHAR(160) | yes |  |
| `fluid_temperature_c` | NUMERIC(18, 6) | yes |  |
| `fluid_specific_gravity` | NUMERIC(18, 6) | yes |  |
| `required_standard` | VARCHAR(64) | yes |  |
| `required_pump_types` | JSONB | no |  |
| `required_area_classification` | VARCHAR(40) | yes |  |
| `required_certifications` | JSONB | no |  |
| `required_material_class` | VARCHAR(24) | yes |  |
| `nace_required` | BOOLEAN | yes |  |
| `max_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `max_budget_usd` | NUMERIC(18, 2) | yes |  |
| `max_dry_weight_kg` | NUMERIC(18, 6) | yes |  |
| `max_footprint_m2` | NUMERIC(18, 6) | yes |  |
| `excluded_countries` | JSONB | no |  |
| `local_content_min_pct` | NUMERIC(18, 6) | yes |  |
| `weight_technical` | NUMERIC(18, 6) | no |  |
| `weight_commercial` | NUMERIC(18, 6) | no |  |
| `weight_delivery` | NUMERIC(18, 6) | no |  |
| `weight_data_confidence` | NUMERIC(18, 6) | no |  |
| `criteria_overrides` | JSONB | no |  |
| `is_active` | BOOLEAN | no |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `roles`

The six product roles, with their resource/action matrix.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | user_role_name | no |  |
| `display_name` | VARCHAR(120) | no |  |
| `description` | VARCHAR(500) | yes |  |
| `is_platform_role` | BOOLEAN | no | Role operates across all tenants |
| `permissions` | JSONB | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |

### `saved_searches`

Stored queries, optionally alerting on new matches.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | VARCHAR(255) | no |  |
| `query_text` | VARCHAR(1000) | yes |  |
| `filters` | JSONB | no |  |
| `sort_by` | VARCHAR(80) | yes |  |
| `is_shared_in_tenant` | BOOLEAN | no |  |
| `alert_enabled` | BOOLEAN | no |  |
| `alert_frequency` | VARCHAR(24) | yes | daily \| weekly \| on_change |
| `last_alert_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `last_result_count` | INTEGER | yes |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `search_index`

Denormalised one-row-per-model index backing full-text search.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `pump_id` | UUID | no | FK to `pumps.id`. |
| `vendor_id` | UUID | no | FK to `vendors.id`. |
| `label` | VARCHAR(500) | no | Vendor + pump + model, as shown in result rows |
| `vendor_name` | VARCHAR(255) | no |  |
| `pump_name` | VARCHAR(255) | no |  |
| `model_code` | VARCHAR(160) | no |  |
| `summary` | TEXT | yes |  |
| `search_vector` | TSVECTOR | yes |  |
| `searchable_text` | TEXT | yes | Concatenated haystack the tsvector is generated from |
| `vendor_country` | VARCHAR(2) | yes |  |
| `manufacturing_countries` | VARCHAR(2)[] | yes |  |
| `country_of_origin` | VARCHAR(2) | yes |  |
| `pump_type` | pump_type | yes |  |
| `applicable_standard` | applicable_standard | yes |  |
| `service_application` | VARCHAR(255) | yes |  |
| `area_classification` | VARCHAR(40) | yes |  |
| `seal_system_type` | VARCHAR(60) | yes |  |
| `driver_type` | VARCHAR(60) | yes |  |
| `material_class` | VARCHAR(24) | yes |  |
| `certifications` | VARCHAR(120)[] | yes |  |
| `incoterms_offered` | VARCHAR(8)[] | yes |  |
| `vendor_approval_status` | vendor_approval_status | yes |  |
| `vendor_tier` | VARCHAR(40) | yes |  |
| `fpso_experience` | BOOLEAN | yes |  |
| `nace_compliant` | BOOLEAN | yes |  |
| `rated_capacity_m3h` | NUMERIC(18, 6) | yes |  |
| `rated_head_m` | NUMERIC(18, 6) | yes |  |
| `npsh_required_m` | NUMERIC(18, 6) | yes |  |
| `hydraulic_efficiency_pct` | NUMERIC(18, 6) | yes |  |
| `rated_speed_rpm` | INTEGER | yes |  |
| `rated_power_kw` | NUMERIC(18, 6) | yes |  |
| `fluid_temperature_max_c` | NUMERIC(18, 6) | yes |  |
| `casing_design_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `base_price_usd` | NUMERIC(18, 2) | yes |  |
| `standard_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `expedited_lead_time_weeks` | NUMERIC(18, 6) | yes |  |
| `dry_weight_kg` | NUMERIC(18, 6) | yes |  |
| `operating_weight_kg` | NUMERIC(18, 6) | yes |  |
| `footprint_area_m2` | NUMERIC(18, 6) | yes |  |
| `on_time_delivery_pct` | NUMERIC(5, 4) | yes |  |
| `units_installed` | INTEGER | yes |  |
| `mtbf_hours` | INTEGER | yes |  |
| `confidence_level` | confidence_level | yes |  |
| `verification_status` | verification_status | yes |  |
| `data_completeness_pct` | NUMERIC(5, 4) | yes |  |
| `data_confidence_score` | NUMERIC(6, 3) | yes |  |
| `open_flag_count` | INTEGER | no |  |
| `is_shared_master` | BOOLEAN | no |  |
| `last_source_captured_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `indexed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `index_version` | VARCHAR(24) | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `sources`

Captured evidence: raw content, parsed text, capture date, confidence.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `source_type` | source_type | no |  |
| `status` | ingestion_status | no |  |
| `title` | VARCHAR(500) | yes |  |
| `source_url` | VARCHAR(2000) | yes |  |
| `canonical_url` | VARCHAR(2000) | yes |  |
| `publisher` | VARCHAR(255) | yes |  |
| `author` | VARCHAR(255) | yes |  |
| `language` | VARCHAR(8) | yes |  |
| `published_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `captured_at` | TIMESTAMP WITH TIME ZONE | no | When PumpAtlas fetched the source |
| `http_status` | INTEGER | yes |  |
| `content_type` | VARCHAR(160) | yes |  |
| `content_hash` | VARCHAR(64) | yes | SHA-256 of raw bytes; drives re-crawl dedupe |
| `raw_content` | TEXT | yes | Raw HTML / JSON payload as captured; large binaries live in documents |
| `parsed_text` | TEXT | yes | Plain text used for extraction |
| `parsed_text_chars` | INTEGER | yes |  |
| `source_metadata` | JSONB | no | Headers, robots directives, crawl context |
| `confidence_level` | confidence_level | no |  |
| `reliability_score` | NUMERIC(5, 4) | yes | 0-1 trust in the publisher; OEM site > distributor > forum |
| `is_authoritative` | BOOLEAN | no | True for OEM/official documents |
| `parallel_search_id` | VARCHAR(120) | yes | Parallel AI run that surfaced this result |
| `parallel_result_rank` | INTEGER | yes |  |
| `import_batch_id` | UUID | yes | FK to `import_batches.id`. |
| `submitted_by_user_id` | UUID | yes | FK to `users.id`. |
| `vendor_hint` | VARCHAR(255) | yes | Vendor the submitter believes this source is about |
| `error_message` | TEXT | yes |  |
| `retry_count` | INTEGER | no |  |
| `processed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `tagged_records`

Tag assignment join table.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `tag_id` | UUID | no | Primary key. FK to `tags.id`. |
| `entity_type` | VARCHAR(60) | no | Primary key. |
| `entity_id` | UUID | no | Primary key. |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `tagged_by_user_id` | UUID | yes | FK to `users.id`. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |

### `tags`

Analyst-managed labels: watchlists, project codes, risk markers.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `slug` | VARCHAR(80) | no |  |
| `name` | VARCHAR(120) | no |  |
| `description` | VARCHAR(500) | yes |  |
| `color` | VARCHAR(9) | yes | Hex, for dashboard chips |
| `category` | VARCHAR(60) | yes | watchlist \| project \| risk \| commodity \| custom |
| `is_system` | BOOLEAN | no |  |
| `usage_count` | INTEGER | no |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |

### `technical_specs`

Hydraulic, mechanical, material, certification and testing data.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `standard_compliance_notes` | TEXT | yes |  |
| `api_610_type_code` | VARCHAR(16) | yes | OH2 / BB3 / VS4 ... as declared on the datasheet |
| `deviations_to_standard` | TEXT | yes |  |
| `rated_capacity_m3h` | NUMERIC(18, 6) | yes |  |
| `min_capacity_m3h` | NUMERIC(18, 6) | yes |  |
| `max_capacity_m3h` | NUMERIC(18, 6) | yes |  |
| `min_continuous_stable_flow_m3h` | NUMERIC(18, 6) | yes |  |
| `bep_capacity_m3h` | NUMERIC(18, 6) | yes |  |
| `rated_head_m` | NUMERIC(18, 6) | yes |  |
| `max_head_m` | NUMERIC(18, 6) | yes |  |
| `shutoff_head_m` | NUMERIC(18, 6) | yes |  |
| `differential_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `npsh_required_m` | NUMERIC(18, 6) | yes |  |
| `npsh_available_m` | NUMERIC(18, 6) | yes |  |
| `npsh_margin_m` | NUMERIC(18, 6) | yes |  |
| `hydraulic_efficiency_pct` | NUMERIC(18, 6) | yes |  |
| `bep_efficiency_pct` | NUMERIC(18, 6) | yes |  |
| `rated_power_kw` | NUMERIC(18, 6) | yes |  |
| `max_power_kw` | NUMERIC(18, 6) | yes |  |
| `specific_speed` | NUMERIC(18, 6) | yes |  |
| `suction_specific_speed` | NUMERIC(18, 6) | yes |  |
| `impeller_type` | VARCHAR(80) | yes | closed \| semi-open \| open \| vortex \| double-suction |
| `impeller_diameter_mm` | NUMERIC(18, 6) | yes |  |
| `number_of_vanes` | INTEGER | yes |  |
| `suction_size_mm` | NUMERIC(18, 6) | yes |  |
| `discharge_size_mm` | NUMERIC(18, 6) | yes |  |
| `flange_rating` | VARCHAR(40) | yes | e.g. ASME 300# RF, API 6A 5000 psi |
| `flange_facing` | VARCHAR(40) | yes |  |
| `rated_speed_rpm` | INTEGER | yes |  |
| `min_speed_rpm` | INTEGER | yes |  |
| `max_speed_rpm` | INTEGER | yes |  |
| `is_variable_speed` | BOOLEAN | yes |  |
| `driver_type` | driver_type | yes |  |
| `driver_type_raw` | VARCHAR(160) | yes |  |
| `driver_rated_power_kw` | NUMERIC(18, 6) | yes |  |
| `driver_manufacturer` | VARCHAR(160) | yes |  |
| `driver_model` | VARCHAR(160) | yes |  |
| `driver_voltage_v` | INTEGER | yes |  |
| `driver_frequency_hz` | INTEGER | yes |  |
| `driver_service_factor` | NUMERIC(18, 6) | yes |  |
| `driver_enclosure` | VARCHAR(40) | yes | e.g. TEFC, WPII, Ex d IIB T4 |
| `coupling_type` | VARCHAR(120) | yes |  |
| `gearbox_required` | BOOLEAN | yes |  |
| `material_class` | VARCHAR(24) | yes | API 610 Table H.1 class, e.g. S-6, C-6, A-8, D-1 |
| `casing_material` | VARCHAR(160) | yes |  |
| `impeller_material` | VARCHAR(160) | yes |  |
| `shaft_material` | VARCHAR(160) | yes |  |
| `wear_parts_material` | VARCHAR(160) | yes |  |
| `shaft_sleeve_material` | VARCHAR(160) | yes |  |
| `gasket_material` | VARCHAR(160) | yes |  |
| `fastener_material` | VARCHAR(160) | yes |  |
| `nace_mr0175_compliant` | BOOLEAN | yes | Sour service compliance (NACE MR0175 / ISO 15156) |
| `corrosion_allowance_mm` | NUMERIC(18, 6) | yes |  |
| `material_certification` | VARCHAR(120) | yes | e.g. EN 10204 3.1 / 3.2 |
| `seal_system_type` | seal_system_type | yes |  |
| `seal_system_type_raw` | VARCHAR(160) | yes |  |
| `seal_api_682_category` | VARCHAR(24) | yes | Category 1 / 2 / 3 |
| `seal_arrangement` | VARCHAR(80) | yes | single \| dual pressurised \| dual unpressurised |
| `seal_piping_plan` | VARCHAR(80) | yes | API 682 flush plan, e.g. Plan 11 + Plan 52 |
| `seal_manufacturer` | VARCHAR(160) | yes |  |
| `seal_model` | VARCHAR(160) | yes |  |
| `seal_face_materials` | VARCHAR(200) | yes |  |
| `seal_elastomer` | VARCHAR(120) | yes |  |
| `barrier_buffer_fluid` | VARCHAR(160) | yes |  |
| `seal_support_system_scope` | TEXT | yes |  |
| `radial_bearing_type` | VARCHAR(120) | yes |  |
| `thrust_bearing_type` | VARCHAR(120) | yes |  |
| `bearing_arrangement` | VARCHAR(120) | yes |  |
| `bearing_manufacturer` | VARCHAR(160) | yes |  |
| `bearing_life_hours` | INTEGER | yes |  |
| `lubrication_type` | VARCHAR(80) | yes | ring oil \| flood \| pressurised \| grease \| oil mist |
| `lubricant_grade` | VARCHAR(80) | yes |  |
| `lube_oil_system_scope` | TEXT | yes |  |
| `bearing_isolators` | VARCHAR(120) | yes |  |
| `bearing_temperature_monitoring` | BOOLEAN | yes |  |
| `area_classification` | area_classification | yes |  |
| `area_classification_raw` | VARCHAR(160) | yes |  |
| `gas_group` | VARCHAR(24) | yes | IIA / IIB / IIC |
| `temperature_class` | VARCHAR(16) | yes | T1 - T6 |
| `equipment_protection_level` | VARCHAR(24) | yes |  |
| `ingress_protection` | VARCHAR(16) | yes | e.g. IP66 |
| `atex_certified` | BOOLEAN | yes |  |
| `iecex_certified` | BOOLEAN | yes |  |
| `ex_certificate_numbers` | VARCHAR(80)[] | yes |  |
| `casing_type` | VARCHAR(80) | yes | radially split \| axially split \| barrel \| double casing |
| `casing_design_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `max_allowable_working_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `casing_design_temperature_min_c` | NUMERIC(18, 6) | yes |  |
| `casing_design_temperature_max_c` | NUMERIC(18, 6) | yes |  |
| `hydrostatic_test_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `pressure_class` | VARCHAR(40) | yes | ASME/ANSI class or API rating of the casing |
| `casing_design_code` | VARCHAR(120) | yes | e.g. ASME VIII Div.1, PED 2014/68/EU |
| `nozzle_load_capability` | VARCHAR(160) | yes | e.g. 2x API 610 Table 5 allowable |
| `performance_test_required` | BOOLEAN | yes |  |
| `performance_test_grade` | VARCHAR(40) | yes | e.g. API 610 Table 16 / HI 14.6 grade 1B |
| `npsh_test_required` | BOOLEAN | yes |  |
| `mechanical_run_test_required` | BOOLEAN | yes |  |
| `mechanical_run_duration_hours` | NUMERIC(18, 6) | yes |  |
| `hydrostatic_test_required` | BOOLEAN | yes |  |
| `string_test_required` | BOOLEAN | yes |  |
| `complete_unit_test_required` | BOOLEAN | yes |  |
| `nde_requirements` | TEXT | yes | Non-destructive examination scope: RT / UT / MPI / DPI extents |
| `witness_level` | VARCHAR(40) | yes | witnessed \| observed \| monitored \| unwitnessed |
| `test_standard` | VARCHAR(120) | yes |  |
| `noise_limit_dba` | NUMERIC(18, 6) | yes |  |
| `vibration_limit_mm_s` | NUMERIC(18, 6) | yes |  |
| `external_coating_spec` | VARCHAR(200) | yes | e.g. NORSOK M-501 System 1 |
| `internal_coating_spec` | VARCHAR(200) | yes |  |
| `paint_system_standard` | VARCHAR(120) | yes | NORSOK M-501 \| ISO 12944 \| client spec |
| `coating_dft_microns` | NUMERIC(18, 6) | yes |  |
| `surface_preparation` | VARCHAR(120) | yes | e.g. ISO 8501-1 Sa 2.5 |
| `corrosion_category` | VARCHAR(24) | yes | ISO 12944 category, e.g. CX offshore |
| `galvanic_protection` | VARCHAR(160) | yes |  |
| `instrumentation_scope` | TEXT | yes |  |
| `vibration_monitoring` | VARCHAR(160) | yes | API 670 accelerometers / velocity probes / none |
| `api_670_compliant` | BOOLEAN | yes |  |
| `temperature_monitoring` | VARCHAR(160) | yes |  |
| `pressure_instrumentation` | VARCHAR(160) | yes |  |
| `control_interface_protocol` | VARCHAR(120) | yes | Modbus TCP \| PROFIBUS DP \| HART \| FF \| Ethernet/IP |
| `local_control_panel` | BOOLEAN | yes |  |
| `junction_box_certification` | VARCHAR(120) | yes |  |
| `condition_monitoring_ready` | BOOLEAN | yes |  |
| `signal_list` | JSONB | no |  |
| `marine_class_society` | VARCHAR(80) | yes | DNV \| ABS \| LR \| BV \| ClassNK \| RINA \| none |
| `marine_certification_type` | VARCHAR(120) | yes | Type approval \| product certificate \| unit certificate |
| `third_party_certifications` | VARCHAR(120)[] | yes | Free list, e.g. CE/PED, ATEX, IECEx, UKCA |
| `certificate_numbers` | VARCHAR(120)[] | yes |  |
| `certification_valid_until` | DATE | yes |  |
| `inspection_authority` | VARCHAR(120) | yes |  |
| `spares_interchangeable_with` | VARCHAR(160)[] | yes | Model codes sharing rotating elements / wear parts |
| `parts_commonality_pct` | NUMERIC(18, 6) | yes |  |
| `common_rotating_element` | BOOLEAN | yes |  |
| `interchangeability_notes` | TEXT | yes |  |
| `obsolescence_risk` | VARCHAR(24) | yes | low \| medium \| high |
| `fluid_handled` | VARCHAR(160) | yes |  |
| `fluid_specific_gravity` | NUMERIC(18, 6) | yes |  |
| `fluid_viscosity_cst` | NUMERIC(18, 6) | yes |  |
| `fluid_temperature_min_c` | NUMERIC(18, 6) | yes |  |
| `fluid_temperature_max_c` | NUMERIC(18, 6) | yes |  |
| `solids_content_pct` | NUMERIC(18, 6) | yes |  |
| `h2s_service` | BOOLEAN | yes |  |
| `suction_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `discharge_pressure_barg` | NUMERIC(18, 6) | yes |  |
| `pump_model_id` | UUID | no | FK to `pump_models.id`. |
| `source_id` | UUID | yes | FK to `sources.id`. |
| `ai_job_id` | UUID | yes | FK to `ai_jobs.id`. |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `source_units` | JSONB | no | Original units/values per field, e.g. {"rated_capacity": "1200 USgpm"} |
| `notes` | TEXT | yes |  |
| `extra` | JSONB | no | Fields not yet promoted to columns |
| `data_submission_date` | DATE | yes | Date the supplier or analyst submitted this data |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `version` | INTEGER | no |  |
| `is_current` | BOOLEAN | no |  |
| `superseded_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `schema_version` | VARCHAR | no |  |

### `tenant_permissions`

Per-tenant feature entitlements and cross-tenant sharing grants.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `tenant_id` | UUID | no | FK to `tenants.id`. |
| `resource` | VARCHAR(64) | no |  |
| `action` | VARCHAR(32) | no |  |
| `granted` | BOOLEAN | no |  |
| `shared_with_tenant_id` | UUID | yes | FK to `tenants.id`. |
| `constraints` | JSONB | no |  |
| `expires_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `granted_by_user_id` | UUID | yes | FK to `users.id`. |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |

### `tenants`

Client companies. The root of every isolation boundary.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `slug` | VARCHAR(63) | no |  |
| `name` | VARCHAR(255) | no |  |
| `legal_name` | VARCHAR(255) | yes |  |
| `country` | VARCHAR(2) | yes | ISO 3166-1 alpha-2 |
| `industry_segment` | VARCHAR(120) | yes | e.g. upstream FPSO operator, EPC contractor |
| `status` | tenant_status | no |  |
| `plan` | tenant_plan | no |  |
| `contract_start` | DATE | yes |  |
| `contract_end` | DATE | yes |  |
| `can_use_shared_master` | BOOLEAN | no |  |
| `can_contribute_shared_master` | BOOLEAN | no |  |
| `max_users` | INTEGER | no |  |
| `max_ai_jobs_per_day` | INTEGER | no |  |
| `max_storage_mb` | INTEGER | no |  |
| `data_retention_days` | INTEGER | yes |  |
| `settings` | JSONB | no |  |
| `primary_contact_email` | VARCHAR(320) | yes |  |
| `notes` | TEXT | yes |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |

### `user_roles`

Role assignment join table.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `user_id` | UUID | no | Primary key. FK to `users.id`. |
| `role_id` | UUID | no | Primary key. FK to `roles.id`. |

### `users`

People. ``tenant_id IS NULL`` marks Targeticon platform staff.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `tenant_id` | UUID | yes | FK to `tenants.id`. NULL for Targeticon platform staff |
| `email` | VARCHAR(320) | no |  |
| `full_name` | VARCHAR(255) | no |  |
| `job_title` | VARCHAR(160) | yes |  |
| `hashed_password` | VARCHAR(255) | no |  |
| `is_active` | BOOLEAN | no |  |
| `is_platform_admin` | BOOLEAN | no | Can administer every tenant |
| `mfa_enabled` | BOOLEAN | no |  |
| `mfa_secret` | VARCHAR(64) | yes |  |
| `last_login_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `failed_login_count` | INTEGER | no |  |
| `locked_until` | TIMESTAMP WITH TIME ZONE | yes |  |
| `password_changed_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `preferences` | JSONB | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |

### `vendor_contacts`

Authorized representatives, agents and service contacts.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `vendor_id` | UUID | no | FK to `vendors.id`. |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
| `contact_role` | VARCHAR(80) | no | commercial \| technical \| agent \| service \| authorized_representative |
| `full_name` | VARCHAR(255) | yes |  |
| `company_name` | VARCHAR(255) | yes | Set when the contact is an agent/representative entity |
| `email` | VARCHAR(320) | yes |  |
| `phone` | VARCHAR(64) | yes |  |
| `country` | VARCHAR(2) | yes |  |
| `territory` | VARCHAR(255) | yes |  |
| `agency_agreement_valid_until` | DATE | yes |  |
| `is_primary` | BOOLEAN | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |

### `vendors`

Suppliers. ``tenant_id IS NULL`` marks curated shared master data.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `name` | VARCHAR(255) | no |  |
| `normalized_name` | VARCHAR(255) | no | Lowercased, legal-suffix-stripped; dedupe key |
| `aliases` | VARCHAR(255)[] | yes |  |
| `website` | VARCHAR(500) | yes |  |
| `hq_country` | VARCHAR(2) | yes |  |
| `country` | VARCHAR(2) | yes | Operating country for this record |
| `hq_city` | VARCHAR(120) | yes |  |
| `logo_url` | VARCHAR(500) | yes |  |
| `description` | TEXT | yes |  |
| `ai_summary` | TEXT | yes | Gemma-generated vendor briefing; regenerated on material change |
| `ai_summary_generated_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `vendor_tier` | vendor_tier | no |  |
| `vendor_category` | VARCHAR(120) | yes | Client-specific category label |
| `product_families` | VARCHAR(120)[] | yes |  |
| `manufacturing_countries` | VARCHAR(2)[] | yes |  |
| `approval_status` | vendor_approval_status | no |  |
| `approval_expiry` | DATE | yes |  |
| `approved_by_user_id` | UUID | yes | FK to `users.id`. |
| `sanctions_status` | sanctions_screening_status | no |  |
| `sanctions_screened_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `sanctions_notes` | TEXT | yes |  |
| `geopolitical_risk_notes` | TEXT | yes |  |
| `annual_revenue_usd` | NUMERIC(18, 2) | yes |  |
| `revenue_year` | INTEGER | yes |  |
| `employee_count` | INTEGER | yes |  |
| `credit_rating_agency` | VARCHAR(80) | yes |  |
| `credit_rating` | VARCHAR(32) | yes |  |
| `dun_bradstreet_number` | VARCHAR(32) | yes |  |
| `financial_standing_notes` | TEXT | yes |  |
| `bonding_capacity_usd` | NUMERIC(18, 2) | yes |  |
| `can_provide_performance_bond` | BOOLEAN | yes |  |
| `can_provide_advance_payment_guarantee` | BOOLEAN | yes |  |
| `insurance_coverage_usd` | NUMERIC(18, 2) | yes |  |
| `insurance_details` | JSONB | no |  |
| `on_time_delivery_pct` | NUMERIC(5, 4) | yes |  |
| `total_units_supplied` | INTEGER | yes |  |
| `fpso_offshore_experience` | BOOLEAN | yes |  |
| `data_completeness_pct` | NUMERIC(5, 4) | yes |  |
| `confidence_level` | confidence_level | no |  |
| `verification_status` | verification_status | no |  |
| `primary_source_id` | UUID | yes | FK to `sources.id`. |
| `last_verified_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `created_by_user_id` | UUID | yes | FK to `users.id`. |
| `is_shared_master` | BOOLEAN | no |  |
| `merged_into_vendor_id` | UUID | yes | FK to `vendors.id`. Set when this record was merged away as a duplicate |
| `extra` | JSONB | no |  |
| `id` | UUID | no | Primary key. |
| `created_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | no |  |
| `deleted_at` | TIMESTAMP WITH TIME ZONE | yes |  |
| `tenant_id` | UUID | yes | FK to `tenants.id`. |
