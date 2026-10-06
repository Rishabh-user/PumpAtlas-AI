"""Seed the roles, and in development a demo tenant.

Idempotent: running it twice changes nothing. Safe to run as a Compose one-shot on every
deploy.

    python -m scripts.seed

No administrator is created here. It used to be, from `FIRST_ADMIN_EMAIL` and
`FIRST_ADMIN_PASSWORD` in `.env`, which put the live login for the most privileged
account in a configuration file - defaulting to a password published in this repository.
Create it explicitly instead, and type the password rather than storing it:

    python -m scripts.manage_user create --email you@targeticon.com \
        --name "Your Name" --platform-admin

The demo tenant's users are for development only and get a generated password, printed
once by this script.
"""

from __future__ import annotations

import secrets
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.core.logging import configure_logging, get_logger
from app.core.rbac import permissions_for
from app.core.security import hash_password
from app.models.enums import TenantPlan, TenantStatus, UserRoleName
from app.models.tenant import Tenant
from app.models.user import Role, User

configure_logging(settings.LOG_LEVEL, json_logs=False)
log = get_logger(__name__)

ROLE_DEFINITIONS: list[tuple[UserRoleName, str, str, bool]] = [
    (
        UserRoleName.ADMIN,
        "Administrator",
        "Full control of the tenant: users, data, ingestion and governance.",
        False,
    ),
    (
        UserRoleName.RESEARCH_ANALYST,
        "Research analyst",
        "Runs ingestion and AI review; curates vendor and pump records.",
        False,
    ),
    (
        UserRoleName.PROCUREMENT,
        "Procurement",
        "Owns commercial and delivery data, comparisons and award recommendations.",
        False,
    ),
    (
        UserRoleName.ENGINEERING,
        "Engineering",
        "Owns technical specifications and technical-fit approval.",
        False,
    ),
    (
        UserRoleName.VENDOR_MANAGER,
        "Vendor manager",
        "Owns vendor qualification, approval status and governance data.",
        False,
    ),
    (
        UserRoleName.CLIENT_USER,
        "Client user",
        "Read-only access to technical intelligence; commercial terms are hidden.",
        False,
    ),
]


def seed_roles(db) -> int:
    created = 0
    for name, display_name, description, is_platform in ROLE_DEFINITIONS:
        role = db.scalar(select(Role).where(Role.name == name))
        permissions = permissions_for(name)
        if role is None:
            db.add(
                Role(
                    name=name,
                    display_name=display_name,
                    description=description,
                    is_platform_role=is_platform,
                    permissions=permissions,
                )
            )
            created += 1
        else:
            # Keep the stored matrix in step with app.core.rbac.
            role.display_name = display_name
            role.description = description
            role.permissions = permissions
    db.flush()
    return created


def platform_admin_count(db) -> int:
    """How many platform administrators exist, so the seeder can say what is missing.

    It no longer creates one: a password typed into a prompt cannot come from a seeder
    that runs unattended on every deploy.
    """
    return len(
        db.scalars(
            select(User).where(User.is_platform_admin.is_(True), User.deleted_at.is_(None))
        ).all()
    )


def seed_demo_tenant(db) -> tuple[Tenant | None, str | None]:
    """The development tenant and the password its accounts were given, if created."""
    if settings.is_production:
        return None, None

    tenant = db.scalar(select(Tenant).where(Tenant.slug == "demo-operator"))
    if tenant is not None:
        # Already seeded, so nothing to report: the passwords were printed then.
        return tenant, None

    tenant = Tenant(
        slug="demo-operator",
        name="Demo Offshore Operator",
        legal_name="Demo Offshore Operator Ltd",
        country="GB",
        industry_segment="Upstream FPSO operator",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.PROFESSIONAL,
        can_use_shared_master=True,
        can_contribute_shared_master=False,
        max_users=25,
        primary_contact_email="procurement@demo-operator.example",
        settings={
            "units": "metric",
            "default_currency": "USD",
            "scorecard_weights": {
                "technical": 0.40,
                "commercial": 0.25,
                "delivery": 0.20,
                "data_confidence": 0.15,
            },
        },
    )
    db.add(tenant)
    db.flush()

    roles = {role.name: role for role in db.scalars(select(Role)).all()}
    # One generated password for the five demo accounts, returned so `main` can print it
    # once. These are `.example` addresses on a tenant that is never seeded in
    # production; a real account is created with `scripts.manage_user`.
    demo_password = secrets.token_urlsafe(18)
    demo_users = [
        ("admin@demo-operator.example", "Dana Whitfield", "Procurement lead", [UserRoleName.ADMIN]),
        (
            "analyst@demo-operator.example",
            "Ravi Menon",
            "Research analyst",
            [UserRoleName.RESEARCH_ANALYST],
        ),
        (
            "engineer@demo-operator.example",
            "Ingrid Solheim",
            "Rotating equipment engineer",
            [UserRoleName.ENGINEERING],
        ),
        (
            "buyer@demo-operator.example",
            "Tomás Ferreira",
            "Category buyer",
            [UserRoleName.PROCUREMENT],
        ),
        (
            "vendors@demo-operator.example",
            "Amina Diallo",
            "Vendor manager",
            [UserRoleName.VENDOR_MANAGER],
        ),
    ]
    for email, full_name, job_title, role_names in demo_users:
        user = User(
            tenant_id=tenant.id,
            email=email,
            full_name=full_name,
            job_title=job_title,
            hashed_password=hash_password(demo_password),
            password_changed_at=datetime.now(UTC),
        )
        for role_name in role_names:
            role = roles.get(role_name)
            if role is not None:
                user.roles.append(role)
        db.add(user)

    db.flush()
    log.info("seed.demo_tenant_created", tenant_id=str(tenant.id), users=len(demo_users))
    tenant.settings = {**(tenant.settings or {}), "seeded_demo_users": len(demo_users)}
    return tenant, demo_password


def main() -> int:
    # Seeding writes across tenant boundaries, so it runs in platform-admin context.
    with tenant_session(None, is_platform_admin=True) as db:
        roles_created = seed_roles(db)
        admins = platform_admin_count(db)
        tenant, demo_password = seed_demo_tenant(db)
        tenant_label = f"{tenant.name} ({tenant.slug})" if tenant is not None else None

    print("Seed complete.")
    print(f"  roles created:     {roles_created}")
    print(f"  platform admins:   {admins}")
    if tenant_label:
        print(f"  demo tenant:       {tenant_label}")
    if demo_password:
        print(
            "  demo users:        admin@ / analyst@ / engineer@ / buyer@ / vendors@"
            "demo-operator.example"
        )
        print(f"  demo password:     {demo_password}")
        print("  Shown once, and only for the demo tenant.")
    if not admins:
        print()
        print("  No platform administrator exists yet, so nobody can sign in. Create one:")
        print("    python -m scripts.manage_user create --email you@example.com \\")
        print('        --name "Your Name" --platform-admin')
        print("  The password is typed at a prompt; only its hash is stored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
