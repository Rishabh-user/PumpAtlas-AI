"""Generate ``db/schema.sql`` from the SQLAlchemy models.

The models are the single definition of the schema; this script renders them as
PostgreSQL DDL so the SQL file and the ORM can never drift. Run it after any model
change:

    python scripts/gen_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Base  # noqa: E402
from sqlalchemy import Index  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

DIALECT = postgresql.dialect()

HEADER = """-- =====================================================================
-- PumpAtlas AI - Oil & Gas Pump Intelligence Platform
-- Canonical PostgreSQL schema
--
-- GENERATED FILE - do not edit by hand.
-- Source of truth: backend/app/models/*.py
-- Regenerate with:  python scripts/gen_schema.py
--
-- Apply order:
--   1. db/extensions.sql   (pgcrypto, pg_trgm, btree_gin, unaccent)
--   2. db/schema.sql       (this file)
--   3. db/functions.sql    (search vector, versioning, provenance triggers)
--   4. db/rls.sql          (row level security policies)
--   5. db/partitions.sql   (optional: audit_logs monthly partitioning)
--
-- Then seed roles, the demo tenant and the bootstrap admin:
--   cd backend && python -m scripts.seed
-- =====================================================================

SET client_min_messages = warning;
"""


def render() -> str:
    out: list[str] = [HEADER]

    # --- enum types -------------------------------------------------------
    seen: set[str] = set()
    enum_ddl: list[str] = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            enum_type = getattr(column.type, "enums", None)
            name = getattr(column.type, "name", None)
            if enum_type is None or not name or name in seen:
                continue
            seen.add(name)
            values = ",\n    ".join(f"'{v}'" for v in enum_type)
            enum_ddl.append(f"CREATE TYPE {name} AS ENUM (\n    {values}\n);")

    out.append("\n-- ---------- enum types ----------\n")
    out.append("\n\n".join(sorted(enum_ddl)))

    # --- tables -----------------------------------------------------------
    out.append("\n\n-- ---------- tables ----------\n")
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=DIALECT)).strip()
        out.append(f"{ddl};\n")
        comments = [
            f"COMMENT ON COLUMN {table.name}.{c.name} IS "
            f"'{c.comment.replace(chr(39), chr(39) * 2)}';"
            for c in table.columns
            if c.comment
        ]
        if table.comment:
            comments.insert(
                0,
                f"COMMENT ON TABLE {table.name} IS "
                f"'{table.comment.replace(chr(39), chr(39) * 2)}';",
            )
        if comments:
            out.append("\n".join(comments) + "\n")

    # --- indexes ----------------------------------------------------------
    out.append("\n-- ---------- indexes ----------\n")
    index_ddl: list[str] = []
    for table in Base.metadata.sorted_tables:
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            assert isinstance(index, Index)
            index_ddl.append(str(CreateIndex(index).compile(dialect=DIALECT)).strip() + ";")
    out.append("\n".join(index_ddl))

    out.append("\n")
    return "\n".join(out)


def main() -> None:
    target = ROOT / "db" / "schema.sql"
    target.write_text(render(), encoding="utf-8")
    tables = len(Base.metadata.tables)
    columns = sum(len(t.columns) for t in Base.metadata.tables.values())
    indexes = sum(len(t.indexes) for t in Base.metadata.tables.values())
    print(f"wrote {target.relative_to(ROOT)}")
    print(f"  tables:  {tables}")
    print(f"  columns: {columns}")
    print(f"  indexes: {indexes}")


if __name__ == "__main__":
    main()
