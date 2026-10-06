"""Read-only database browser for platform staff.

Useful for the thing no purpose-built screen covers: confirming what is actually stored
after an import, an AI promotion or a migration. Deliberately narrow, because a table
browser in a multi-tenant system is the one page that can leak everything at once.

What it will not do, and why:

* **No SQL from the caller.** Not a text box, not a WHERE clause, not an ORDER BY
  expression. There is no safe way to accept SQL from a browser, and "admin only" is not
  an answer - it turns one stolen session into arbitrary read access over every tenant.
* **No writes.** Correcting a record goes through the service layer, so it lands in a
  version row with provenance and an audit entry. A direct UPDATE here would silently
  produce a value with no source, which is the one thing this platform promises never to
  hold.
* **Table names are matched against the live catalogue** before they reach a query, and
  quoted by SQLAlchemy's identifier preparer. An identifier cannot be parameterised, so
  validating against ``information_schema`` is what makes interpolation safe.
* **Secrets are replaced, not selected.** Password hashes, MFA secrets and API key
  hashes are dropped at the SQL level, so they never enter the process. The column is
  still listed - hiding its existence would be more confusing than showing it is
  withheld.

Row-level security still applies: the app connects as a NOBYPASSRLS role. But platform
staff run with ``app.is_platform_admin`` on, which is what lets them see across tenants
by design - so this page shows every tenant's rows, and says so.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from app.core.deps import DbSession, PlatformAdmin
from app.core.logging import get_logger
from app.models.enums import AuditAction
from app.services import audit

log = get_logger(__name__)

router = APIRouter(prefix="/admin/database", tags=["admin"])

#: Columns whose values must never leave the database, by ``table.column``.
#:
#: Named explicitly rather than matched by pattern: a regex over "hash", "token" or
#: "secret" also catches ``prompt_tokens``, ``content_hash`` and ``password_changed_at``,
#: which are ordinary data and useful to see. A denylist that hides useful columns gets
#: worked around; this one should not need to be.
REDACTED_COLUMNS: frozenset[str] = frozenset(
    {
        "users.hashed_password",
        "users.mfa_secret",
        "api_keys.hashed_key",
        # Ciphertext, but still a secret: a page that can display any table must not
        # become the way an encrypted provider key is read out and taken offline.
        "ai_provider_configs.encrypted_api_key",
    }
)

REDACTION_MARKER = "[withheld]"

#: A page of rows. Small because the database is remote and rows here are wide - the
#: technical specification table alone has 161 columns.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _tables(db: DbSession) -> dict[str, int]:
    """Every base table in the public schema, with an estimated row count.

    One statement. Counting exactly would mean ``count(*)`` per table - 36 round trips
    at roughly a third of a second each just to draw a list - so the listing uses
    PostgreSQL's own estimate and the detail view counts for real.
    """
    rows = db.execute(
        text("""
            SELECT c.relname AS table_name,
                   GREATEST(c.reltuples, 0)::bigint AS estimate
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname
        """)
    ).all()
    return {row.table_name: int(row.estimate) for row in rows}


def _columns(db: DbSession, table: str) -> list[dict[str, Any]]:
    """Column metadata for one table, in declaration order."""
    rows = db.execute(
        text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t
            ORDER BY ordinal_position
        """),
        {"t": table},
    ).all()
    return [
        {
            "name": row.column_name,
            "data_type": row.data_type,
            "nullable": row.is_nullable == "YES",
            "redacted": f"{table}.{row.column_name}" in REDACTED_COLUMNS,
        }
        for row in rows
    ]


def _resolve_table(db: DbSession, table: str) -> str:
    """The real table name, or a 404.

    The returned value comes from the catalogue rather than from the request, so what
    reaches the query is never caller-supplied text.
    """
    known = _tables(db)
    if table not in known:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No table named {table!r} in the public schema.",
        )
    return next(name for name in known if name == table)


@router.get("/tables")
def list_tables(principal: PlatformAdmin, db: DbSession) -> dict[str, Any]:
    """Every table, with an estimated row count and how many columns it has."""
    estimates = _tables(db)
    counts = db.execute(
        text("""
            SELECT table_name, count(*)::int AS columns
            FROM information_schema.columns
            WHERE table_schema = 'public'
            GROUP BY table_name
        """)
    ).all()
    columns_by_table = {row.table_name: row.columns for row in counts}

    return {
        "tables": [
            {
                "name": name,
                "estimated_rows": estimate,
                "columns": columns_by_table.get(name, 0),
                "has_redacted_columns": any(
                    entry.startswith(f"{name}.") for entry in REDACTED_COLUMNS
                ),
            }
            for name, estimate in estimates.items()
        ],
        "row_counts_are_estimates": True,
        "scope": "every tenant - platform staff see across tenant boundaries",
    }


@router.get("/tables/{table}")
def read_table(
    table: str,
    principal: PlatformAdmin,
    db: DbSession,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """One page of rows from one table, with its column metadata.

    Ordered by primary key where the table has a single-column one, so paging is stable;
    otherwise unordered, and the response says so rather than implying an order the
    database does not guarantee.
    """
    name = _resolve_table(db, table)
    columns = _columns(db, name)
    if not columns:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Table {name!r} has no columns")

    preparer = db.bind.dialect.identifier_preparer
    quoted_table = preparer.quote(name)

    # Redacted columns are replaced in the SELECT list, so the value is never read out
    # of the database at all rather than being filtered out afterwards.
    projection = ", ".join(
        f"{REDACTION_MARKER!r} AS {preparer.quote(column['name'])}"
        if column["redacted"]
        else preparer.quote(column["name"])
        for column in columns
    )

    order_by = ""
    primary_key = db.execute(
        text("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = to_regclass(:qualified) AND i.indisprimary
        """),
        {"qualified": f"public.{name}"},
    ).all()
    if len(primary_key) == 1:
        order_by = f" ORDER BY {preparer.quote(primary_key[0].attname)}"

    total = db.execute(text(f"SELECT count(*) FROM {quoted_table}")).scalar() or 0
    rows = db.execute(
        text(f"SELECT {projection} FROM {quoted_table}{order_by} LIMIT :lim OFFSET :off"),
        {"lim": limit, "off": offset},
    ).mappings()

    # Every value is stringified: a page of JSONB, arrays, enums, dates and Decimals has
    # no single JSON representation, and this view exists to be *read*, not parsed.
    items = [
        {key: (None if value is None else str(value)) for key, value in row.items()} for row in rows
    ]

    # Reading raw tables is exactly what "read_sensitive" is for. Recorded per request,
    # including which table and how much was read.
    audit.record_audit(
        db,
        action=AuditAction.READ_SENSITIVE,
        principal=principal,
        entity_type=name,
        summary=f"Browsed {len(items)} row(s) of {name} in the admin database viewer",
        context={"table": name, "limit": limit, "offset": offset},
        tenant_id=principal.tenant_id,
    )
    db.commit()

    return {
        "table": name,
        "columns": columns,
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "ordered_by": primary_key[0].attname if len(primary_key) == 1 else None,
        "redacted_columns": sorted(column["name"] for column in columns if column["redacted"]),
    }
