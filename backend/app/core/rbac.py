"""Role-based access control.

Six product roles map onto resource/action pairs. ``admin`` is the tenant
administrator; platform staff carry ``User.is_platform_admin`` in addition, which is
what allows crossing tenant boundaries.
"""

from __future__ import annotations

from app.models.enums import UserRoleName

READ = "read"
WRITE = "write"
DELETE = "delete"
APPROVE = "approve"
EXPORT = "export"

# resource -> {action: {roles}}
_ALL = {
    UserRoleName.ADMIN,
    UserRoleName.RESEARCH_ANALYST,
    UserRoleName.PROCUREMENT,
    UserRoleName.ENGINEERING,
    UserRoleName.VENDOR_MANAGER,
    UserRoleName.CLIENT_USER,
}
_STAFF = _ALL - {UserRoleName.CLIENT_USER}

ROLE_MATRIX: dict[str, dict[str, set[UserRoleName]]] = {
    "vendor": {
        READ: _ALL,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST, UserRoleName.VENDOR_MANAGER},
        DELETE: {UserRoleName.ADMIN},
        APPROVE: {UserRoleName.ADMIN, UserRoleName.VENDOR_MANAGER},
    },
    "pump": {
        READ: _ALL,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST, UserRoleName.ENGINEERING},
        DELETE: {UserRoleName.ADMIN},
    },
    "technical_spec": {
        READ: _ALL,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST, UserRoleName.ENGINEERING},
        APPROVE: {UserRoleName.ADMIN, UserRoleName.ENGINEERING},
    },
    "commercial_spec": {
        READ: {
            UserRoleName.ADMIN,
            UserRoleName.PROCUREMENT,
            UserRoleName.RESEARCH_ANALYST,
            UserRoleName.VENDOR_MANAGER,
        },
        WRITE: {UserRoleName.ADMIN, UserRoleName.PROCUREMENT, UserRoleName.RESEARCH_ANALYST},
        APPROVE: {UserRoleName.ADMIN, UserRoleName.PROCUREMENT},
    },
    "dimensional_spec": {
        READ: _ALL,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST, UserRoleName.ENGINEERING},
    },
    "delivery_spec": {
        READ: _ALL,
        WRITE: {UserRoleName.ADMIN, UserRoleName.PROCUREMENT, UserRoleName.RESEARCH_ANALYST},
    },
    "operational_spec": {
        READ: _ALL,
        WRITE: {
            UserRoleName.ADMIN,
            UserRoleName.RESEARCH_ANALYST,
            UserRoleName.VENDOR_MANAGER,
            UserRoleName.ENGINEERING,
        },
    },
    "administrative_spec": {
        READ: _STAFF,
        WRITE: {UserRoleName.ADMIN, UserRoleName.VENDOR_MANAGER, UserRoleName.RESEARCH_ANALYST},
    },
    "ingestion": {
        READ: _STAFF,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST},
        DELETE: {UserRoleName.ADMIN},
    },
    "ai_review": {
        READ: _STAFF,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST},
        APPROVE: {
            UserRoleName.ADMIN,
            UserRoleName.RESEARCH_ANALYST,
            UserRoleName.ENGINEERING,
            UserRoleName.PROCUREMENT,
        },
    },
    "comparison": {
        READ: _ALL,
        WRITE: {
            UserRoleName.ADMIN,
            UserRoleName.PROCUREMENT,
            UserRoleName.ENGINEERING,
            UserRoleName.RESEARCH_ANALYST,
        },
        EXPORT: {UserRoleName.ADMIN, UserRoleName.PROCUREMENT, UserRoleName.ENGINEERING},
    },
    "data_quality": {READ: _STAFF, WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST}},
    "audit": {READ: {UserRoleName.ADMIN}},
    "tenant": {READ: {UserRoleName.ADMIN}, WRITE: {UserRoleName.ADMIN}},
    "user": {READ: {UserRoleName.ADMIN}, WRITE: {UserRoleName.ADMIN}},
    "search": {READ: _ALL},
    "document": {
        READ: _ALL,
        WRITE: {UserRoleName.ADMIN, UserRoleName.RESEARCH_ANALYST, UserRoleName.VENDOR_MANAGER},
    },
}


def is_allowed(roles: list[str], resource: str, action: str) -> bool:
    permitted = ROLE_MATRIX.get(resource, {}).get(action)
    if not permitted:
        return False
    allowed_values = {r.value for r in permitted}
    return any(role in allowed_values for role in roles)


def permissions_for(role: UserRoleName) -> dict[str, list[str]]:
    """Flatten the matrix for one role - stored on the ``roles`` row when seeding."""
    out: dict[str, list[str]] = {}
    for resource, actions in ROLE_MATRIX.items():
        granted = sorted(action for action, roles in actions.items() if role in roles)
        if granted:
            out[resource] = granted
    return out
