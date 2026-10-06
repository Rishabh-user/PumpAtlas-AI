"""Contract tests that need no database.

They assert the API surface itself: the routes exist, no route is shadowed by a UUID
path parameter, the generated spec schemas cover every intelligence field in the brief,
and the RBAC matrix keeps commercial terms away from client users.
"""

from app.core import rbac
from app.main import app
from app.models.enums import UserRoleName
from app.schemas.specs import ALL_TRACKED_FIELDS, SPEC_FIELDS


def paths() -> dict:
    return app.openapi()["paths"]


def test_openapi_builds():
    schema = app.openapi()
    assert schema["info"]["title"] == "PumpAtlas AI"
    assert schema["paths"]


def test_core_module_routes_exist():
    expected = [
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/search",
        "/api/v1/search/similar/{pump_model_id}",
        "/api/v1/vendors",
        "/api/v1/vendors/{vendor_id}/profile",
        "/api/v1/vendors/merge",
        "/api/v1/pumps",
        "/api/v1/pump-models",
        "/api/v1/pump-models/{pump_model_id}",
        "/api/v1/pump-models/{pump_model_id}/specs/{group}",
        "/api/v1/pump-models/{pump_model_id}/specs/{group}/versions",
        "/api/v1/pump-models/{pump_model_id}/provenance",
        "/api/v1/ingest/upload",
        "/api/v1/ingest/urls",
        "/api/v1/ingest/web-search",
        "/api/v1/ingest/manual",
        "/api/v1/ingest/batches",
        "/api/v1/ai/review-queue",
        "/api/v1/ai/suggestions",
        "/api/v1/ai/usage",
        "/api/v1/quality/dashboard",
        "/api/v1/quality/flags",
        "/api/v1/quality/duplicates",
        "/api/v1/comparisons",
        "/api/v1/vendor-comparison",
        "/api/v1/requirement-profiles",
        "/api/v1/audit-logs",
        "/api/v1/record-versions",
        "/api/v1/tenants",
        "/api/v1/users",
        "/api/v1/tags",
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/meta/vocabularies",
    ]
    missing = [path for path in expected if path not in paths()]
    assert not missing, f"missing routes: {missing}"


def test_no_route_shadowed_by_a_uuid_path_param():
    """A static segment sharing a method with a sibling {uuid} route would 422.

    Starlette keeps scanning past a path match whose method does not match, so a
    static route is only shadowed when the {uuid} route answers the *same* method.
    """
    spec = paths()
    uuid_leaves = ("{comparison_id}", "{tenant_id}", "{vendor_id}", "{pump_model_id}")
    conflicts = []
    for path, operations in spec.items():
        if not path.endswith(uuid_leaves):
            continue
        prefix = path.rsplit("/", 1)[0]
        uuid_methods = {m for m in operations if m in ("get", "post", "put", "patch", "delete")}
        for other, other_ops in spec.items():
            if not other.startswith(f"{prefix}/") or other == path:
                continue
            segment = other[len(prefix) + 1 :].split("/")[0]
            if segment.startswith("{"):
                continue
            clash = uuid_methods & set(other_ops)
            if clash:
                conflicts.append(f"{other} {sorted(clash)} shadowed by {path}")
    assert not conflicts, "shadowed routes: " + "; ".join(conflicts)


def test_static_route_under_uuid_prefix_actually_resolves():
    """Proves the routing claim above rather than trusting it."""
    from fastapi.testclient import TestClient

    # No `with`: the lifespan probes PostgreSQL, and this test is about routing only.
    response = TestClient(app).post("/api/v1/vendors/merge", json={})
    # 401 = the route matched and asked for credentials.
    # 422 would mean "merge" was parsed as a vendor_id and failed UUID validation.
    assert response.status_code == 401, response.text


def test_spec_groups_cover_every_required_field_group():
    assert set(SPEC_FIELDS) == {
        "technical",
        "commercial",
        "dimensional",
        "delivery",
        "operational",
        "administrative",
    }
    assert len(ALL_TRACKED_FIELDS) > 380


def test_required_technical_fields_are_modelled():
    technical = set(SPEC_FIELDS["technical"])
    for field in (
        "rated_capacity_m3h",
        "rated_head_m",
        "npsh_required_m",
        "hydraulic_efficiency_pct",
        "rated_speed_rpm",
        "driver_type",
        "casing_material",
        "impeller_material",
        "shaft_material",
        "seal_system_type",
        "seal_piping_plan",
        "radial_bearing_type",
        "thrust_bearing_type",
        "lubrication_type",
        "area_classification",
        "casing_design_pressure_barg",
        "performance_test_required",
        "external_coating_spec",
        "control_interface_protocol",
        "marine_class_society",
        "spares_interchangeable_with",
        "material_class",
    ):
        assert field in technical, f"technical spec is missing {field}"


def test_required_commercial_fields_are_modelled():
    commercial = set(SPEC_FIELDS["commercial"])
    for field in (
        "base_price_amount",
        "payment_terms",
        "warranty_months",
        "spares_price_amount",
        "price_escalation_formula",
        "volume_discount_schedule",
        "historical_price_benchmark_usd",
        "lifecycle_cost_usd",
        "local_content_pct",
        "import_duty_pct",
        "financial_standing_summary",
        "bonding_capability",
        "insurance_capability",
    ):
        assert field in commercial, f"commercial spec is missing {field}"


def test_required_dimensional_fields_are_modelled():
    dimensional = set(SPEC_FIELDS["dimensional"])
    for field in (
        "dry_weight_kg",
        "operating_weight_kg",
        "shipping_weight_kg",
        "crate_length_mm",
        "baseplate_length_mm",
        "footprint_area_m2",
        "cog_x_mm",
        "lifting_points_count",
        "static_load_kn",
        "max_maintenance_lift_weight_kg",
        "packaging_type",
        "fpso_module_space_envelope",
    ):
        assert field in dimensional, f"dimensional spec is missing {field}"


def test_required_delivery_fields_are_modelled():
    delivery = set(SPEC_FIELDS["delivery"])
    for field in (
        "standard_lead_time_weeks",
        "expedited_lead_time_weeks",
        "expedite_premium_pct",
        "manufacturing_locations",
        "logistics_lead_time_weeks",
        "incoterms_offered",
        "documentation_lead_time_weeks",
        "fat_duration_days",
        "fat_lead_time_weeks",
        "historical_on_time_delivery_pct",
        "long_lead_components",
        "country_of_origin",
        "export_control_classification",
    ):
        assert field in delivery, f"delivery spec is missing {field}"


def test_required_operational_fields_are_modelled():
    operational = set(SPEC_FIELDS["operational"])
    for field in (
        "reference_list",
        "units_supplied",
        "units_installed_operating",
        "mtbf_hours",
        "fpso_experience",
        "service_network_countries",
        "post_warranty_spares_years",
        "training_offered",
        "commissioning_support_included",
        "hse_trir",
        "qaqc_certifications",
        "approved_vendor_list_membership",
    ):
        assert field in operational, f"operational spec is missing {field}"


def test_required_administrative_fields_are_modelled():
    administrative = set(SPEC_FIELDS["administrative"])
    for field in (
        "legal_entity_name",
        "registration_number",
        "authorized_representative_name",
        "local_agent_name",
        "esg_report_published",
        "iso_27001_certified",
        "iec_62443_compliance",
        "submitted_by_name",
        "verification_method",
    ):
        assert field in administrative, f"administrative spec is missing {field}"


def test_client_user_cannot_write_or_see_commercial_terms():
    client = [UserRoleName.CLIENT_USER.value]
    assert rbac.is_allowed(client, "search", "read")
    assert rbac.is_allowed(client, "vendor", "read")
    assert not rbac.is_allowed(client, "vendor", "write")
    assert not rbac.is_allowed(client, "commercial_spec", "read")
    assert not rbac.is_allowed(client, "audit", "read")
    assert not rbac.is_allowed(client, "tenant", "write")
    assert not rbac.is_allowed(client, "ingestion", "write")


def test_role_separation_matches_the_brief():
    engineering = [UserRoleName.ENGINEERING.value]
    procurement = [UserRoleName.PROCUREMENT.value]
    vendor_manager = [UserRoleName.VENDOR_MANAGER.value]

    assert rbac.is_allowed(engineering, "technical_spec", "write")
    assert not rbac.is_allowed(engineering, "commercial_spec", "write")

    assert rbac.is_allowed(procurement, "commercial_spec", "approve")
    assert not rbac.is_allowed(procurement, "technical_spec", "write")

    assert rbac.is_allowed(vendor_manager, "vendor", "approve")
    assert not rbac.is_allowed(vendor_manager, "pump", "write")


def test_admin_reads_everything_that_matters():
    admin = [UserRoleName.ADMIN.value]
    for resource in (
        "vendor",
        "pump",
        "technical_spec",
        "commercial_spec",
        "ingestion",
        "ai_review",
        "comparison",
        "data_quality",
        "tenant",
        "user",
        "audit",
    ):
        assert rbac.is_allowed(admin, resource, "read"), resource


def test_unknown_resource_or_action_is_denied():
    admin = [UserRoleName.ADMIN.value]
    assert not rbac.is_allowed(admin, "nuclear_launch", "write")
    assert not rbac.is_allowed(admin, "vendor", "teleport")


def test_permissions_for_is_serialisable_for_role_seeding():
    permissions = rbac.permissions_for(UserRoleName.PROCUREMENT)
    assert "commercial_spec" in permissions
    assert "approve" in permissions["commercial_spec"]
    assert all(isinstance(v, list) for v in permissions.values())
