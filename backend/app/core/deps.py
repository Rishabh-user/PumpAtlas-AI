"""FastAPI dependencies: DB session, current principal, tenant scope, RBAC guards."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core import rbac
from app.core.db import SessionLocal, set_tenant_guc
from app.core.logging import get_logger, tenant_id_ctx, user_id_ctx
from app.core.security import decode_token, verify_api_key
from app.models.user import ApiKey, User

log = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Whoever is making the request: a user, or an API key acting for a tenant."""

    user_id: uuid.UUID | None
    tenant_id: uuid.UUID | None
    roles: list[str]
    is_platform_admin: bool
    email: str | None = None
    api_key_id: uuid.UUID | None = None
    actor_type: str = "user"
    scopes: list[str] = field(default_factory=list)
    # True when platform staff narrowed themselves to one tenant with X-Tenant-Id.
    # Their RBAC powers are unchanged; only the visible data narrows.
    scoped_to_tenant: bool = False

    def can(self, resource: str, action: str) -> bool:
        if self.is_platform_admin:
            return True
        if self.actor_type == "api_key":
            return f"{resource}:{action}" in self.scopes or "*" in self.scopes
        return rbac.is_allowed(self.roles, resource, action)

    @property
    def require_tenant_id(self) -> uuid.UUID:
        if self.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This endpoint is tenant scoped. Platform staff must pass "
                    "X-Tenant-Id to act inside a tenant."
                ),
            )
        return self.tenant_id


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def _principal_from_jwt(token: str, db: Session) -> Principal:
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    user_id = uuid.UUID(payload["sub"])
    # RLS is not yet bound to a tenant, so read the user as platform context.
    set_tenant_guc(db, None, is_platform_admin=True)
    # Roles come back in the same statement; the default selectin strategy would add
    # another round trip to every authenticated request.
    user = db.scalar(select(User).options(joinedload(User.roles)).where(User.id == user_id))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is not active")

    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        roles=user.role_names,
        is_platform_admin=user.is_platform_admin,
        email=user.email,
        actor_type="user",
    )


#: How stale `last_used_at` may get before it is written again.
#:
#: Every write is a round trip to a database roughly 300ms away, and an integration
#: polling this API would pay it on every request for a column nobody reads in real time.
#: Five minutes is enough to answer the question the column exists for - "is this key
#: still in use, and when did it last run?" - at a hundredth of the cost.
API_KEY_TOUCH_INTERVAL = timedelta(minutes=5)


def _principal_from_api_key(raw_key: str, db: Session) -> Principal:
    prefix = raw_key[:11]
    set_tenant_guc(db, None, is_platform_admin=True)
    candidates = db.scalars(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.is_active.is_(True))
    ).all()
    for candidate in candidates:
        if not verify_api_key(raw_key, candidate.hashed_key):
            continue

        # An expiry date that is not enforced is a note to self. `create_api_key` has
        # always accepted `expires_in_days` and stored the date, and nothing ever read
        # it back - so a key issued to an integration "for 30 days" kept working for
        # good, which is the opposite of what the person issuing it was promised.
        now = datetime.now(UTC)
        if candidate.expires_at is not None and candidate.expires_at <= now:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                f"API key expired on {candidate.expires_at.date().isoformat()}",
            )

        # When it was last used, which is how a key nobody uses any more - or one being
        # used from somewhere it should not be - becomes visible.
        last = candidate.last_used_at
        if last is None or now - last > API_KEY_TOUCH_INTERVAL:
            candidate.last_used_at = now
            db.commit()

        return Principal(
            user_id=candidate.created_by_user_id,
            tenant_id=candidate.tenant_id,
            roles=[],
            is_platform_admin=False,
            api_key_id=candidate.id,
            actor_type="api_key",
            scopes=list(candidate.scopes or []),
        )
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")


def get_principal(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Principal:
    """Resolve the caller, then bind the DB session to the effective tenant."""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        principal = _principal_from_jwt(credentials.credentials, db)
    elif x_api_key:
        principal = _principal_from_api_key(x_api_key, db)
    else:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Platform staff may narrow themselves to one tenant for support and curation work.
    if x_tenant_id and principal.is_platform_admin:
        try:
            principal.tenant_id = uuid.UUID(x_tenant_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed X-Tenant-Id") from exc
        principal.scoped_to_tenant = True
    elif x_tenant_id and str(principal.tenant_id) != x_tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant mismatch")

    # Asking for one tenant means seeing that tenant, not everything. Keeping the
    # platform-admin bypass on would short-circuit every RLS policy to true, so a
    # support engineer who believes they are looking at one client would silently be
    # looking at all of them. RBAC still uses is_platform_admin; only data scope narrows.
    rls_bypass = principal.is_platform_admin and not principal.scoped_to_tenant
    set_tenant_guc(db, principal.tenant_id, rls_bypass)
    tenant_id_ctx.set(str(principal.tenant_id) if principal.tenant_id else None)
    user_id_ctx.set(str(principal.user_id) if principal.user_id else None)
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(resource: str, action: str):
    """Route guard: ``Depends(require("vendor", "write"))``."""

    def _guard(principal: CurrentPrincipal) -> Principal:
        if not principal.can(resource, action):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role does not permit {action} on {resource}",
            )
        return principal

    return _guard


def require_platform_admin(principal: CurrentPrincipal) -> Principal:
    if not principal.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator only")
    return principal


PlatformAdmin = Annotated[Principal, Depends(require_platform_admin)]
