"""Apply the SQL files to any PostgreSQL, including a managed one.

A container reads ``db/*.sql`` from ``docker-entrypoint-initdb.d`` on first start.
A managed database (Render, RDS, Cloud SQL, Neon) has no such hook, and you may not have
``psql`` installed, so this applies the same files over a normal connection in the same
order.

    # from the app's own configuration
    python scripts/apply_schema.py

    # or against an explicit URL
    python scripts/apply_schema.py --url "postgresql://user:pw@host/db?sslmode=require"

    # set the application role's password at the same time
    python scripts/apply_schema.py --app-password "$(openssl rand -hex 24)"

Safety: it refuses to touch a database that already has tables unless you pass
``--skip-schema`` (re-apply only the idempotent files) or ``--reset`` (drop everything
first). ``--reset`` is destructive and prints exactly what it will do before acting.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

# Order matters: extensions define functions the schema and triggers rely on, and RLS
# policies reference the helper functions created alongside them.
FILES = [
    ("db/extensions.sql", "extensions and the text-search configuration", True),
    ("db/schema.sql", "tables, enums and indexes", False),
    ("db/functions.sql", "triggers and helper functions", True),
    ("db/rls.sql", "row level security policies", True),
    ("db/app_role.sql", "the NOBYPASSRLS application role", True),
]


def normalise(url: str) -> str:
    """psycopg wants a plain libpq URL, not SQLAlchemy's driver-qualified scheme."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def safe_target(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.username}@{parsed.hostname}:{parsed.port or 5432}{parsed.path}"


def existing_tables(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        return int(cur.fetchone()[0])


def describe_role(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname = current_user"
        )
        user, superuser, bypassrls = cur.fetchone()
        cur.execute("SELECT current_setting('server_version')")
        version = cur.fetchone()[0]
    return {
        "user": user,
        "superuser": superuser,
        "bypassrls": bypassrls,
        "server_version": version,
    }


def apply_file(conn: psycopg.Connection, path: Path) -> None:
    """Execute a whole file in one transaction.

    Sent as a single script rather than split on ';': these files contain
    dollar-quoted DO blocks and function bodies that naive splitting would corrupt.
    One transaction per file means a failure leaves nothing half-applied.
    """
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)  # type: ignore[arg-type]
    conn.commit()


def reset_public_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
        cur.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    conn.commit()


def set_app_password(conn: psycopg.Connection, password: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'pumpatlas_app'")
        if cur.fetchone() is None:
            print("  ! pumpatlas_app does not exist; skipping the password change")
            return
        # ALTER ROLE is a utility statement and does not accept bind parameters, so the
        # password has to be composed in. psycopg's Literal does the quoting and
        # escaping; never build this string with f-strings or %.
        cur.execute(
            sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                sql.Identifier("pumpatlas_app"), sql.Literal(password)
            )
        )
    conn.commit()
    print("  set the pumpatlas_app password")


def verify(conn: psycopg.Connection) -> dict:
    """Read back what actually landed, rather than trusting that it did."""
    queries = {
        "tables": "SELECT count(*) FROM pg_tables WHERE schemaname='public'",
        "columns": "SELECT count(*) FROM information_schema.columns WHERE table_schema='public'",
        "indexes": "SELECT count(*) FROM pg_indexes WHERE schemaname='public'",
        "enum_types": (
            "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
            "WHERE t.typtype='e' AND n.nspname='public'"
        ),
        "rls_enabled": (
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relrowsecurity AND n.nspname='public'"
        ),
        "rls_forced": (
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relforcerowsecurity AND n.nspname='public'"
        ),
        "policies": "SELECT count(*) FROM pg_policies WHERE schemaname='public'",
        "triggers": (
            "SELECT count(DISTINCT trigger_name) FROM information_schema.triggers "
            "WHERE trigger_schema='public'"
        ),
    }
    out: dict[str, object] = {}
    with conn.cursor() as cur:
        for label, query in queries.items():
            cur.execute(query)
            out[label] = int(cur.fetchone()[0])
        cur.execute("SELECT string_agg(extname, ', ' ORDER BY extname) FROM pg_extension")
        out["extensions"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_ts_config WHERE cfgname='pumpatlas'")
        out["text_search_config"] = "present" if cur.fetchone()[0] else "MISSING"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="database URL; defaults to the app's configuration")
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="re-apply only the idempotent files, leaving existing tables alone",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DESTRUCTIVE: drop the public schema and everything in it first",
    )
    parser.add_argument("--app-password", help="set the pumpatlas_app role's password")
    parser.add_argument(
        "--file",
        help=(
            "apply one SQL file instead of the full set - for an incremental migration "
            "from db/migrations/ against a database that already has tables"
        ),
    )
    args = parser.parse_args()

    if args.url:
        url = normalise(args.url)
    else:
        from app.core.config import settings

        url = normalise(settings.sqlalchemy_url)

    print(f"target: {safe_target(url)}")

    with psycopg.connect(url, connect_timeout=30, autocommit=False) as conn:
        role = describe_role(conn)
        print(f"server: PostgreSQL {role['server_version']}")
        print(
            f"role  : {role['user']} (superuser={role['superuser']}, "
            f"bypassrls={role['bypassrls']})"
        )
        if role["superuser"] or role["bypassrls"]:
            print("  ! This role bypasses row level security. Applying the schema is fine,")
            print("  ! but the application must NOT connect as it, or tenant isolation")
            print("  ! will be silently inert. Use the pumpatlas_app role instead.")

        # A single file, for an incremental change. Skips the "refusing to continue"
        # guard below, which exists to stop the *full* schema being replayed over live
        # data - not to stop one migration being applied to it.
        if args.file:
            path = pathlib.Path(args.file)
            if not path.is_absolute():
                path = ROOT / args.file
            if not path.exists():
                print(f"\nNo such file: {path}")
                return 1
            try:
                apply_file(conn, path)
            except psycopg.Error as exc:
                conn.rollback()
                print(f"\nFAILED  {path.name}: {str(exc).splitlines()[0]}")
                return 1
            print(f"\napplied {path.name}")
            for key, value in verify(conn).items():
                print(f"  {key:22s} {value}")
            return 0

        present = existing_tables(conn)
        if args.reset:
            print(f"\n--reset: dropping the public schema ({present} tables) ...")
            reset_public_schema(conn)
            present = 0
        elif present and not args.skip_schema:
            print(f"\nRefusing to continue: {present} tables already exist in public.")
            print("  --skip-schema  re-apply extensions, functions, RLS and the app role")
            print("  --reset        drop everything and rebuild (destroys all data)")
            return 1

        print()
        for relative, description, idempotent in FILES:
            path = ROOT / relative
            if not path.exists():
                print(f"  skip {relative} (not present)")
                continue
            if relative == "db/schema.sql" and args.skip_schema:
                print(f"  skip {relative} (--skip-schema)")
                continue
            try:
                apply_file(conn, path)
                print(f"  applied {relative:22s} {description}")
            except psycopg.Error as exc:
                conn.rollback()
                first_line = str(exc).splitlines()[0]
                if idempotent:
                    print(f"  warn    {relative:22s} {first_line[:80]}")
                    continue
                print(f"  FAILED  {relative:22s} {first_line}")
                return 1

        if args.app_password:
            set_app_password(conn, args.app_password)

        print("\nverification:")
        for key, value in verify(conn).items():
            print(f"  {key:20s} {value}")

    print("\nNext: seed roles and the first administrator")
    print("  cd backend && python -m scripts.seed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
