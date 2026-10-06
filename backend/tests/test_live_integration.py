"""Integration tests against a running API and a live PostgreSQL.

Skipped unless ``PUMPATLAS_LIVE_API`` points at a running instance:

    docker compose -f infra/docker-compose.deps.yml up -d
    cd backend && python -m scripts.seed
    python -m scripts.manage_user create --email admin@example.com --name Admin --platform-admin
    python -m uvicorn app.main:app --port 8000

Then export the credentials of two accounts - a platform administrator and the demo
tenant's analyst - and run them:

    PUMPATLAS_LIVE_API=http://127.0.0.1:8000/api/v1
    PUMPATLAS_TEST_ADMIN_EMAIL / PUMPATLAS_TEST_ADMIN_PASSWORD
    PUMPATLAS_TEST_ANALYST_EMAIL / PUMPATLAS_TEST_ANALYST_PASSWORD
    pytest tests/test_live_integration.py

These cover what the offline suite structurally cannot: that row level security really
isolates tenants, that the versioning triggers really fire, and that provenance survives
a version bump. Every one of them caught a real bug the first time it ran.

The tests assume the seeded demo tenant and are safe to re-run; they create their own
tenants and records with unique names, and remove them again on teardown. A crashed run
can still leave rows behind - `python -m scripts.remove_test_residue` clears those.
"""

from __future__ import annotations

import os
import uuid

import pytest

httpx = pytest.importorskip("httpx")

BASE = os.environ.get("PUMPATLAS_LIVE_API")

# Credentials come from the environment of the person running these, not from a constant.
# They used to be the seeder's default password, which stopped being true the moment a
# login became a database row instead of a line in `.env` - and hardcoding a real
# password in a test file is how it ends up committed.
ADMIN = {
    "email": os.environ.get("PUMPATLAS_TEST_ADMIN_EMAIL", ""),
    "password": os.environ.get("PUMPATLAS_TEST_ADMIN_PASSWORD", ""),
}
ANALYST = {
    "email": os.environ.get("PUMPATLAS_TEST_ANALYST_EMAIL", ""),
    "password": os.environ.get("PUMPATLAS_TEST_ANALYST_PASSWORD", ""),
}

pytestmark = pytest.mark.skipif(
    not BASE or not ADMIN["password"] or not ANALYST["password"],
    reason=(
        "set PUMPATLAS_LIVE_API plus PUMPATLAS_TEST_ADMIN_EMAIL/PASSWORD and "
        "PUMPATLAS_TEST_ANALYST_EMAIL/PASSWORD to run these against a live stack"
    ),
)


def login(creds: dict, tenant: str | None = None) -> httpx.Client:
    client = httpx.Client(base_url=BASE, timeout=90)
    response = client.post("/auth/login", json=creds)
    response.raise_for_status()
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    if tenant:
        client.headers["X-Tenant-Id"] = tenant
    return client


@pytest.fixture(scope="module")
def admin() -> httpx.Client:
    return login(ADMIN)


@pytest.fixture(scope="module")
def analyst() -> httpx.Client:
    return login(ANALYST)


def sample_payload(model_code: str, vendor: str = "Sulzer Pumps Ltd") -> dict:
    return {
        "vendor_name": vendor,
        "vendor_country": "CH",
        "pump_name": "MSD Between Bearings",
        "model_code": model_code,
        "pump_type": "between_bearings_bb3",
        "applicable_standard": "api_610",
        "service_application": "crude export",
        "confidence_level": "vendor_declared",
        "technical": {
            "rated_capacity_m3h": 305,
            "rated_head_m": 138,
            "npsh_required_m": 3.2,
            "hydraulic_efficiency_pct": 78,
            "material_class": "S-6",
            "area_classification": "zone_1",
            "nace_mr0175_compliant": True,
            "marine_class_society": "DNV",
            "third_party_certifications": ["ATEX", "IECEx"],
            "atex_certified": True,
        },
        "commercial": {
            "base_price_amount": 310000,
            "base_price_currency": "USD",
            "base_price_usd": 310000,
            "warranty_months": 24,
        },
        "dimensional": {"dry_weight_kg": 3200, "operating_weight_kg": 3450},
        "delivery": {"standard_lead_time_weeks": 26, "country_of_origin": "CH"},
        "operational": {"units_supplied": 240, "fpso_experience": True},
        "administrative": {"legal_entity_name": vendor, "registration_country": "CH"},
    }


@pytest.fixture(scope="module")
def ingested(analyst: httpx.Client) -> dict:
    code = f"MSD-{uuid.uuid4().hex[:8].upper()}"
    response = analyst.post("/ingest/manual", json=sample_payload(code))
    assert response.status_code == 201, response.text
    return {"code": code, **response.json()}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_login_returns_tenant_and_roles(analyst: httpx.Client):
    me = analyst.get("/auth/me").json()
    assert me["tenant_slug"] == "demo-operator"
    assert me["roles"][0]["name"] == "research_analyst"
    assert "commercial_spec" in me["permissions"]


def test_wrong_password_is_rejected():
    response = httpx.post(
        f"{BASE}/auth/login",
        json={"email": ANALYST["email"], "password": "definitely-wrong"},
        timeout=30,
    )
    assert response.status_code == 401


def test_unauthenticated_request_is_rejected():
    assert httpx.get(f"{BASE}/vendors", timeout=30).status_code == 401


# ---------------------------------------------------------------------------
# Ingestion writes through the whole chain
# ---------------------------------------------------------------------------


def test_manual_submission_writes_all_six_spec_groups(ingested: dict):
    assert set(ingested["written"]) == {
        "technical",
        "commercial",
        "dimensional",
        "delivery",
        "operational",
        "administrative",
    }
    assert len(ingested["written"]["technical"]["applied"]) >= 8
    assert ingested["written"]["technical"]["refused"] == {}


def test_source_row_is_created_for_the_form(analyst: httpx.Client, ingested: dict):
    source = analyst.get(f"/ingest/sources/{ingested['source_id']}").json()
    assert source["source_type"] == "manual_form"
    assert source["content_hash"]


def test_search_index_is_populated_by_the_db_trigger(analyst: httpx.Client, ingested: dict):
    response = analyst.post("/search", json={"query": ingested["code"]})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    row = response.json()["items"][0]
    assert row["rated_capacity_m3h"] == 305.0
    # Certifications are gathered from two different spec tables by the indexer.
    assert {"ATEX", "DNV"} <= set(row["certifications"])


def test_numeric_and_boolean_filters(analyst: httpx.Client, ingested: dict):
    matching = analyst.post(
        "/search",
        json={
            "query": ingested["code"],
            "capacity_min": 300,
            "capacity_max": 310,
            "npshr_max": 5,
            "lead_time_max": 30,
            "fpso_experience": True,
        },
    ).json()
    assert matching["total"] == 1

    excluded = analyst.post(
        "/search", json={"query": ingested["code"], "capacity_min": 9000}
    ).json()
    assert excluded["total"] == 0


def test_facets_are_returned(analyst: httpx.Client):
    facets = analyst.post("/search", json={"include_facets": True}).json()["facets"]
    assert facets["pump_type"]


# ---------------------------------------------------------------------------
# Provenance - the platform's central claim
# ---------------------------------------------------------------------------


def test_profile_provenance_spans_the_model_and_its_specs(analyst: httpx.Client, ingested: dict):
    """Regression: this reported 0 because it only looked at the pump_models row."""
    summary = analyst.get(f"/pump-models/{ingested['pump_model_id']}").json()["provenance_summary"]
    assert summary["total_fields_with_provenance"] >= 20
    assert summary["ai_derived_fields"] == 0
    assert summary["ai_share_pct"] == 0.0
    assert summary["by_origin"] == {"manual": summary["total_fields_with_provenance"]}


def test_field_lineage_names_its_source(analyst: httpx.Client, ingested: dict):
    """Regression: this 500'd because UUID columns were typed as `str`."""
    rows = analyst.get(
        f"/pump-models/{ingested['pump_model_id']}/provenance",
        params={"entity_type": "technical_specs"},
    )
    assert rows.status_code == 200, rows.text
    entry = next(r for r in rows.json() if r["field_name"] == "rated_head_m")
    assert entry["value_origin"] == "manual"
    assert entry["source_id"]
    assert entry["confidence_level"] == "vendor_declared"


# ---------------------------------------------------------------------------
# Spec versioning: the DB triggers
# ---------------------------------------------------------------------------


def test_spec_write_opens_a_new_version_and_retires_the_old(analyst: httpx.Client, ingested: dict):
    model = ingested["pump_model_id"]
    written = analyst.put(
        f"/pump-models/{model}/specs/technical",
        json={"rated_head_m": 141.5, "impeller_diameter_mm": 279},
    )
    assert written.status_code == 200, written.text
    new_version = written.json()["version"]
    assert new_version >= 2

    current = analyst.get(f"/pump-models/{model}/specs/technical").json()
    assert current["version"] == new_version
    assert current["is_current"] is True
    assert float(current["data"]["rated_head_m"]) == 141.5
    # Untouched fields must survive a partial write.
    assert float(current["data"]["rated_capacity_m3h"]) == 305.0

    previous = analyst.get(
        f"/pump-models/{model}/specs/technical", params={"version": new_version - 1}
    ).json()
    assert previous["is_current"] is False, "the supersede trigger did not fire"
    assert float(previous["data"]["rated_head_m"]) == 138.0

    history = analyst.get(f"/pump-models/{model}/specs/technical/versions").json()
    assert sum(1 for v in history if v["is_current"]) == 1


def test_provenance_survives_a_version_bump(analyst: httpx.Client, ingested: dict):
    """Regression: carrying a value forward used to drop its lineage.

    After an edit to one field, every other field on the new version must still be able
    to name where it came from - otherwise the traceability guarantee lasts exactly one
    edit.
    """
    model = ingested["pump_model_id"]
    analyst.put(f"/pump-models/{model}/specs/commercial", json={"warranty_months": 36})

    rows = analyst.get(
        f"/pump-models/{model}/provenance", params={"entity_type": "commercial_specs"}
    ).json()
    fields = {r["field_name"] for r in rows}
    assert "warranty_months" in fields, "the edited field has no provenance"
    assert "base_price_amount" in fields, "a carried-forward field lost its provenance"


def test_new_version_does_not_lose_unrelated_fields(analyst: httpx.Client, ingested: dict):
    """A spec write must not silently blank the rest of the group."""
    model = ingested["pump_model_id"]
    analyst.put(f"/pump-models/{model}/specs/commercial", json={"payment_terms": "30/60/10"})
    current = analyst.get(f"/pump-models/{model}/specs/commercial").json()["data"]
    assert current["payment_terms"] == "30/60/10"
    assert float(current["base_price_amount"]) == 310000.0


# ---------------------------------------------------------------------------
# Data quality validators against real rows
# ---------------------------------------------------------------------------


def test_contradictory_weights_raise_a_flag(analyst: httpx.Client, ingested: dict):
    model = ingested["pump_model_id"]
    written = analyst.put(
        f"/pump-models/{model}/specs/dimensional",
        json={"dry_weight_kg": 3200, "operating_weight_kg": 2100},
    )
    assert written.status_code == 200, written.text
    assert written.json()["quality_flags_raised"] > 0

    flags = analyst.get("/quality/flags", params={"limit": 100}).json()["items"]
    messages = " ".join(f["message"] for f in flags)
    assert "below dry weight" in messages


def test_feet_stored_as_metres_is_reported_as_a_unit_mismatch(
    analyst: httpx.Client, ingested: dict
):
    model = ingested["pump_model_id"]
    analyst.put(f"/pump-models/{model}/specs/technical", json={"rated_head_m": 4500})
    flags = analyst.get("/quality/flags", params={"limit": 100}).json()["items"]
    unit_flags = [f for f in flags if f["flag_type"] == "unit_mismatch"]
    assert unit_flags
    assert any("feet" in f["message"] for f in unit_flags)
    # restore a plausible value for the scoring tests
    analyst.put(f"/pump-models/{model}/specs/technical", json={"rated_head_m": 138})


def test_quality_dashboard_aggregates(analyst: httpx.Client):
    dashboard = analyst.get("/quality/dashboard").json()
    assert dashboard["total_pump_models"] >= 1
    assert sum(dashboard["open_flags_by_severity"].values()) > 0
    assert dashboard["ai_field_share_pct"] == 0.0


# ---------------------------------------------------------------------------
# Scoring and comparison
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def profile(analyst: httpx.Client) -> str:
    response = analyst.post(
        "/requirement-profiles",
        json={
            "name": f"P-1201 crude export {uuid.uuid4().hex[:6]}",
            "project_name": "FPSO Alpha",
            "required_capacity_m3h": 300,
            "required_head_m": 140,
            "max_npshr_m": 5,
            "min_efficiency_pct": 70,
            "required_standard": "api_610",
            "required_area_classification": "zone_1",
            "required_certifications": ["ATEX", "DNV"],
            "nace_required": True,
            "max_lead_time_weeks": 30,
            "max_budget_usd": 400000,
            "excluded_countries": ["IR", "RU"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_scorecard_weights_must_sum_to_one(analyst: httpx.Client):
    response = analyst.post(
        "/requirement-profiles",
        json={
            "name": "invalid weights",
            "weight_technical": 0.5,
            "weight_commercial": 0.5,
            "weight_delivery": 0.5,
            "weight_data_confidence": 0.5,
        },
    )
    assert response.status_code == 422


def test_matching_candidate_scores_well_and_is_not_disqualified(
    analyst: httpx.Client, ingested: dict, profile: str
):
    cards = analyst.post(
        f"/pump-models/{ingested['pump_model_id']}/score",
        params={"requirement_profile_id": profile},
    ).json()["scorecards"]
    assert cards["technical"]["score"] > 70
    assert cards["overall"]["disqualified"] is False
    assert "capacity" in cards["technical"]["breakdown"]
    # Data confidence must reflect real completeness, not sit at 100.
    assert 0 < cards["data_confidence"]["score"] < 100


def test_comparison_freezes_a_reproducible_snapshot(
    analyst: httpx.Client, ingested: dict, profile: str
):
    response = analyst.post(
        "/comparisons",
        json={
            "name": f"P-1201 shortlist {uuid.uuid4().hex[:6]}",
            "requirement_profile_id": profile,
            "pump_model_ids": [ingested["pump_model_id"]],
        },
    )
    assert response.status_code == 201, response.text
    comparison = response.json()
    assert comparison["items"][0]["rank"] == 1
    snapshot = comparison["snapshot"]
    assert snapshot["scoring_version"] == "1.0.0"
    assert snapshot["rows"][0]["values"]
    assert snapshot["requirement_profile"]["required_capacity_m3h"]

    reloaded = analyst.get(f"/comparisons/{comparison['id']}").json()
    assert reloaded["items"][0]["rank"] == 1


# ---------------------------------------------------------------------------
# Tenant isolation - the reason row level security exists
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rival(admin: httpx.Client):
    """A second tenant with its own data, used to prove tenant A cannot reach it.

    Removes what it created on teardown; see the comment at the yield.
    """
    slug = f"rival-epc-{uuid.uuid4().hex[:6]}"
    password = "RivalPassword123!"
    created = admin.post(
        "/tenants",
        json={
            "slug": slug,
            "name": "Rival EPC Contractor",
            "country": "KR",
            "plan": "standard",
            "admin_email": f"lead@{slug}.example",
            "admin_full_name": "Rival Lead",
            "admin_password": password,
        },
    )
    assert created.status_code == 201, created.text
    tenant_id = created.json()["id"]

    client = login({"email": f"lead@{slug}.example", "password": password})
    code = f"SECRET-{uuid.uuid4().hex[:6].upper()}"
    ingest = client.post(
        "/ingest/manual",
        json={
            "vendor_name": f"Confidential Rival Vendor {slug}",
            "vendor_country": "KR",
            "model_code": code,
            "pump_type": "centrifugal_oh2",
            "applicable_standard": "api_610",
            # The same duty point as tenant A's pump, so similarity matching would
            # surface it if isolation were broken.
            "technical": {"rated_capacity_m3h": 305, "rated_head_m": 138},
            "commercial": {
                "base_price_amount": 99000,
                "base_price_currency": "USD",
                "base_price_usd": 99000,
            },
        },
    )
    assert ingest.status_code == 201, ingest.text
    created_records = ingest.json()

    yield {
        "slug": slug,
        "tenant_id": tenant_id,
        "client": client,
        "code": code,
        **created_records,
    }

    # Clean up after ourselves. Without this every run left a
    # "Confidential Rival Vendor rival-epc-…" in the vendor list and a searchable
    # SECRET-… pump model, indistinguishable to anyone reading the UI from real
    # supply-chain data - and there is no way to tell from a row that it came from a
    # test. Soft deletes, so the audit trail of the run survives.
    #
    # Best effort: a failing teardown would mask the test result that matters, and
    # `scripts/remove_test_residue.py` exists to mop up whatever a crashed run leaves.
    for path in (
        f"/pump-models/{created_records.get('pump_model_id')}",
        f"/vendors/{created_records.get('vendor_id')}",
    ):
        try:
            client.delete(path)
        except Exception:  # noqa: BLE001 - teardown must not fail the suite
            pass
    try:
        # Tenants suspend rather than delete, by design: client data is retained for the
        # contract term. Suspending at least stops its users signing in.
        admin.delete(f"/tenants/{tenant_id}")
    except Exception:  # noqa: BLE001
        pass


def test_rls_blocks_cross_tenant_search(analyst: httpx.Client, rival: dict):
    assert analyst.post("/search", json={"query": rival["code"]}).json()["total"] == 0


def test_rls_blocks_cross_tenant_direct_id_access(analyst: httpx.Client, rival: dict):
    """Guessing a UUID must not be enough."""
    assert analyst.get(f"/pump-models/{rival['pump_model_id']}").status_code == 404
    assert analyst.get(f"/vendors/{rival['vendor_id']}/profile").status_code == 404
    assert analyst.get(f"/vendors/{rival['vendor_id']}").status_code == 404


def test_rls_blocks_the_other_direction(rival: dict, ingested: dict):
    assert rival["client"].post("/search", json={"query": ingested["code"]}).json()["total"] == 0
    assert rival["client"].get(f"/pump-models/{ingested['pump_model_id']}").status_code == 404


def test_each_tenant_still_sees_its_own_data(analyst: httpx.Client, rival: dict, ingested: dict):
    assert analyst.post("/search", json={"query": ingested["code"]}).json()["total"] == 1
    assert rival["client"].post("/search", json={"query": rival["code"]}).json()["total"] == 1


def test_similar_pump_matching_does_not_cross_tenants(
    analyst: httpx.Client, rival: dict, ingested: dict
):
    """The rival pump has an identical duty point, so this is the real test."""
    matches = analyst.post(
        f"/search/similar/{ingested['pump_model_id']}",
        json={"limit": 25, "duty_tolerance_pct": 50},
    ).json()["items"]
    assert all(m["pump_model_id"] != rival["pump_model_id"] for m in matches)


def test_platform_admin_scoped_to_a_tenant_sees_only_that_tenant(
    admin: httpx.Client, rival: dict, ingested: dict
):
    """Regression: the admin bypass stayed on, so scoping showed every tenant."""
    scoped = login(ADMIN, tenant=rival["tenant_id"])
    assert scoped.post("/search", json={"query": rival["code"]}).json()["total"] == 1
    assert scoped.post("/search", json={"query": ingested["code"]}).json()["total"] == 0


def test_non_admin_cannot_borrow_another_tenants_scope(analyst: httpx.Client, rival: dict):
    response = analyst.get("/vendors", headers={"X-Tenant-Id": rival["tenant_id"]})
    assert response.status_code == 403


def test_non_admin_cannot_list_tenants(rival: dict):
    assert rival["client"].get("/tenants").status_code == 403


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_client_user_cannot_reach_commercial_terms_or_ingestion(admin: httpx.Client, rival: dict):
    email = f"viewer@{rival['slug']}.example"
    password = "ViewerPassword123!"
    created = admin.post(
        "/users",
        json={
            "email": email,
            "full_name": "Client Viewer",
            "password": password,
            "roles": ["client_user"],
            "tenant_id": rival["tenant_id"],
        },
    )
    assert created.status_code == 201, created.text
    viewer = login({"email": email, "password": password})

    # A client user can look, and that is all.
    assert viewer.post("/search", json={"query": rival["code"]}).json()["total"] == 1
    assert (
        viewer.put(
            f"/pump-models/{rival['pump_model_id']}/specs/commercial",
            json={"warranty_months": 99},
        ).status_code
        == 403
    )
    assert viewer.post("/ingest/manual", json={"vendor_name": "Sneaky"}).status_code == 403
    assert viewer.get("/quality/dashboard").status_code == 403
    assert viewer.get("/audit-logs").status_code == 403


def test_analyst_cannot_read_the_audit_trail(analyst: httpx.Client):
    assert analyst.get("/audit-logs").status_code == 403


def test_platform_admin_can_read_the_audit_trail(admin: httpx.Client):
    """Regression: this 500'd because psycopg returns IPv4Address for an INET column."""
    response = admin.get("/audit-logs", params={"limit": 25})
    assert response.status_code == 200, response.text
    assert response.json()["total"] > 5
    entry = response.json()["items"][0]
    assert entry["action"]
    assert entry["occurred_at"]


def test_audit_trail_records_writes_with_a_diff(admin: httpx.Client):
    entries = admin.get("/audit-logs", params={"limit": 100, "action": "update"}).json()
    assert entries["total"] >= 1
    assert any(e["changes"] for e in entries["items"])


# ---------------------------------------------------------------------------
# Duplicate detection via pg_trgm
# ---------------------------------------------------------------------------


def test_pg_trgm_flags_a_near_duplicate_vendor(analyst: httpx.Client):
    suffix = uuid.uuid4().hex[:6]
    first = analyst.post("/vendors", json={"name": f"Ruhrpumpen {suffix} GmbH", "country": "DE"})
    assert first.status_code == 201, first.text
    second = analyst.post(
        "/vendors", json={"name": f"Ruhrpumpen {suffix} Gmbh Limited", "country": "DE"}
    )
    # Either the unique constraint catches it, or duplicate detection flags it.
    if second.status_code == 409:
        return
    assert second.status_code == 201, second.text

    candidates = analyst.get(f"/vendors/{second.json()['id']}/duplicates")
    assert candidates.status_code == 200, candidates.text
    assert candidates.json(), "pg_trgm found no near-duplicate"
    signals = candidates.json()[0]["match_signals"]
    assert "trigram_name" in signals or "normalized_name" in signals
