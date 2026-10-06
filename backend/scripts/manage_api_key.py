"""Issue, list and revoke the machine credentials another application uses.

    python -m scripts.manage_api_key list
    python -m scripts.manage_api_key create --name "Portal (read only)" --read-only
    python -m scripts.manage_api_key create --name Portal --scopes vendor:read,pump:read
    python -m scripts.manage_api_key revoke --prefix pa_1c4f9a2b

A key is printed **once**, at creation, and only its hash is stored - there is no command
that shows it again, because the database does not hold it. If it is lost, revoke it and
issue another.

Which tenant a key belongs to decides what it can see, and this is the part worth getting
right before handing one over:

* ``--tenant <uuid>`` binds the key to one client. It sees that client's records plus the
  shared master catalogue, exactly as a user of that client does.
* ``--shared-only`` issues a key with no tenant. It sees the shared master catalogue and
  nothing belonging to any client - the right choice for a public-facing site or a
  demo, because there is no way for it to read a client's private data even if the
  application asks for it.

Scopes are what the key may do, checked on every request by `Principal.can`. Read-only is
the default and the recommended setting for another application that displays this data:
a key that can only read cannot be used to change a record, whatever a bug at the far end
does with it.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.core.security import new_api_key
from app.models.tenant import Tenant
from app.models.user import ApiKey

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

#: What another application needs to show vendors, pumps and the chat answer.
READ_ONLY_SCOPES = [
    "vendor:read",
    "pump:read",
    "search:read",
    "data_quality:read",
]

#: Scopes that let a key change the record. Never part of `--read-only`, and worth a
#: deliberate decision every time: a key is a password that lives in another codebase.
WRITE_SCOPES = ["vendor:write", "pump:write"]


def _tenant_label(db, tenant_id: uuid.UUID | None) -> str:
    if tenant_id is None:
        return "shared master only"
    tenant = db.get(Tenant, tenant_id)
    return tenant.name if tenant else f"unknown tenant {tenant_id}"


def cmd_list(db, args) -> int:
    keys = db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
    if not keys:
        print("No API keys issued.")
        return 0
    now = datetime.now(UTC)
    print(f"{len(keys)} key(s):\n")
    for key in keys:
        state = "active"
        if not key.is_active:
            state = "revoked"
        elif key.expires_at is not None and key.expires_at <= now:
            state = f"expired {key.expires_at.date()}"
        elif key.expires_at is not None:
            state = f"expires {key.expires_at.date()}"
        used = (
            key.last_used_at.strftime("%Y-%m-%d %H:%M") if key.last_used_at else "never used"
        )
        print(f"   {key.prefix}…  {key.name[:34]:34} {state:22} {used}")
        scope_text = ", ".join(key.scopes or []) or "none"
        print(f"      {_tenant_label(db, key.tenant_id)} · scopes: {scope_text}")
    return 0


def cmd_create(db, args) -> int:
    if args.shared_only and args.tenant:
        print(
            "Choose one: --tenant binds the key to a client, --shared-only to none.",
            file=sys.stderr,
        )
        return 2
    if not args.shared_only and not args.tenant:
        print(
            "Say which data this key may read: --tenant <uuid> for one client's records, "
            "or --shared-only for the shared master catalogue.\n"
            "Tenants:",
            file=sys.stderr,
        )
        for tenant in db.scalars(select(Tenant).order_by(Tenant.name)).all():
            print(f"   {tenant.id}  {tenant.name}", file=sys.stderr)
        return 2

    tenant_id = uuid.UUID(args.tenant) if args.tenant else None
    if tenant_id is not None and db.get(Tenant, tenant_id) is None:
        print(f"No tenant {tenant_id}", file=sys.stderr)
        return 2

    if args.read_only:
        scopes = list(READ_ONLY_SCOPES)
    elif args.scopes:
        scopes = [scope.strip() for scope in args.scopes.split(",") if scope.strip()]
    else:
        print("Pass --read-only, or --scopes with an explicit list.", file=sys.stderr)
        return 2

    unknown = [s for s in scopes if ":" not in s and s != "*"]
    if unknown:
        print(f"Not scope-shaped (resource:action): {', '.join(unknown)}", file=sys.stderr)
        return 2
    if "*" in scopes:
        print("Refusing to issue a wildcard key: name the scopes it needs.", file=sys.stderr)
        return 2

    raw, hashed = new_api_key()
    key = ApiKey(
        tenant_id=tenant_id,
        name=args.name,
        prefix=raw[:11],
        hashed_key=hashed,
        scopes=scopes,
        expires_at=(
            datetime.now(UTC) + timedelta(days=args.expires_in_days)
            if args.expires_in_days
            else None
        ),
    )
    db.add(key)
    if args.commit:
        db.commit()
    else:
        db.rollback()

    print(f"\n{'ISSUED' if args.commit else 'DRY RUN - not saved'}: {args.name}")
    print(f"   sees   : {_tenant_label(db, tenant_id)}")
    print(f"   scopes : {', '.join(scopes)}")
    print(f"   expires: {key.expires_at.date() if key.expires_at else 'never'}")
    if args.commit:
        print(
            "\n   Send this to the other application. It is not stored and "
            "cannot be shown again:\n"
        )
        print(f"      {raw}\n")
        print("   Used as a header on every request:\n")
        print(f"      X-API-Key: {raw}\n")
    else:
        print("\n   Re-run with --commit to issue it.")
    return 0


def cmd_revoke(db, args) -> int:
    key = db.scalar(select(ApiKey).where(ApiKey.prefix == args.prefix))
    if key is None:
        print(f"No key with prefix {args.prefix}", file=sys.stderr)
        return 2
    if not key.is_active:
        print(f"{key.name} was already revoked.")
        return 0
    key.is_active = False
    if args.commit:
        db.commit()
        print(f"Revoked {key.name}. Requests using it now fail with 401.")
    else:
        db.rollback()
        print(f"Would revoke {key.name}. Re-run with --commit.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="apply; otherwise a dry run")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="every key, with what it can see and when it was last used")

    create = sub.add_parser("create", help="issue a key")
    create.add_argument("--name", required=True, help="who it is for, e.g. 'Portal (read only)'")
    create.add_argument("--tenant", help="tenant uuid this key acts for")
    create.add_argument(
        "--shared-only", action="store_true", help="no tenant: shared master catalogue only"
    )
    create.add_argument(
        "--read-only", action="store_true", help="read scopes for vendors, pumps and chat"
    )
    create.add_argument(
        "--scopes", help="explicit comma-separated list, e.g. vendor:read,pump:read"
    )
    create.add_argument(
        "--expires-in-days", type=int, help="expiry; omit for a key that never expires"
    )

    revoke = sub.add_parser("revoke", help="turn a key off")
    revoke.add_argument("--prefix", required=True, help="the pa_… prefix shown by `list`")

    args = parser.parse_args()
    handlers = {"list": cmd_list, "create": cmd_create, "revoke": cmd_revoke}

    with tenant_session(None, is_platform_admin=True) as db:
        return handlers[args.command](db, args)


if __name__ == "__main__":
    raise SystemExit(main())
