"""Report what the models expect and the database does not have.

An unapplied migration does not announce itself. The chat history tables sat missing
for as long as they were missing: `/chat/conversations` 500'd, the sidebar rendered the
same "no conversations yet" it shows a new account, and `record_api_ask` caught its own
exception so API questions were never logged either. Three layers of best-effort
handling, and nothing that said *the table is not there*.

This compares every table and column the SQLAlchemy models declare against
`information_schema`, so a migration that was written but never run shows up as a list
of missing objects rather than as puzzling behaviour weeks later.

Read-only. Run it after pulling, and after applying a migration to confirm it took.
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from app.core.db import tenant_session
from app.models import Base


def main() -> int:
    with tenant_session(None, is_platform_admin=True) as db:
        present = {
            r["table_name"]: set()
            for r in db.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).mappings()
        }
        for r in db.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )
        ).mappings():
            if r["table_name"] in present:
                present[r["table_name"]].add(r["column_name"])

        missing_tables: list[str] = []
        missing_columns: list[tuple[str, list[str]]] = []

        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                missing_tables.append(table.name)
                continue
            absent = [c.name for c in table.columns if c.name not in present[table.name]]
            if absent:
                missing_columns.append((table.name, absent))

        inspector = inspect(db.get_bind())
        print(f"models declare {len(Base.metadata.sorted_tables)} tables; ", end="")
        print(f"database has {len(inspector.get_table_names())}")
        print()

        if missing_tables:
            print("MISSING TABLES - a migration was written but never applied:")
            for name in missing_tables:
                print(f"   {name}")
            print()
        if missing_columns:
            print("MISSING COLUMNS:")
            for name, cols in missing_columns:
                print(f"   {name}: {', '.join(cols)}")
            print()
        if not missing_tables and not missing_columns:
            print("No drift. Every mapped table and column exists.")
            return 0

        print("Apply the matching migration as the schema OWNER, from the repo root:")
        print(
            "   python scripts/apply_schema.py "
            "--url <owner-dsn> --file db/migrations/<file>.sql"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
