"""Configuration: the template stays in step with the code, and it ships no secret.

`.env.example` is what gets copied to `.env`, so anything filled in there is a default
for every installation that does not think about it. That is how this project ended up
with a published administrator password and, less obviously, with the MinIO credentials
selecting an S3 backend on machines that had no MinIO - which failed every document
upload instead of falling back to disk.

The other half is drift: a template that documents a setting the code stopped reading, or
misses one it started reading, sends the next person to the wrong place.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest
from pydantic import ValidationError

from app.api.v1 import system
from app.core.config import DEV_SECRET_KEY, MIN_SECRET_KEY_CHARS, Settings

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = REPO / ".env.example"

#: Settings the template deliberately omits, with the reason.
UNDOCUMENTED_ON_PURPOSE = {
    # Changing the JWT algorithm is not a deployment knob; documenting it invites
    # someone to try "none".
    "ALGORITHM",
}


def template_keys() -> dict[str, str]:
    """Keys the template sets, ignoring comments - including commented-out examples."""
    keys: dict[str, str] = {}
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        keys[key.strip()] = value.strip()
    return keys


def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


class TestTheTemplateMatchesTheCode:
    def test_every_setting_is_documented(self):
        """A setting nobody can find is a setting nobody sets."""
        documented = set(template_keys())
        text = template_text()
        missing = sorted(
            name
            for name in Settings.model_fields
            if name not in documented
            and name not in UNDOCUMENTED_ON_PURPOSE
            # A commented-out example (`# DATABASE_URL=...`) counts as documented.
            and f"# {name}=" not in text
        )
        assert missing == [], f"undocumented settings: {missing}"

    def test_it_documents_nothing_the_code_ignores(self):
        """`EXTRACTION_FALLBACK_PROVIDERS` outlived the code that read it by a while."""
        stale = sorted(set(template_keys()) - set(Settings.model_fields))
        assert stale == []

    @pytest.mark.parametrize(
        "key",
        [
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "POSTGRES_PASSWORD",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "PARALLEL_API_KEY",
        ],
    )
    def test_no_credential_is_filled_in(self, key):
        assert template_keys().get(key) == "", f"{key} must ship empty"

    def test_the_secret_key_is_not_set_to_anything(self):
        """Empty would be refused at startup; a placeholder would be a shared secret.

        Commented out is the third option: the code default applies, and readiness
        reports it as weak.
        """
        assert "SECRET_KEY" not in template_keys()
        assert "# SECRET_KEY=" in template_text()

    def test_it_says_where_the_login_and_the_ai_keys_live_instead(self):
        text = template_text()
        assert "scripts.manage_user create" in text
        assert "/ai-settings" in text


class TestAnUnusableSecretIsCaught:
    def test_an_empty_secret_is_refused_outright(self):
        """`SECRET_KEY=` signs tokens with a zero-length secret and nothing complains."""
        with pytest.raises(ValidationError, match="SECRET_KEY is empty"):
            Settings(SECRET_KEY="")

    def test_whitespace_counts_as_empty(self):
        with pytest.raises(ValidationError, match="SECRET_KEY is empty"):
            Settings(SECRET_KEY="   ")

    def test_the_development_default_is_reported_as_weak(self):
        assert Settings(SECRET_KEY=DEV_SECRET_KEY).secret_key_is_weak

    def test_a_short_secret_is_weak_but_still_starts(self):
        """The offline suite runs on a short key; breaking it would buy nothing."""
        short = "a" * (MIN_SECRET_KEY_CHARS - 1)
        assert Settings(SECRET_KEY=short).secret_key_is_weak

    def test_a_real_secret_is_not_weak(self):
        assert not Settings(SECRET_KEY="b" * 64).secret_key_is_weak

    def test_the_minimum_matches_what_encryption_needs(self):
        """Shorter and `ai_settings._fernet` refuses, at the point of use rather than here."""
        from app.services import ai_settings

        assert MIN_SECRET_KEY_CHARS >= 16
        assert "too short" in inspect.getsource(ai_settings._fernet)


class TestReadinessReportsTheRealConfiguration:
    def test_the_ai_checks_read_the_database_not_the_environment(self):
        """Saying "not_configured" while a run uses Anthropic from the database is a lie.

        The same class as the progress badge that named Gemma while Claude was reading.
        """
        source = inspect.getsource(system.ready)
        assert "ai_settings.active_config(db, role)" in source
        assert '"source": "database"' in source

    def test_it_names_the_environment_fallback_as_a_fallback(self):
        source = inspect.getsource(system.ready)
        assert "environment fallback" in source

    def test_a_weak_secret_only_fails_production(self):
        """In development the default is the expected value, so 503 would be noise."""
        source = inspect.getsource(system.ready)
        assert '"required": settings.is_production' in source

    def test_redis_is_required_only_when_a_queue_is_meant_to_exist(self):
        source = inspect.getsource(system.ready)
        assert "not settings.CELERY_TASK_ALWAYS_EAGER" in source

    def test_a_missing_redis_says_what_it_costs(self):
        """Runs then execute in the API process and die with a restart."""
        source = inspect.getsource(system.ready)
        assert "do not " in source and "survive a restart" in source

    def test_storage_reports_which_backend_it_chose(self):
        source = inspect.getsource(system.ready)
        assert "settings.use_s3" in source
        assert "LOCAL_STORAGE_DIR" in source


class TestTheDeployedOriginsAreRealOrigins:
    """Render's blueprint supplies a service's `host` property, which is a bare hostname.

    A browser sends `Origin: https://that-host`. Starlette compares the two as strings,
    so a bare hostname matches nothing and every cross-origin call is refused - with
    nothing in the logs naming the cause.
    """

    def test_a_bare_hostname_becomes_an_origin(self):
        from app.core.config import Settings

        assert Settings(CORS_ORIGINS="pumpatlas-web.onrender.com").cors_origins == [
            "https://pumpatlas-web.onrender.com"
        ]

    def test_an_origin_that_is_already_one_is_untouched(self):
        from app.core.config import Settings

        assert Settings(CORS_ORIGINS="http://localhost:3000").cors_origins == [
            "http://localhost:3000"
        ]

    def test_a_trailing_slash_is_not_part_of_an_origin(self):
        from app.core.config import Settings

        assert Settings(CORS_ORIGINS="https://a.example/").cors_origins == ["https://a.example"]

    def test_the_wildcard_still_means_everything(self):
        from app.core.config import Settings

        assert Settings(CORS_ORIGINS="*").cors_origins == ["*"]

    def test_several_origins_are_each_normalised(self):
        from app.core.config import Settings

        assert Settings(CORS_ORIGINS="a.example, https://b.example , ").cors_origins == [
            "https://a.example",
            "https://b.example",
        ]
