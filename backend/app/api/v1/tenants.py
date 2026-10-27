"""Tenant management (platform admin) and tenant self-service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentPrincipal, DbSession, PlatformAdmin, require
from app.core.rbac import permissions_for
from app.core.security import hash_password, new_api_key
from app.models.ai import AiJob, DataQualityFlag
from app.models.enums import AuditAction, UserRoleName
from app.models.pump import PumpModel
from app.models.source import Document, Source
from app.models.tenant import Tenant, TenantPermission
from app.models.user import ApiKey, Role, User
from app.models.vendor import Vendor
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import Message, Page
from app.schemas.tenant import (
    TenantCreate,
    TenantOut,
    TenantPermissionIn,
    TenantPermissionOut,
    TenantStats,
    TenantUpdate,
)
from app.services import audit

router = APIRouter(tags=["tenants"])


def _counts_by_tenant(db: DbSession, model, *conditions) -> dict:
    """One grouped query for every tenant, rather than one query per row.

    The list renders a users, vendors, pump-models and storage column for each client.
    Asking `/tenants/{id}` per row would be four counts times however many customers
    there are, against a database 300ms away - and the page would still be wrong while
    it waited. Grouped, the whole table costs four queries whatever the customer count.
    """
    rows = db.execute(
        select(model.tenant_id, func.count())
        .where(model.tenant_id.is_not(None), *conditions)
        .group_by(model.tenant_id)
    ).all()
    return {tenant_id: int(count) for tenant_id, count in rows}


@router.get("/tenants", response_model=Page[TenantStats])
def list_tenants(
    _: PlatformAdmin,
    db: DbSession,
    status_filter: list[str] = Query(default_factory=list, alias="status"),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """All client companies. Platform administrators only."""
    stmt = select(Tenant).where(Tenant.deleted_at.is_(None))
    if status_filter:
        stmt = stmt.where(Tenant.status.in_(status_filter))
    if q:
        stmt = stmt.where(Tenant.name.ilike(f"%{q}%") | Tenant.slug.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Tenant.name).limit(limit).offset(offset)).all()

    # The columns the page actually renders. Without these every usage cell showed an
    # em dash, which reads as "nothing here" rather than "nobody asked".
    users = _counts_by_tenant(db, User, User.deleted_at.is_(None))
    vendors = _counts_by_tenant(db, Vendor, Vendor.deleted_at.is_(None))
    models = _counts_by_tenant(db, PumpModel, PumpModel.deleted_at.is_(None))
    storage = {
        tenant_id: int(total_bytes or 0)
        for tenant_id, total_bytes in db.execute(
            select(Document.tenant_id, func.coalesce(func.sum(Document.size_bytes), 0))
            .where(Document.tenant_id.is_not(None))
            .group_by(Document.tenant_id)
        ).all()
    }

    # The shared master catalogue: owned by nobody, readable by every tenant whose
    # entitlement allows it. Counted once for the page, not once per tenant.
    shared_vendors = int(
        db.scalar(
            select(func.count())
            .select_from(Vendor)
            .where(Vendor.tenant_id.is_(None), Vendor.deleted_at.is_(None))
        )
        or 0
    )
    shared_models = int(
        db.scalar(
            select(func.count())
            .select_from(PumpModel)
            .where(PumpModel.tenant_id.is_(None), PumpModel.deleted_at.is_(None))
        )
        or 0
    )

    items = []
    for tenant in rows:
        stats = TenantStats.model_validate(tenant)
        stats.user_count = users.get(tenant.id, 0)
        stats.vendor_count = vendors.get(tenant.id, 0)
        stats.pump_model_count = models.get(tenant.id, 0)
        stats.shared_vendor_count = shared_vendors if tenant.can_use_shared_master else 0
        stats.shared_pump_model_count = shared_models if tenant.can_use_shared_master else 0
        stats.visible_vendor_count = stats.vendor_count + stats.shared_vendor_count
        stats.visible_pump_model_count = (
            stats.pump_model_count + stats.shared_pump_model_count
        )
        stats.storage_used_mb = round(storage.get(tenant.id, 0) / 1_048_576, 2)
        items.append(stats)
    return Page[TenantStats](items=items, total=int(total), limit=limit, offset=offset)


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate, principal: PlatformAdmin, db: DbSession) -> Tenant:
    """Provision a client company, optionally with its first administrator."""
    if db.scalar(select(Tenant).where(Tenant.slug == payload.slug)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Slug '{payload.slug}' is taken")

    tenant = Tenant(
        slug=payload.slug,
        name=payload.name,
        legal_name=payload.legal_name,
        country=payload.country,
        industry_segment=payload.industry_segment,
        plan=payload.plan,
        primary_contact_email=payload.primary_contact_email,
        can_use_shared_master=payload.can_use_shared_master,
        can_contribute_shared_master=payload.can_contribute_shared_master,
        max_users=payload.max_users,
    )
    db.add(tenant)
    db.flush()

    if payload.admin_email:
        if db.scalar(select(User).where(User.email == payload.admin_email.lower())) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"User {payload.admin_email} already exists"
            )
        admin_role = db.scalar(select(Role).where(Role.name == UserRoleName.ADMIN))
        admin = User(
            tenant_id=tenant.id,
            email=payload.admin_email.lower(),
            full_name=payload.admin_full_name or payload.admin_email,
            hashed_password=hash_password(payload.admin_password or ""),
            job_title="Tenant administrator",
        )
        if admin_role is not None:
            admin.roles.append(admin_role)
        db.add(admin)

    audit.record_audit(
        db,
        action=AuditAction.TENANT_CHANGE,
        principal=principal,
        entity_type="tenants",
        entity_id=tenant.id,
        entity_label=tenant.name,
        summary=f"Tenant provisioned on the {tenant.plan} plan",
        tenant_id=tenant.id,
    )
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/tenants/{tenant_id}", response_model=TenantStats)
def get_tenant(tenant_id: uuid.UUID, _: PlatformAdmin, db: DbSession) -> TenantStats:
    """Tenant record plus usage counters."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    def _count(model, *conditions) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

    from datetime import UTC, datetime, timedelta

    since = datetime.now(UTC) - timedelta(days=30)
    storage_bytes = (
        db.scalar(
            select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                Document.tenant_id == tenant_id
            )
        )
        or 0
    )

    stats = TenantStats.model_validate(tenant)
    stats.user_count = _count(User, User.tenant_id == tenant_id, User.deleted_at.is_(None))
    stats.vendor_count = _count(Vendor, Vendor.tenant_id == tenant_id, Vendor.deleted_at.is_(None))
    stats.pump_model_count = _count(
        PumpModel, PumpModel.tenant_id == tenant_id, PumpModel.deleted_at.is_(None)
    )
    stats.source_count = _count(Source, Source.tenant_id == tenant_id)
    stats.ai_jobs_last_30d = _count(AiJob, AiJob.tenant_id == tenant_id, AiJob.created_at >= since)
    stats.storage_used_mb = round(int(storage_bytes) / 1_048_576, 2)
    stats.open_flag_count = _count(
        DataQualityFlag,
        DataQualityFlag.tenant_id == tenant_id,
        DataQualityFlag.is_resolved.is_(False),
    )
    return stats


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: uuid.UUID, payload: TenantUpdate, principal: PlatformAdmin, db: DbSession
) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    before = audit.snapshot(tenant)
    for field_name, value in payload.model_dump(exclude_none=True).items():
        setattr(tenant, field_name, value)

    audit.record_audit(
        db,
        action=AuditAction.TENANT_CHANGE,
        principal=principal,
        entity_type="tenants",
        entity_id=tenant.id,
        entity_label=tenant.name,
        summary="Tenant updated",
        changes=audit.diff(before, audit.snapshot(tenant)),
        tenant_id=tenant.id,
    )
    db.commit()
    db.refresh(tenant)
    return tenant


@router.delete("/tenants/{tenant_id}", response_model=Message)
def suspend_tenant(tenant_id: uuid.UUID, principal: PlatformAdmin, db: DbSession) -> Message:
    """Suspends rather than deletes. Client data is retained for the contract term."""
    from app.models.enums import TenantStatus

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    tenant.status = TenantStatus.SUSPENDED
    for user in db.scalars(select(User).where(User.tenant_id == tenant_id)).all():
        user.is_active = False

    audit.record_audit(
        db,
        action=AuditAction.TENANT_CHANGE,
        principal=principal,
        entity_type="tenants",
        entity_id=tenant.id,
        entity_label=tenant.name,
        summary="Tenant suspended and all its users deactivated",
        tenant_id=tenant.id,
    )
    db.commit()
    return Message(
        detail=f"Tenant {tenant.name} suspended. Data is retained; users can no longer sign in."
    )


@router.get("/tenants/{tenant_id}/api-keys", response_model=list[ApiKeyOut])
def list_tenant_api_keys(
    tenant_id: uuid.UUID, _: PlatformAdmin, db: DbSession
) -> list[ApiKey]:
    """The keys issued to one client.

    `GET /auth/api-keys` lists the *caller's* keys, so platform staff see the ones
    belonging to nobody and never a client's. Without this there is no way to answer
    "what does this customer hold" short of a SQL prompt, which is how a key nobody
    remembers issuing stays active.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.tenant_id == tenant_id)
            .order_by(ApiKey.created_at.desc())
        ).all()
    )


@router.delete("/tenants/{tenant_id}/api-keys/{key_id}", response_model=Message)
def revoke_tenant_api_key(
    tenant_id: uuid.UUID, key_id: uuid.UUID, principal: PlatformAdmin, db: DbSession
) -> Message:
    """Revoke one of this client's keys. Deactivates rather than deletes, so the audit
    trail of it having existed and been used survives."""
    key = db.get(ApiKey, key_id)
    if key is None or key.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.is_active = False
    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="api_keys",
        entity_id=key.id,
        entity_label=key.name,
        summary="API key revoked",
        tenant_id=tenant_id,
    )
    db.commit()
    return Message(detail=f"Key {key.name} revoked. It will be refused immediately.")


@router.post(
    "/tenants/{tenant_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
def issue_tenant_api_key(
    tenant_id: uuid.UUID,
    payload: ApiKeyCreate,
    principal: PlatformAdmin,
    db: DbSession,
) -> ApiKeyCreated:
    """Issue a machine credential **for this client**. The key is shown once.

    `POST /auth/api-keys` binds a key to the *caller's* tenant, which is right for a
    client administrator issuing their own and wrong for platform staff onboarding
    somebody: a platform admin has no tenant, so it produces a key belonging to nobody
    that reads only the shared master catalogue. One such key is already in this
    database. Naming the tenant in the path removes the ambiguity.

    The key carries the tenant for its whole life. Row level security does the rest -
    a request authenticated with it sees that client's records plus whatever shared
    master data their entitlement allows, and nothing else.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    raw, hashed = new_api_key()
    key = ApiKey(
        tenant_id=tenant.id,
        created_by_user_id=principal.user_id,
        name=payload.name,
        prefix=raw[:11],
        hashed_key=hashed,
        scopes=payload.scopes,
        expires_at=(
            datetime.now(UTC) + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days
            else None
        ),
    )
    db.add(key)
    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="api_keys",
        entity_id=key.id,
        entity_label=key.name,
        summary=f"API key issued to {tenant.name}",
        tenant_id=tenant.id,
        context={"scopes": payload.scopes, "expires_at": str(key.expires_at)},
    )
    db.commit()
    db.refresh(key)
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), api_key=raw)


@router.get("/tenants/{tenant_id}/permissions", response_model=list[TenantPermissionOut])
def list_tenant_permissions(tenant_id: uuid.UUID, _: PlatformAdmin, db: DbSession) -> list:
    return list(
        db.scalars(select(TenantPermission).where(TenantPermission.tenant_id == tenant_id)).all()
    )


@router.post(
    "/tenants/{tenant_id}/permissions",
    response_model=TenantPermissionOut,
    status_code=status.HTTP_201_CREATED,
)
def grant_tenant_permission(
    tenant_id: uuid.UUID,
    payload: TenantPermissionIn,
    principal: PlatformAdmin,
    db: DbSession,
) -> TenantPermission:
    """Grant a feature entitlement, or share this tenant's data with another tenant."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    if payload.shared_with_tenant_id:
        if payload.shared_with_tenant_id == tenant_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A tenant cannot be granted access to itself"
            )
        if db.get(Tenant, payload.shared_with_tenant_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Target tenant not found")

    permission = TenantPermission(
        tenant_id=tenant_id,
        granted_by_user_id=principal.user_id,
        **payload.model_dump(),
    )
    db.add(permission)
    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="tenant_permissions",
        entity_label=f"{payload.resource}:{payload.action}",
        summary=(
            f"Granted {payload.resource}:{payload.action}"
            + (
                f" to tenant {payload.shared_with_tenant_id}"
                if payload.shared_with_tenant_id
                else ""
            )
        ),
        tenant_id=tenant_id,
    )
    db.commit()
    db.refresh(permission)
    return permission


@router.delete("/tenants/{tenant_id}/permissions/{permission_id}", response_model=Message)
def revoke_tenant_permission(
    tenant_id: uuid.UUID,
    permission_id: uuid.UUID,
    principal: PlatformAdmin,
    db: DbSession,
) -> Message:
    permission = db.get(TenantPermission, permission_id)
    if permission is None or permission.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission grant not found")
    db.delete(permission)
    audit.record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="tenant_permissions",
        entity_id=permission_id,
        summary=f"Revoked {permission.resource}:{permission.action}",
        tenant_id=tenant_id,
    )
    db.commit()
    return Message(detail="Permission revoked")


# Not /tenants/me/... - that would be swallowed by /tenants/{tenant_id}.
@router.get(
    "/my-tenant", response_model=TenantOut, dependencies=[Depends(require("tenant", "read"))]
)
def my_tenant(principal: CurrentPrincipal, db: DbSession) -> Tenant:
    """A tenant administrator reading their own organisation."""
    tenant = db.get(Tenant, principal.require_tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return tenant


# ---------------------------------------------------------------------------
# Users, scoped to the caller's tenant unless the caller is platform staff
# ---------------------------------------------------------------------------


@router.get("/users", response_model=Page[UserOut], dependencies=[Depends(require("user", "read"))])
def list_users(
    principal: CurrentPrincipal,
    db: DbSession,
    tenant_id: uuid.UUID | None = Query(default=None, description="Platform admins only"),
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    scope = tenant_id if (tenant_id and principal.is_platform_admin) else principal.tenant_id
    stmt = select(User).where(User.deleted_at.is_(None), User.tenant_id == scope)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.full_name).limit(limit).offset(offset)).all()
    return Page[UserOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("user", "write"))],
)
def create_user(payload: UserCreate, principal: CurrentPrincipal, db: DbSession) -> User:
    """Invite a user into a tenant and assign roles."""
    if payload.is_platform_admin and not principal.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only platform admins can create platform admins"
        )
    tenant_id = (
        payload.tenant_id
        if (payload.tenant_id and principal.is_platform_admin)
        else principal.tenant_id
    )
    if tenant_id is None and not payload.is_platform_admin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A tenant is required for non-platform users"
        )

    if db.scalar(select(User).where(User.email == payload.email.lower())) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{payload.email} is already registered")

    if tenant_id is not None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
        current = (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
            )
            or 0
        )
        if current >= tenant.max_users:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Tenant seat limit reached ({tenant.max_users}). Raise max_users first.",
            )

    unknown = [name for name in payload.roles if name not in {r.value for r in UserRoleName}]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown role(s): {', '.join(unknown)}. Allowed: "
            f"{', '.join(r.value for r in UserRoleName)}",
        )

    user = User(
        tenant_id=tenant_id,
        email=payload.email.lower(),
        full_name=payload.full_name,
        job_title=payload.job_title,
        hashed_password=hash_password(payload.password),
        is_platform_admin=payload.is_platform_admin,
    )
    for role in db.scalars(select(Role).where(Role.name.in_(payload.roles))).all():
        user.roles.append(role)
    db.add(user)

    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="users",
        entity_label=user.email,
        summary=f"User created with roles {payload.roles}",
        tenant_id=tenant_id,
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch(
    "/users/{user_id}", response_model=UserOut, dependencies=[Depends(require("user", "write"))]
)
def update_user(
    user_id: uuid.UUID, payload: UserUpdate, principal: CurrentPrincipal, db: DbSession
) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.tenant_id != principal.tenant_id and not principal.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User belongs to another tenant")

    before = audit.snapshot(user)
    values = payload.model_dump(exclude_none=True)
    roles = values.pop("roles", None)
    for field_name, value in values.items():
        setattr(user, field_name, value)
    if roles is not None:
        user.roles = list(db.scalars(select(Role).where(Role.name.in_(roles))).all())

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="users",
        entity_id=user.id,
        entity_label=user.email,
        summary="User updated",
        changes=audit.diff(before, audit.snapshot(user)),
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/roles", dependencies=[Depends(require("user", "read"))])
def list_roles(db: DbSession) -> list[dict]:
    """Roles with the resource/action matrix each one grants."""
    rows = db.scalars(select(Role).order_by(Role.name)).all()
    return [
        {
            "id": str(role.id),
            "name": role.name.value,
            "display_name": role.display_name,
            "description": role.description,
            "is_platform_role": role.is_platform_role,
            "permissions": role.permissions or permissions_for(role.name),
        }
        for role in rows
    ]
