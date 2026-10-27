"""Make `is_shared_master` agree with who owns the row.

Row level security decides what a tenant can see from `tenant_id`: a row with no tenant
is shared master, and every tenant entitled to the shared catalogue can read it. That
part works. The `is_shared_master` *column* is a second, denormalised copy of the same
fact, and it was never written - 55 vendors and 45 pump models have `tenant_id IS NULL`
and the flag set to false.

`search.apply_filters` reads the column, not the ownership, so both shared-master
filters were silently wrong in opposite directions:

* ``only_shared_master=True`` becomes ``WHERE is_shared_master IS true`` and matched
  nothing, anywhere. The shared-master-only view could not return a row.
* ``include_shared_master=False`` becomes ``WHERE is_shared_master IS false`` and
  matched *everything*, so asking to exclude shared master excluded nothing.

Neither failed loudly. Both returned a plausible list.

This backfills the flag from the ownership that RLS already enforces, and reports what
it changed. `--commit` writes; without it the script only counts, which is how it
should be read first.

The repair is one UPDATE per table, driven entirely by `tenant_id`, so it cannot
promote a tenant's row to shared master or demote a shared row: it copies a fact that
is already true rather than deciding a new one.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from app.core.db import tenant_session

#: Every table carrying the denormalised flag, and whether it is soft-deleted.
TABLES = {
    "vendors": True,
    "pump_models": True,
    "pumps": True,
    "search_index": False,
}


def _counts(db, table: str, soft_deleted: bool) -> dict[str, int]:
    alive = " AND deleted_at IS NULL" if soft_deleted else ""
    return dict(
        db.execute(
            text(
                f"""
                SELECT
                  count(*) FILTER (
                    WHERE tenant_id IS NULL AND NOT is_shared_master
                  ) AS wrongly_false,
                  count(*) FILTER (
                    WHERE tenant_id IS NOT NULL AND is_shared_master
                  ) AS wrongly_true,
                  count(*) FILTER (WHERE tenant_id IS NULL) AS shared,
                  count(*) AS total
                FROM {table}
                WHERE true{alive}
                """
            )
        )
        .mappings()
        .one()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="write the change; without it, only report what would change",
    )
    args = parser.parse_args()

    with tenant_session(None, is_platform_admin=True) as db:
        print(f"{'table':16} {'rows':>7} {'shared':>7} {'flag wrong':>11}")
        print("-" * 46)
        before = {}
        for table, soft_deleted in TABLES.items():
            c = _counts(db, table, soft_deleted)
            before[table] = c
            wrong = c["wrongly_false"] + c["wrongly_true"]
            print(
                f"{table:16} {c['total']:7} {c['shared']:7} {wrong:11}"
                + ("" if wrong else "   (already correct)")
            )

        total_wrong = sum(
            c["wrongly_false"] + c["wrongly_true"] for c in before.values()
        )
        if not total_wrong:
            print("\nNothing to repair.")
            return 0

        if not args.commit:
            print(f"\n{total_wrong} rows disagree with their ownership.")
            print("Re-run with --commit to write the correction.")
            return 0

        print()
        for table, soft_deleted in TABLES.items():
            alive = " AND deleted_at IS NULL" if soft_deleted else ""
            result = db.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET is_shared_master = (tenant_id IS NULL)
                    WHERE is_shared_master IS DISTINCT FROM (tenant_id IS NULL){alive}
                    """
                )
            )
            print(f"  {table:16} {result.rowcount:5} rows corrected")
        db.commit()

        print()
        for table, soft_deleted in TABLES.items():
            c = _counts(db, table, soft_deleted)
            wrong = c["wrongly_false"] + c["wrongly_true"]
            status = "OK" if not wrong else f"STILL WRONG: {wrong}"
            print(f"  {table:16} shared={c['shared']:5}  {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
