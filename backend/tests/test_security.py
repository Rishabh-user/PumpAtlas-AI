"""Password and token handling.

Auth is the one area where a subtle bug is a breach rather than a defect.
"""

from __future__ import annotations

import pathlib
import time

import jwt
import pytest

from app.core import security


def test_hash_is_salted_and_verifies():
    first = security.hash_password("correct horse battery staple")
    second = security.hash_password("correct horse battery staple")
    assert first != second, "hashes must be salted"
    assert security.verify_password("correct horse battery staple", first)
    assert security.verify_password("correct horse battery staple", second)


def test_wrong_password_fails():
    hashed = security.hash_password("s3cret-passphrase")
    assert not security.verify_password("s3cret-passphras", hashed)
    assert not security.verify_password("", hashed)


def test_long_passphrase_is_not_silently_truncated():
    """bcrypt ignores bytes past 72; the SHA-256 pre-hash is what prevents that.

    Without it these two passphrases - identical for 72 bytes, different after - would
    hash to the same value and either would unlock the account.
    """
    base = "a" * 72
    hashed = security.hash_password(base + "-alpha")
    assert security.verify_password(base + "-alpha", hashed)
    assert not security.verify_password(base + "-omega", hashed)


def test_unicode_passwords_round_trip():
    password = "Ingrid Sølheim / переменная / 密码 / 🔧"
    assert security.verify_password(password, security.hash_password(password))


def test_malformed_hash_returns_false_rather_than_raising():
    assert not security.verify_password("anything", "not-a-bcrypt-hash")
    assert not security.verify_password("anything", "")


def test_api_key_prefix_is_stable_and_hash_verifies():
    raw, hashed = security.new_api_key()
    assert raw.startswith("pa_")
    # deps.py looks keys up by their first 11 characters before verifying the hash.
    assert len(raw[:11]) == 11
    assert security.verify_api_key(raw, hashed)
    assert not security.verify_api_key(raw + "x", hashed)


def test_access_token_carries_tenant_and_roles():
    token = security.create_access_token(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        ["research_analyst"],
        is_platform_admin=False,
    )
    claims = security.decode_token(token, expected_type="access")
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["tid"] == "22222222-2222-2222-2222-222222222222"
    assert claims["roles"] == ["research_analyst"]
    assert claims["adm"] is False
    assert claims["iss"] == "pumpatlas-ai"


def test_refresh_token_is_rejected_where_an_access_token_is_required():
    """Otherwise a long-lived refresh token would work as an API credential."""
    refresh = security.create_refresh_token("11111111-1111-1111-1111-111111111111")
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(refresh, expected_type="access")
    assert security.decode_token(refresh, expected_type="refresh")["type"] == "refresh"


def test_token_signed_with_another_key_is_rejected():
    token = jwt.encode(
        {"sub": "x", "type": "access", "iss": "pumpatlas-ai", "exp": int(time.time()) + 60},
        "a-different-secret",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidSignatureError):
        security.decode_token(token, expected_type="access")


def test_expired_token_is_rejected():
    now = int(time.time())
    token = jwt.encode(
        {"sub": "x", "type": "access", "iss": "pumpatlas-ai", "iat": now - 120, "exp": now - 60},
        security.settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token, expected_type="access")


def test_token_from_another_issuer_is_rejected():
    token = jwt.encode(
        {"sub": "x", "type": "access", "iss": "someone-else", "exp": int(time.time()) + 60},
        security.settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidIssuerError):
        security.decode_token(token, expected_type="access")


class TestAnApiKeyIsOnlyGoodWhileItIsGood:
    """Another application authenticates with a key rather than a login.

    `create_api_key` has always accepted `expires_in_days` and stored the date, and
    nothing ever read it back - so a key issued to an integration "for 30 days" kept
    working for good, which is the opposite of what the person issuing it was promised.
    """

    def _key(self, raw_hash, **kwargs):
        from app.models.user import ApiKey

        fields = {
            "prefix": "pa_deadbeef",
            "hashed_key": raw_hash,
            "name": "Portal",
            "scopes": ["vendor:read"],
            "is_active": True,
            "tenant_id": None,
            "expires_at": None,
            "last_used_at": None,
        }
        fields.update(kwargs)
        return ApiKey(**fields)

    class _Db:
        def __init__(self, keys):
            self.keys = keys
            self.commits = 0

        def scalars(self, _statement):
            return self

        def all(self):
            return self.keys

        def execute(self, *_args, **_kwargs):
            return None

        def commit(self):
            self.commits += 1

    def _authenticate(self, monkeypatch, key, raw):
        from app.core import deps

        monkeypatch.setattr(deps, "set_tenant_guc", lambda *a, **k: None)
        return deps._principal_from_api_key(raw, self._Db([key]))

    def test_a_live_key_authenticates(self, monkeypatch):
        raw, hashed = security.new_api_key()
        principal = self._authenticate(monkeypatch, self._key(hashed), raw)
        assert principal.actor_type == "api_key"
        assert principal.scopes == ["vendor:read"]
        assert principal.is_platform_admin is False

    def test_an_expired_key_is_refused(self, monkeypatch):
        from datetime import UTC, datetime, timedelta

        import fastapi

        raw, hashed = security.new_api_key()
        expired = self._key(hashed, expires_at=datetime.now(UTC) - timedelta(days=1))
        with pytest.raises(fastapi.HTTPException) as caught:
            self._authenticate(monkeypatch, expired, raw)
        assert caught.value.status_code == 401
        assert "expired" in caught.value.detail

    def test_a_key_expiring_later_still_works(self, monkeypatch):
        from datetime import UTC, datetime, timedelta

        raw, hashed = security.new_api_key()
        key = self._key(hashed, expires_at=datetime.now(UTC) + timedelta(days=1))
        assert self._authenticate(monkeypatch, key, raw).actor_type == "api_key"

    def test_use_is_recorded_the_first_time(self, monkeypatch):
        raw, hashed = security.new_api_key()
        key = self._key(hashed)
        self._authenticate(monkeypatch, key, raw)
        assert key.last_used_at is not None

    def test_but_not_on_every_request(self, monkeypatch):
        """One write per request to a database 300ms away, for a column nobody watches."""
        from datetime import UTC, datetime

        raw, hashed = security.new_api_key()
        key = self._key(hashed, last_used_at=datetime.now(UTC))
        before = key.last_used_at
        self._authenticate(monkeypatch, key, raw)
        assert key.last_used_at == before

    def test_a_key_cannot_carry_platform_admin(self, monkeypatch):
        """Platform admin bypasses row-level security; no machine credential gets that."""
        raw, hashed = security.new_api_key()
        principal = self._authenticate(monkeypatch, self._key(hashed), raw)
        assert principal.is_platform_admin is False

    def test_scopes_are_what_a_key_may_do(self):
        from app.core.deps import Principal

        key = Principal(
            user_id=None,
            tenant_id=None,
            roles=[],
            is_platform_admin=False,
            actor_type="api_key",
            scopes=["vendor:read"],
        )
        assert key.can("vendor", "read") is True
        assert key.can("vendor", "write") is False
        assert key.can("pump", "read") is False


class TestTheReadOnlyKeyReachesWhatWasPromised:
    """`--read-only` has to cover vendors, pumps and chat, and nothing that writes.

    The scopes are checked per request against the resource each endpoint names. A set
    that misses one leaves the other application with a 403 on a page it was told would
    work; a set that is too wide hands a display application the ability to change
    records.
    """

    def _key_principal(self):
        from app.core.deps import Principal
        from scripts.manage_api_key import READ_ONLY_SCOPES

        return Principal(
            user_id=None,
            tenant_id=None,
            roles=[],
            is_platform_admin=False,
            actor_type="api_key",
            scopes=list(READ_ONLY_SCOPES),
        )

    def test_it_can_read_the_three_areas(self):
        principal = self._key_principal()
        # vendors, pumps, and search - which is what chat/ask and /search both require.
        assert principal.can("vendor", "read")
        assert principal.can("pump", "read")
        assert principal.can("search", "read")

    def test_it_cannot_change_anything(self):
        principal = self._key_principal()
        for resource, action in [
            ("vendor", "write"),
            ("vendor", "delete"),
            ("vendor", "approve"),
            ("pump", "write"),
            ("pump", "delete"),
            ("ingestion", "write"),
            ("technical_spec", "approve"),
        ]:
            assert principal.can(resource, action) is False, f"{resource}:{action}"

    def test_the_scopes_named_are_the_ones_the_endpoints_ask_for(self):
        """Read endpoints across vendors, pumps, search and chat name three resources."""
        import re

        from scripts.manage_api_key import READ_ONLY_SCOPES

        required = set()
        for module in ("vendors", "pumps", "search", "chat_routes"):
            source = pathlib.Path(f"app/api/v1/{module}.py").read_text(encoding="utf-8")
            required |= {
                f"{resource}:{action}"
                for resource, action in re.findall(r'require\("(\w+)", "(read)"\)', source)
            }
        assert required <= set(READ_ONLY_SCOPES), (
            f"a read endpoint needs {required - set(READ_ONLY_SCOPES)}, which --read-only "
            "does not grant"
        )
