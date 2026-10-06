"""Create login accounts, and change their passwords, in the database.

Accounts used to come from the environment: `FIRST_ADMIN_EMAIL` and
`FIRST_ADMIN_PASSWORD` sat in `.env`, and the seeder hashed whatever it found there into
a platform administrator. That is a poor place for a credential. It is readable by
anything that can read the file or the process environment, it is copied into every
backup and deployment dashboard, it is the same value on every machine that shares the
file, and it cannot be rotated without editing configuration and re-running a seeder.
Worse, it defaulted to a password published in this repository, so an installation that
never edited `.env` shipped with a known administrator login.

A login belongs in the users table, where it can be rotated, audited and revoked. This
script is how one gets there.

    python -m scripts.manage_user list
    python -m scripts.manage_user create --email you@targeticon.com \\
        --name "Your Name" --platform-admin
    python -m scripts.manage_user set-password --email you@targeticon.com

The password is never taken as a command-line argument. An argument is visible in shell
history and, on most systems, to anyone who can run `ps` while the command runs. It is
read from a prompt with no echo, confirmed by retyping, and never logged or printed.
`--random` generates one instead and prints it once - for setting up somebody else's
account, where you need a value to hand over.

Roles come from the `roles` table, so `python -m scripts.seed` must have run first.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import string
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.models.enums import AuditAction, UserRoleName
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.audit import record_audit

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

#: Long enough that a bcrypt hash is not worth grinding at. Not a complexity rule:
#: length is what actually helps, and character-class rules mostly produce "Passw0rd!".
MIN_PASSWORD_CHARS = 12

#: Passwords this repository or its docs have ever suggested. Refused outright: the
#: whole point of moving off `.env` is that this one was the live administrator login.
KNOWN_DEFAULTS = frozenset({"changeme!123", "changeme", "password", "admin", "pumpatlas"})

ROLE_CHOICES = tuple(role.value for role in UserRoleName)


def read_new_password(*, random: bool) -> tuple[str, bool]:
    """The password to store. Returns ``(password, was_generated)``.

    Generated passwords are printed by the caller, once. Typed ones are never printed,
    never echoed while typing, and confirmed by retyping - a typo in a password nobody
    can see would otherwise lock the account out silently.
    """
    if random:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
        return "".join(secrets.choice(alphabet) for _ in range(24)), True

    if not sys.stdin.isatty():
        # A pipe cannot be prompted twice, so accept one line from it. Useful for
        # automation; still keeps the value out of argv.
        piped = sys.stdin.readline().rstrip("\n")
        _check_password(piped)
        return piped, False

    while True:
        first = getpass.getpass("New password (not shown): ")
        try:
            _check_password(first)
        except ValueError as exc:
            print(f"  {exc}")
            continue
        if first != getpass.getpass("Confirm password: "):
            print("  The two entries differ. Try again.")
            continue
        return first, False


def _check_password(password: str) -> None:
    # The default is checked first on purpose: answering "too short" to someone who typed
    # a known default sends them to "changeme!1234", which is no better.
    if password.strip().lower() in KNOWN_DEFAULTS:
        raise ValueError("That is a documented default password. Choose another.")
    if len(password) < MIN_PASSWORD_CHARS:
        raise ValueError(f"Too short - use at least {MIN_PASSWORD_CHARS} characters.")


def resolve_tenant(db, slug: str | None, platform_admin: bool) -> Tenant | None:
    """Which tenant the account belongs to, or None for a platform administrator.

    A platform administrator carries a null tenant, which is also how row level security
    recognises one - so the two options are mutually exclusive rather than merely
    unusual together.
    """
    if platform_admin and slug:
        raise SystemExit(
            "A platform administrator belongs to no tenant. Pass --platform-admin or "
            "--tenant, not both."
        )
    if platform_admin:
        return None
    if not slug:
        raise SystemExit(
            "Say where the account belongs: --tenant <slug> for a client user, or "
            "--platform-admin for a Targeticon operator. Run `list` to see the tenants."
        )
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise SystemExit(f"No tenant with slug {slug!r}. Run `list` to see them.")
    return tenant


def resolve_roles(db, names: list[str]) -> list[Role]:
    """Role rows for the given names, refusing any that is not seeded.

    Silently dropping an unknown role would create an account that can log in and do
    nothing, which reads as a broken deployment rather than a typo.
    """
    if not names:
        return []
    roles = {role.name: role for role in db.scalars(select(Role)).all()}
    missing = [name for name in names if name not in roles]
    if missing:
        raise SystemExit(
            f"Unknown role(s): {', '.join(missing)}. Known: {', '.join(sorted(roles))}. "
            "If that list is empty, run `python -m scripts.seed` first."
        )
    return [roles[name] for name in names]


def cmd_create(args) -> int:
    with tenant_session(None, is_platform_admin=True) as db:
        email = args.email.strip().lower()
        if db.scalar(select(User).where(User.email == email)) is not None:
            raise SystemExit(
                f"{email} already exists. Use `set-password --email {email}` to change "
                "its password."
            )

        tenant = resolve_tenant(db, args.tenant, args.platform_admin)
        # A platform administrator with no role can sign in and see nothing, which
        # reads as a broken install rather than a missing flag.
        wanted = args.role or ([UserRoleName.ADMIN.value] if args.platform_admin else [])
        roles = resolve_roles(db, wanted)
        password, generated = read_new_password(random=args.random)

        user = User(
            tenant_id=tenant.id if tenant else None,
            email=email,
            full_name=args.name,
            job_title=args.job_title,
            hashed_password=hash_password(password),
            is_platform_admin=args.platform_admin,
            password_changed_at=datetime.now(UTC),
        )
        user.roles.extend(roles)
        db.add(user)
        db.flush()

        record_audit(
            db,
            action=AuditAction.CREATE,
            entity_type="users",
            entity_id=user.id,
            entity_label=email,
            summary="Login account created from the command line",
            tenant_id=user.tenant_id,
            context={
                "platform_admin": args.platform_admin,
                "roles": [role.name for role in roles],
                # Who ran it, as far as the machine knows. Not authentication - it is a
                # note for whoever reads the trail later.
                "created_by_os_user": getpass.getuser(),
            },
            actor_type="system",
        )

        print(f"Created {email}")
        print(f"  tenant:          {tenant.slug if tenant else 'none (platform admin)'}")
        print(f"  platform admin:  {'yes' if args.platform_admin else 'no'}")
        print(f"  roles:           {', '.join(role.name for role in roles) or 'none'}")
        if generated:
            print(f"  password:        {password}")
            print("  Shown once. Hand it over out of band and have it changed on first use.")
        else:
            print("  password:        set from your input, not recorded anywhere")
    return 0


def cmd_set_password(args) -> int:
    with tenant_session(None, is_platform_admin=True) as db:
        email = args.email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            raise SystemExit(f"No account with email {email!r}. Run `list` to see them.")

        password, generated = read_new_password(random=args.random)
        user.hashed_password = hash_password(password)
        user.password_changed_at = datetime.now(UTC)
        # A password change is also the way out of a lockout, so clear it.
        user.failed_login_count = 0
        user.locked_until = None
        db.flush()

        record_audit(
            db,
            action=AuditAction.UPDATE,
            entity_type="users",
            entity_id=user.id,
            entity_label=email,
            summary="Password changed from the command line",
            tenant_id=user.tenant_id,
            context={"changed_by_os_user": getpass.getuser()},
            actor_type="system",
        )

        print(f"Password changed for {email}")
        if generated:
            print(f"  password:        {password}")
            print("  Shown once.")
    return 0


def cmd_list(args) -> int:
    del args
    with tenant_session(None, is_platform_admin=True) as db:
        tenants = {tenant.id: tenant.slug for tenant in db.scalars(select(Tenant)).all()}
        users = db.scalars(select(User).order_by(User.email)).all()

        print(f"{len(users)} account(s)\n")
        for user in users:
            where = tenants.get(user.tenant_id, "platform") if user.tenant_id else "platform"
            flags = []
            if user.is_platform_admin:
                flags.append("platform-admin")
            if not user.is_active:
                flags.append("inactive")
            if user.deleted_at is not None:
                flags.append("deleted")
            if user.locked_until:
                flags.append(f"locked until {user.locked_until:%Y-%m-%d %H:%M}")
            last = f"{user.last_login_at:%Y-%m-%d}" if user.last_login_at else "never"
            print(f"  {user.email}")
            print(
                f"      {where} | roles: {', '.join(r.name for r in user.roles) or 'none'}"
                f" | last login: {last}" + (f" | {', '.join(flags)}" if flags else "")
            )

        if tenants:
            print(f"\ntenants: {', '.join(sorted(tenants.values()))}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.manage_user",
        description="Create login accounts and change their passwords.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a login account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True, help="full name, shown in the app header")
    create.add_argument("--job-title", default=None)
    create.add_argument("--tenant", default=None, help="tenant slug, for a client user")
    create.add_argument(
        "--platform-admin",
        action="store_true",
        help="a Targeticon operator: no tenant, sees shared master data",
    )
    create.add_argument(
        "--role",
        action="append",
        choices=ROLE_CHOICES,
        help="repeatable; defaults to admin for a platform administrator",
    )
    create.add_argument(
        "--random",
        action="store_true",
        help="generate the password and print it once, instead of prompting",
    )
    create.set_defaults(func=cmd_create)

    change = sub.add_parser("set-password", help="change an existing account's password")
    change.add_argument("--email", required=True)
    change.add_argument("--random", action="store_true", help="generate and print once")
    change.set_defaults(func=cmd_set_password)

    listing = sub.add_parser("list", help="show accounts and tenants")
    listing.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
