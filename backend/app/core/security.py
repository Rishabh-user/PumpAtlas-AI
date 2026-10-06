"""Password hashing and JWT issuance / verification."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

BCRYPT_ROUNDS = 12


def _prepare(secret: str) -> bytes:
    """Reduce any secret to a fixed-length, null-byte-free input for bcrypt.

    bcrypt silently truncates anything past 72 bytes, which would make a long passphrase
    no stronger than its first 72 bytes. Hashing to SHA-256 first and base64-encoding the
    digest gives a constant 44-byte input, so the whole secret always contributes.

    (Using bcrypt directly rather than passlib: passlib 1.7.4 is unmaintained and reads
    ``bcrypt.__about__``, which bcrypt 4.x removed, producing a spurious error on every
    call.)
    """
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison. Returns False rather than raising on a malformed hash."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid.uuid4()),
        "iss": "pumpatlas-ai",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(
    user_id: str, tenant_id: str | None, roles: list[str], is_platform_admin: bool = False
) -> str:
    return _create_token(
        user_id,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        {"tid": tenant_id, "roles": roles, "adm": is_platform_admin},
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Raises ``jwt.PyJWTError`` subclasses on any problem."""
    payload = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], issuer="pumpatlas-ai"
    )
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload


def new_api_key() -> tuple[str, str]:
    """Return ``(plaintext, hash)``. Only the hash is stored."""
    raw = f"pa_{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}"
    return raw, hash_password(raw)


def verify_api_key(raw: str, hashed: str) -> bool:
    return verify_password(raw, hashed)
