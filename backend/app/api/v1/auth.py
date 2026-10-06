"""Authentication, session and API key endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.db import set_tenant_guc
from app.core.deps import CurrentPrincipal, DbSession
from app.core.rbac import permissions_for
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_api_key,
    verify_password,
)
from app.models.enums import AuditAction, UserRoleName
from app.models.user import ApiKey, User
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    CurrentUser,
    LoginRequest,
    PasswordChange,
    RefreshRequest,
    TokenPair,
)
from app.schemas.common import Message
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenPair:
    """Exchange credentials for an access + refresh token pair."""
    # Reading users before a principal exists requires platform context.
    set_tenant_guc(db, None, is_platform_admin=True)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    def _reject(reason: str) -> HTTPException:
        record_audit(
            db,
            action=AuditAction.LOGIN_FAILED,
            entity_type="users",
            entity_id=user.id if user else None,
            entity_label=payload.email,
            summary=reason,
            tenant_id=user.tenant_id if user else None,
            ip_address=client_ip,
            user_agent=user_agent,
            http_method="POST",
            http_path="/auth/login",
            status_code=401,
            actor_type="user",
        )
        db.commit()
        # Deliberately identical message for every failure mode.
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    if user is None or user.deleted_at is not None:
        raise _reject("unknown email")
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account locked until {user.locked_until.isoformat()} after repeated failures",
        )
    if not user.is_active:
        raise _reject("inactive user")
    if not verify_password(payload.password, user.hashed_password):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)
        raise _reject("bad password")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)

    tokens = TokenPair(
        access_token=create_access_token(
            str(user.id),
            str(user.tenant_id) if user.tenant_id else None,
            user.role_names,
            user.is_platform_admin,
        ),
        refresh_token=create_refresh_token(str(user.id)),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    record_audit(
        db,
        action=AuditAction.LOGIN,
        entity_type="users",
        entity_id=user.id,
        entity_label=user.email,
        summary="Successful login",
        tenant_id=user.tenant_id,
        ip_address=client_ip,
        user_agent=user_agent,
        http_method="POST",
        http_path="/auth/login",
        status_code=200,
    )
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc

    set_tenant_guc(db, None, is_platform_admin=True)
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is no longer active")

    return TokenPair(
        access_token=create_access_token(
            str(user.id),
            str(user.tenant_id) if user.tenant_id else None,
            user.role_names,
            user.is_platform_admin,
        ),
        refresh_token=create_refresh_token(str(user.id)),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/identity")
def identity(principal: CurrentPrincipal, db: DbSession) -> dict:
    """Who this request is, whatever kind of credential it carries.

    `GET /me` answers for a signed-in person and refuses an API key, which is correct -
    a key has no profile, no email and no roles. But an integration needs *some* call
    that answers "is this key live, what can it see, what may it do", and the first thing
    a developer at the other end reaches for is the endpoint that 400s at them.

    Everything here is already known to the caller: they sent the key. Nothing secret is
    returned - not the key, not its hash, not the tenant's name.
    """
    key: ApiKey | None = None
    if principal.api_key_id is not None:
        key = db.get(ApiKey, principal.api_key_id)

    return {
        "actor_type": principal.actor_type,
        "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
        # What "no tenant" means differs by caller, and getting it wrong is the difference
        # between an empty screen and someone else's data.
        "sees": (
            "shared master catalogue only"
            if principal.tenant_id is None and not principal.is_platform_admin
            else "every tenant"
            if principal.is_platform_admin and not principal.scoped_to_tenant
            else "this tenant and the shared master catalogue"
        ),
        "scopes": list(principal.scopes),
        "roles": list(principal.roles),
        "email": principal.email,
        "key": (
            {
                "name": key.name,
                "prefix": key.prefix,
                "expires_at": key.expires_at,
                "last_used_at": key.last_used_at,
            }
            if key is not None
            else None
        ),
    }


@router.get("/me", response_model=CurrentUser)
def me(principal: CurrentPrincipal, db: DbSession) -> CurrentUser:
    """The signed-in user, their tenant and their effective permissions."""
    if principal.user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "API keys have no user profile")
    # One query for the user, their roles and their tenant. Fetching the user, then
    # lazy-loading roles, then fetching the tenant is three round trips, and this runs
    # on every page in the app: the navigation shell asks who is signed in each time.
    user = db.scalar(
        select(User)
        .options(joinedload(User.roles), joinedload(User.tenant))
        .where(User.id == principal.user_id)
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    tenant = user.tenant
    permissions: dict[str, list[str]] = {}
    for role in user.roles:
        for resource, actions in permissions_for(role.name).items():
            permissions.setdefault(resource, [])
            permissions[resource] = sorted(set(permissions[resource]) | set(actions))
    if user.is_platform_admin:
        permissions["*"] = ["read", "write", "delete", "approve", "export"]

    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        mfa_enabled=user.mfa_enabled,
        roles=user.roles,
        tenant_name=tenant.name if tenant else None,
        tenant_slug=tenant.slug if tenant else None,
        permissions=permissions,
    )


@router.post("/logout", response_model=Message)
def logout(principal: CurrentPrincipal, db: DbSession) -> Message:
    """Records the event. Tokens are stateless, so clients must discard them."""
    record_audit(
        db,
        action=AuditAction.LOGOUT,
        principal=principal,
        entity_type="users",
        entity_id=principal.user_id,
        entity_label=principal.email,
        summary="Logout",
    )
    db.commit()
    return Message(detail="Signed out. Discard the stored tokens.")


@router.post("/change-password", response_model=Message)
def change_password(payload: PasswordChange, principal: CurrentPrincipal, db: DbSession) -> Message:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "API keys have no password")
    user = db.get(User, principal.user_id)
    if user is None or not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the old")

    user.hashed_password = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(UTC)
    record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="users",
        entity_id=user.id,
        entity_label=user.email,
        summary="Password changed",
    )
    db.commit()
    return Message(detail="Password updated")


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(principal: CurrentPrincipal, db: DbSession) -> list[ApiKey]:
    if not principal.can("user", "read"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator only")
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.tenant_id == principal.tenant_id)
            .order_by(ApiKey.created_at.desc())
        ).all()
    )


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyCreate, principal: CurrentPrincipal, db: DbSession
) -> ApiKeyCreated:
    """Issue a machine credential. The plaintext key is returned exactly once."""
    if not principal.can("user", "write"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator only")

    raw, hashed = new_api_key()
    key = ApiKey(
        tenant_id=principal.tenant_id,
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
    record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="api_keys",
        entity_label=payload.name,
        summary=f"API key issued with scopes {payload.scopes}",
    )
    db.commit()
    db.refresh(key)
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        is_active=key.is_active,
        api_key=raw,
    )


@router.delete("/api-keys/{key_id}", response_model=Message)
def revoke_api_key(key_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Message:
    if not principal.can("user", "write"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator only")
    key = db.get(ApiKey, key_id)
    if key is None or key.tenant_id != principal.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.is_active = False
    record_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        principal=principal,
        entity_type="api_keys",
        entity_id=key.id,
        entity_label=key.name,
        summary="API key revoked",
    )
    db.commit()
    return Message(detail="API key revoked")


# Roles are seeded from the RBAC matrix, so the constant is re-exported for the UI.
ROLE_CHOICES = [role.value for role in UserRoleName]
