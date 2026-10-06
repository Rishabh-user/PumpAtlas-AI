"""Offline checks on the generated DDL.

No PostgreSQL server was available while this was built, so these tests catch the class
of schema mistake that only shows up when the server rejects the file: duplicate index
names, enum types used before they are created, foreign keys to tables that do not exist,
and columns whose name promises a unit the type cannot hold.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import Numeric
from sqlalchemy.sql.sqltypes import Enum as SAEnum

from app.models import Base

SCHEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture(scope="module")
def ddl() -> str:
    assert SCHEMA_SQL.exists(), "db/schema.sql is missing - run scripts/gen_schema.py"
    return SCHEMA_SQL.read_text(encoding="utf-8")


def test_schema_file_is_current(ddl: str):
    """Every table in the models must appear in the generated file."""
    for table in Base.metadata.sorted_tables:
        assert f"CREATE TABLE {table.name} (" in ddl, f"{table.name} missing from db/schema.sql"


def test_no_duplicate_index_names(ddl: str):
    names = re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", ddl)
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"duplicate index names would fail on CREATE: {duplicates}"


def test_no_duplicate_identifiers_across_the_whole_schema():
    """Index and constraint names share one namespace per schema in PostgreSQL.

    A per-table check is not enough: six spec tables once shared an explicit constraint
    name, which passed a per-table check and then failed on CREATE with
    'relation "pump_model_version" already exists'. Explicit ``name=`` arguments override
    the metadata naming convention, so the safe rule is to let the convention name things.
    """
    from collections import Counter

    identifiers: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        for constraint in table.constraints:
            if constraint.name and constraint.__class__.__name__ == "UniqueConstraint":
                identifiers.append((str(constraint.name), f"{table.name} (unique)"))
        for index in table.indexes:
            identifiers.append((str(index.name), f"{table.name} (index)"))

    counts = Counter(name for name, _ in identifiers)
    duplicates = {
        name: [owner for candidate, owner in identifiers if candidate == name]
        for name, count in counts.items()
        if count > 1
    }
    assert not duplicates, f"PostgreSQL would reject these duplicate identifiers: {duplicates}"


def test_every_enum_type_is_created_before_first_use(ddl: str):
    """CREATE TYPE statements are emitted ahead of the tables; verify the ordering."""
    created = {
        name: ddl.index(f"CREATE TYPE {name} AS ENUM")
        for name in re.findall(r"CREATE TYPE (\w+) AS ENUM", ddl)
    }
    for table in Base.metadata.sorted_tables:
        table_position = ddl.index(f"CREATE TABLE {table.name} (")
        for column in table.columns:
            if not isinstance(column.type, SAEnum):
                continue
            type_name = column.type.name
            assert (
                type_name in created
            ), f"{table.name}.{column.name} uses enum {type_name}, which is never created"
            assert (
                created[type_name] < table_position
            ), f"enum {type_name} is created after {table.name} uses it"


def test_foreign_keys_point_at_tables_that_exist():
    known = set(Base.metadata.tables)
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                target = fk.column.table.name
                assert (
                    target in known
                ), f"{table.name}.{column.name} references unknown table {target}"


def test_delete_behaviour_is_declared_on_every_foreign_key():
    """An FK with no ON DELETE rule turns a tenant deletion into a constraint error."""
    undeclared = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.ondelete is None:
                    undeclared.append(f"{table.name}.{column.name}")
    assert not undeclared, f"foreign keys without ON DELETE: {undeclared}"


def test_unit_suffixed_columns_are_numeric():
    """A column named _m3h or _kg must be able to hold a converted SI value."""
    suffixes = ("_m3h", "_kg", "_kw", "_barg", "_knm", "_kn", "_m2", "_m3", "_cst", "_tco2e")
    offenders = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.name.endswith(suffixes) and not isinstance(column.type, Numeric):
                offenders.append(f"{table.name}.{column.name} is {column.type}")
    assert not offenders, f"unit-suffixed columns that are not numeric: {offenders}"


# ai_jobs.cost_usd tracks fractions of a cent per model call, so it is deliberately
# finer-grained than the money columns a buyer ever sees.
FINER_GRAINED_MONEY = {"ai_jobs.cost_usd"}


def test_money_columns_share_one_precision():
    """Mixed precision across price columns silently changes rounding between tables."""
    by_precision: dict[tuple[int | None, int | None], list[str]] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            name = f"{table.name}.{column.name}"
            if name in FINER_GRAINED_MONEY:
                continue
            if column.name.endswith("_usd") and isinstance(column.type, Numeric):
                by_precision.setdefault((column.type.precision, column.type.scale), []).append(name)
    assert len(by_precision) == 1, f"inconsistent money precision: {by_precision}"
    assert next(iter(by_precision)) == (18, 2)


def test_search_index_has_a_gin_index_on_the_tsvector():
    table = Base.metadata.tables["search_index"]
    gin_indexes = [
        index
        for index in table.indexes
        if index.dialect_options.get("postgresql", {}).get("using") == "gin"
    ]
    assert gin_indexes, "search_index has no GIN index; full-text search would seq-scan"
    covered = {column.name for index in gin_indexes for column in index.columns}
    assert "search_vector" in covered


def test_spec_tables_have_a_unique_version_per_pump_model():
    """Two rows at the same version would make history ambiguous."""
    for table_name in (
        "technical_specs",
        "commercial_specs",
        "dimensional_specs",
        "delivery_specs",
        "operational_specs",
        "administrative_specs",
    ):
        table = Base.metadata.tables[table_name]
        unique_sets = [
            {column.name for column in constraint.columns}
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        assert {
            "pump_model_id",
            "version",
        } in unique_sets, f"{table_name} allows duplicate versions for one pump model"


def test_audit_log_is_append_only_shaped(ddl: str):
    """A bigint identity key, indexed by time - the shape partitioning later needs."""
    table = Base.metadata.tables["audit_logs"]
    assert table.columns["id"].primary_key
    assert "BIGSERIAL" in ddl or "BIGINT" in ddl.upper()
    indexed_columns = {column.name for index in table.indexes for column in index.columns}
    assert "occurred_at" in indexed_columns


def test_all_orm_mappers_configure():
    """Catches relationship errors that table metadata alone cannot.

    `Tenant.permissions` was ambiguous because `tenant_permissions` carries two foreign
    keys to `tenants`. Nothing in the table metadata is wrong, so this only surfaced when
    SQLAlchemy configured the mappers at first ORM use. Configuring them here moves that
    failure into the test suite.
    """
    from sqlalchemy.orm import configure_mappers

    import app.models  # noqa: F401 - registers every mapper

    configure_mappers()


def test_relationships_with_multiple_fk_paths_declare_foreign_keys():
    """Any relationship between two tables joined by more than one FK must be explicit."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.orm import configure_mappers

    import app.models  # noqa: F401

    configure_mappers()
    ambiguous = []
    for mapper in Base.registry.mappers:
        for relationship in mapper.relationships:
            target = relationship.target
            paths = [
                fk
                for column in mapper.local_table.columns
                for fk in column.foreign_keys
                if fk.column.table is target
            ]
            if len(paths) > 1 and not relationship._user_defined_foreign_keys:
                # SQLAlchemy resolved it, but the intent is implicit; make it explicit.
                ambiguous.append(f"{sa_inspect(mapper.class_).class_.__name__}.{relationship.key}")
    assert not ambiguous, f"relationships with an implicit FK choice: {ambiguous}"
