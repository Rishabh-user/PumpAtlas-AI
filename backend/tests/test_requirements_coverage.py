"""The brief is a contract. This test is how it stays one.

``scripts/requirements_map.py`` maps every intelligence field named in the product brief
to the column that holds it. If a column is renamed or dropped, this fails - which is
exactly the moment someone should notice that the schema no longer matches what was
specified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from requirements_map import REQUIREMENTS, all_referenced_columns  # noqa: E402

from app.models import Base  # noqa: E402

EXPECTED_GROUPS = {
    "Technical data",
    "Commercial data",
    "Weight and dimensional data",
    "Delivery data",
    "Operational and track record data",
    "Administrative and data-quality data",
}


@pytest.fixture(scope="module")
def schema_columns() -> set[str]:
    return {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
    }


def test_all_six_requirement_groups_are_mapped():
    assert set(REQUIREMENTS) == EXPECTED_GROUPS


def test_every_mapped_column_exists_in_the_schema(schema_columns: set[str]):
    missing = [column for column in all_referenced_columns() if column not in schema_columns]
    assert not missing, (
        "The requirements map references columns that no longer exist. Either restore "
        f"them or update scripts/requirements_map.py: {missing}"
    )


def test_every_requirement_maps_to_at_least_one_column():
    empty = [
        f"{group} / {requirement}"
        for group, requirements in REQUIREMENTS.items()
        for requirement, columns in requirements.items()
        if not columns
    ]
    assert not empty, f"Requirements with no columns mapped: {empty}"


@pytest.mark.parametrize(
    ("group", "minimum"),
    [
        ("Technical data", 15),
        ("Commercial data", 11),
        ("Weight and dimensional data", 9),
        ("Delivery data", 10),
        ("Operational and track record data", 12),
        ("Administrative and data-quality data", 6),
    ],
)
def test_requirement_counts_match_the_brief(group: str, minimum: int):
    """The brief lists a specific number of fields per group; none may be dropped."""
    assert len(REQUIREMENTS[group]) >= minimum


def test_spec_tables_are_all_versioned():
    """Change tracking depends on every spec table carrying the versioning columns."""
    for table_name in (
        "technical_specs",
        "commercial_specs",
        "dimensional_specs",
        "delivery_specs",
        "operational_specs",
        "administrative_specs",
    ):
        table = Base.metadata.tables[table_name]
        for required in ("version", "is_current", "superseded_at", "schema_version"):
            assert required in table.columns, f"{table_name} is missing {required}"


def test_tenant_scoped_tables_carry_tenant_id():
    """Anything RLS protects must have the column the policy compares."""
    rls_tables = (
        "vendors",
        "vendor_contacts",
        "pumps",
        "pump_models",
        "technical_specs",
        "commercial_specs",
        "dimensional_specs",
        "delivery_specs",
        "operational_specs",
        "administrative_specs",
        "documents",
        "sources",
        "extracted_entities",
        "ai_jobs",
        "search_index",
        "field_provenance",
        "tags",
        "import_batches",
        "crawl_schedules",
        "confidence_scores",
        "data_quality_flags",
        "ai_suggestions",
        "duplicate_candidates",
        "requirement_profiles",
        "comparisons",
        "comparison_items",
        "saved_searches",
        "tagged_records",
        "record_versions",
        "audit_logs",
        "api_keys",
    )
    for table_name in rls_tables:
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.columns, f"{table_name} has no tenant_id for RLS"


def test_provenance_can_address_any_entity_and_field():
    """Traceability is generic: (entity_type, entity_id, field_name) plus the evidence."""
    table = Base.metadata.tables["field_provenance"]
    for column in (
        "entity_type",
        "entity_id",
        "field_name",
        "value_text",
        "value_origin",
        "confidence_level",
        "confidence_score",
        "source_id",
        "document_id",
        "ai_job_id",
        "model_used",
        "evidence_quote",
        "evidence_locator",
        "original_value",
        "original_unit",
        "is_current",
    ):
        assert column in table.columns, f"field_provenance is missing {column}"
