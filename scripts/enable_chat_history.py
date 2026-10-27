"""Create the chat history tables. Run once, as the database owner.

The chat saves nothing because `chat_conversations` and `chat_turns` do not exist:
migrations 004 and 005 were written but never applied. The application cannot create
them - `pumpatlas_app` has no CREATE on the schema or the database, is not a superuser
and is not a member of the owner role, which is exactly the lockdown that stops an AI
run from altering the schema. Only the owner, `pumpatlas_ai_user`, can.

So this asks for the owner connection string, applies the two migrations in order, and
checks the result. It exists because the alternative is two long command lines with a
password in each, in the right order, with `--reset` close enough to mistype - and
`--reset` drops the public schema and everything in it.

    python scripts/enable_chat_history.py

The URL is read with `getpass`, so it is not echoed to the screen and does not reach
your shell history. Nothing here is destructive: both migrations are `IF NOT EXISTS`
throughout and safe to run twice.

Get the URL from the Render dashboard: your database, Connect, External Database URL.
It starts `postgresql://pumpatlas_ai_user:`.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path
from urllib.parse import urlparse

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    ROOT / "db/migrations/004_chat_conversations.sql",
    ROOT / "db/migrations/005_chat_conversations_api_key_source.sql",
)
WANTED = ("chat_conversations", "chat_turns")


def normalise(url: str) -> str:
    """psycopg wants a plain libpq URL, not SQLAlchemy's driver-qualified scheme."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def present(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (list(WANTED),),
        )
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    for path in MIGRATIONS:
        if not path.exists():
            print(f"Missing migration file: {path}")
            return 1

    print(__doc__.strip().splitlines()[0])
    print()
    # An environment variable for a non-interactive run (CI, or a shell where the
    # prompt cannot reach the console); otherwise ask, without echoing.
    url = os.environ.get("PUMPATLAS_OWNER_URL", "").strip()
    if url:
        print("Using PUMPATLAS_OWNER_URL from the environment.")
    else:
        try:
            url = getpass("Owner database URL (input hidden): ").strip()
        except (EOFError, OSError):
            print(
                "No console to prompt on. Set PUMPATLAS_OWNER_URL and run again:\n"
                '  export PUMPATLAS_OWNER_URL="postgresql://pumpatlas_ai_user:...@host/db"'
            )
            return 1
    if not url:
        print("Nothing entered. Stopping.")
        return 1

    url = normalise(url)
    parsed = urlparse(url)
    print(f"\nConnecting to {parsed.username}@{parsed.hostname}{parsed.path}")

    try:
        conn = psycopg.connect(url, connect_timeout=15)
    except Exception as exc:
        print(f"Could not connect: {exc}")
        return 1

    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, has_schema_privilege(current_user,'public','CREATE')")
            role, can_create = cur.fetchone()
        print(f"Connected as {role}; can create tables: {can_create}")
        if not can_create:
            print(
                "\nThis role cannot create tables, so it is not the owner. Use the "
                "External Database URL from Render, which connects as the database's "
                "owning user."
            )
            return 1

        already = present(conn)
        if already:
            print(f"Already present: {', '.join(sorted(already))}")

        for path in MIGRATIONS:
            print(f"\nApplying {path.name} ...")
            sql = path.read_text(encoding="utf-8")
            # One transaction per file, sent whole: these contain dollar-quoted DO
            # blocks that splitting on ';' would corrupt.
            with conn.cursor() as cur:
                cur.execute(sql)  # type: ignore[arg-type]
            conn.commit()
            print(f"  {path.name} applied.")

        created = present(conn)

    print()
    for name in WANTED:
        print(f"  {name:22} {'present' if name in created else 'STILL MISSING'}")

    if set(WANTED) <= created:
        print("\nChat history is enabled. Reload /chat - the 'history is unavailable'")
        print("notice will be gone and conversations will persist from now on.")
        print("Questions asked before this point were never stored and cannot be")
        print("recovered; the history starts here.")
        return 0

    print("\nSomething did not take. Run `python -m scripts.check_schema_drift` from")
    print("backend/ and send me the output.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
