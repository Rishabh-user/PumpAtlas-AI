"""Provider credentials in the database: the properties that make that acceptable.

Moving keys out of `.env` and into a settings screen trades a file on one machine for a
row in a hosted database. Four things have to hold, and each fails silently rather than
loudly - the screen still works, it just leaks:

* the key is encrypted at rest,
* no endpoint returns it,
* only platform staff can reach any of it,
* the ciphertext is not readable through the admin table browser.

A fifth is about correctness rather than secrecy: exactly one configuration is active
per role, enforced by the schema rather than by whichever request ran last.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.api.v1 import admin_database, ai_settings_routes
from app.core.config import settings
from app.models.ai_settings import AiProviderConfig
from app.services import ai_settings


class TestKeysAreEncryptedAtRest:
    def test_a_key_round_trips(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-long-enough-development-secret")
        token, hint = ai_settings.encrypt_key("sk-test-abcdefghijklmnop")
        config = AiProviderConfig(
            label="x", provider="openai", role="reading", encrypted_api_key=token
        )
        assert ai_settings.decrypt_key(config) == "sk-test-abcdefghijklmnop"

    def test_the_ciphertext_does_not_contain_the_key(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-long-enough-development-secret")
        plaintext = "sk-proj-verydistinctivevalue123456"
        token, _ = ai_settings.encrypt_key(plaintext)
        assert plaintext not in token
        # Nor any substantial run of it.
        assert plaintext[8:24] not in token

    def test_the_hint_identifies_without_revealing(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-long-enough-development-secret")
        plaintext = "sk-proj-abcdefghijklmnopqrstuvwxyz"
        _, hint = ai_settings.encrypt_key(plaintext)
        assert plaintext not in hint
        assert len(hint) < 16
        # A fixed prefix slice would show only "sk-proj-" and identify nothing, so the
        # hint carries both ends.
        assert hint.startswith("sk-pro") and hint.endswith("wxyz")

    def test_a_changed_secret_is_reported_not_swallowed(self, monkeypatch):
        """Rotating SECRET_KEY makes stored keys unreadable, which must be said.

        Silently failing later - mid-sweep, after paying for searches - would be worse
        than refusing now with an instruction to re-enter them.
        """
        monkeypatch.setattr(settings, "SECRET_KEY", "the-original-development-secret")
        token, _ = ai_settings.encrypt_key("sk-test-abcdefghijklmnop")
        config = AiProviderConfig(
            label="x", provider="openai", role="reading", encrypted_api_key=token
        )
        monkeypatch.setattr(settings, "SECRET_KEY", "a-different-development-secret!!")
        with pytest.raises(ai_settings.AiSettingsError, match="SECRET_KEY has changed"):
            ai_settings.decrypt_key(config)

    def test_a_short_secret_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "short")
        with pytest.raises(ai_settings.AiSettingsError, match="too short"):
            ai_settings.encrypt_key("sk-test-abcdefghijklmnop")

    def test_an_empty_key_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-long-enough-development-secret")
        with pytest.raises(ai_settings.AiSettingsError):
            ai_settings.encrypt_key("   ")


class TestNoEndpointReturnsAKey:
    def test_the_api_representation_carries_no_key_material(self, monkeypatch):
        monkeypatch.setattr(settings, "SECRET_KEY", "a-long-enough-development-secret")
        token, hint = ai_settings.encrypt_key("sk-proj-abcdefghijklmnopqrstuv")
        config = AiProviderConfig(
            label="GPT",
            provider="openai",
            role="reading",
            model="gpt-4o-mini",
            encrypted_api_key=token,
            key_hint=hint,
            is_active=True,
        )
        payload = ai_settings.as_dict(config)
        assert "encrypted_api_key" not in payload
        assert "api_key" not in payload
        assert token not in str(payload)
        # The hint is the only key-derived thing that travels.
        assert payload["key_hint"] == hint

    def test_no_route_serialises_the_ciphertext_column(self):
        """Every response is built by `as_dict`, which cannot include it."""
        source = inspect.getsource(ai_settings_routes)
        assert "encrypted_api_key" not in source

    def test_the_check_route_reports_a_result_not_a_credential(self):
        source = inspect.getsource(ai_settings_routes.check_provider)
        assert "decrypt_key" not in source
        assert '"ok"' in source


class TestOnlyPlatformStaff:
    def test_every_route_requires_platform_admin(self):
        tree = ast.parse(pathlib.Path(ai_settings_routes.__file__).read_text(encoding="utf-8"))
        handlers = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in {"get", "post", "patch", "delete", "put"}
                for d in node.decorator_list
            )
        ]
        assert handlers, "expected route handlers"
        for handler in handlers:
            annotations = {
                ast.unparse(arg.annotation) for arg in handler.args.args if arg.annotation
            }
            assert "PlatformAdmin" in annotations, handler.name

    def test_the_config_table_is_not_tenant_scoped(self):
        """One operational choice for the installation, not a per-customer setting."""
        assert "tenant_id" not in AiProviderConfig.__table__.columns


class TestTheCiphertextIsNotReadableElsewhere:
    def test_the_admin_table_browser_redacts_it(self):
        """The browser can display any table, so it must not become the way out."""
        assert "ai_provider_configs.encrypted_api_key" in admin_database.REDACTED_COLUMNS


class TestOneActivePerRole:
    def test_a_partial_unique_index_enforces_it(self):
        """Not application code: two active providers is not a state to be in.

        The runner would have to pick one arbitrarily and the screen would show
        something untrue.
        """
        index = next(
            ix
            for ix in AiProviderConfig.__table__.indexes
            if ix.name == "uq_ai_provider_configs_one_active_per_role"
        )
        assert index.unique
        assert index.dialect_options["postgresql"]["where"] is not None

    def test_activating_deactivates_the_previous_one_first(self):
        """In that order, or the index rejects the pair mid-transaction."""
        source = inspect.getsource(ai_settings.activate_config)
        assert source.index("is_active = False") < source.index("config.is_active = True")
        assert "db.flush()" in source


class TestARoleCannotBeGivenAProviderThatCannotDoIt:
    @pytest.mark.parametrize(
        ("provider", "role"),
        [("parallel", "reading"), ("openrouter", "search")],
    )
    def test_an_impossible_pairing_is_refused(self, provider, role):
        """Caught at entry, not an hour into a sweep that has already paid for searches."""
        with pytest.raises(ai_settings.AiSettingsError, match="cannot do"):
            ai_settings.validate(provider, role, "some-model")

    @pytest.mark.parametrize(
        ("provider", "role"),
        [
            ("parallel", "search"),
            ("openai", "search"),
            ("anthropic", "search"),
            ("openrouter", "reading"),
            ("openai", "reading"),
            ("anthropic", "reading"),
        ],
    )
    def test_every_supported_pairing_is_accepted(self, provider, role):
        ai_settings.validate(provider, role, "a-model")

    def test_a_model_is_required_except_for_parallel(self):
        ai_settings.validate("parallel", "search", None)
        with pytest.raises(ai_settings.AiSettingsError, match="model is required"):
            ai_settings.validate("openai", "reading", None)

    def test_an_unknown_role_is_refused(self):
        with pytest.raises(ai_settings.AiSettingsError, match="Unknown role"):
            ai_settings.validate("openai", "everything", "gpt-4o-mini")

    def test_the_form_is_only_offered_workable_choices(self):
        """The screen builds itself from this, so it cannot offer an invalid pairing."""
        for role, names in ai_settings.PROVIDERS_BY_ROLE.items():
            for provider in names:
                ai_settings.validate(provider, role, "a-model")


class TestEditingDoesNotDestroyTheKey:
    def test_an_absent_key_leaves_the_stored_one_alone(self, monkeypatch):
        """Otherwise renaming a configuration would silently wipe its credential."""
        source = inspect.getsource(ai_settings.update)
        assert "if api_key and api_key.strip():" in source

    def test_replacing_the_key_clears_the_stale_check_result(self):
        source = inspect.getsource(ai_settings.update)
        assert "last_check_ok = None" in source


class TestAnthropicIsTheDefault:
    """First in the list is what the form preselects, for both roles."""

    def test_anthropic_leads_both_roles(self):
        assert ai_settings.PROVIDERS_BY_ROLE["search"][0] == "anthropic"
        assert ai_settings.PROVIDERS_BY_ROLE["reading"][0] == "anthropic"

    def test_every_provider_has_a_default_model(self):
        """So choosing a provider fills the model in rather than asking for an id."""
        for names in ai_settings.PROVIDERS_BY_ROLE.values():
            for provider in names:
                assert provider in ai_settings.DEFAULT_MODELS, provider
        # Parallel AI takes no model, and that is expressed as None rather than "".
        assert ai_settings.DEFAULT_MODELS["parallel"] is None
        assert ai_settings.DEFAULT_MODELS["anthropic"]


class TestAMissingTableIsASetupStepNotACrash:
    """The app role cannot create tables, so the table arrives by migration.

    Until then an UndefinedTable propagated as a 500 and the screen showed a stack
    trace, which tells nobody what to do about it.
    """

    def test_the_list_route_checks_before_querying(self):
        source = inspect.getsource(ai_settings_routes.list_providers)
        assert source.index("is_installed(db)") < source.index("list_configs(db)")

    def test_every_route_that_touches_the_table_is_guarded(self):
        """Guarding only the list route left Save failing with a bare 500.

        The page showed the setup instructions directly underneath that error, which is
        a particular kind of unhelpful. A dependency covers routes added later too.
        """
        tree = ast.parse(pathlib.Path(ai_settings_routes.__file__).read_text(encoding="utf-8"))
        # These two are exempt: /options needs no table, and the list route reports the
        # missing table as data so the screen can render the instructions.
        exempt = {"options", "list_providers"}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name in exempt:
                continue
            decorators = [
                d
                for d in node.decorator_list
                if isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in {"get", "post", "patch", "delete", "put"}
            ]
            if not decorators:
                continue
            rendered = ast.unparse(decorators[0])
            assert "TableRequired" in rendered, f"{node.name} is not guarded"

    def test_the_guard_answers_503_not_500(self):
        """A deployment step that has not happened, not a bad request."""
        source = inspect.getsource(ai_settings_routes.require_table)
        assert "HTTP_503_SERVICE_UNAVAILABLE" in source
        assert "SETUP_HINT" in source

    def test_the_command_names_the_migration_file(self):
        command = ai_settings.setup_command()
        assert "db/migrations/001_ai_provider_configs.sql" in command
        assert "apply_schema.py" in command

    def test_the_command_fills_in_the_real_target(self):
        """Only the owner's credentials are left to substitute.

        A hand-assembled connection string is where this goes wrong, so host, port,
        database and sslmode come from the running configuration.
        """
        from app.core.config import settings

        command = ai_settings.setup_command()
        assert settings.database_host_summary in command
        assert "OWNER:PASSWORD" in command

    def test_the_command_never_contains_a_password(self):
        """The service does not hold the owner credential and must not appear to."""
        from app.core.config import settings

        command = ai_settings.setup_command()
        secret = settings.POSTGRES_PASSWORD
        if secret:
            assert secret not in command

    def test_the_migration_file_exists(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        migration = root / "db" / "migrations" / "001_ai_provider_configs.sql"
        assert migration.exists()
        body = migration.read_text(encoding="utf-8")
        # Idempotent, so re-running it is safe, and it grants the app role access.
        assert "CREATE TABLE IF NOT EXISTS ai_provider_configs" in body
        assert (
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ai_provider_configs TO pumpatlas_app" in body
        )


class TestErrorBodiesAreReadOnce:
    """A fetch body can only be consumed once.

    Falling back from .json() to .text() threw "Body is unusable: Body has already been
    read", which replaced every non-JSON API error with a message about the error
    handler. The real failure - a 500 from a missing table - never reached the screen.
    """

    @pytest.mark.parametrize("helper", ["api.ts", "api-client.ts"])
    def test_the_frontend_helper_does_not_read_twice(self, helper):
        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root / "frontend" / "src" / "lib" / helper).read_text(encoding="utf-8")
        # One read, then JSON.parse on the text - never .json() followed by .text().
        assert 'await response.text().catch(() => "")' in source
        assert "detail = await response.json()" not in source


class TestTheBadgesNameWhoActuallyRan:
    """The run panel puts a provider badge on each stage.

    It read `.env` directly, so a run using Claude for both roles was badged
    "Parallel AI" and "Gemma" - the environment values, which by then were only the
    fallback. A badge that contradicts the job list beside it is worse than no badge.
    """

    def test_the_resolver_prefers_the_activated_configuration(self):
        from app.services import discovery

        source = inspect.getsource(discovery.resolved_providers)
        assert 'active_config(db, "search")' in source
        assert 'active_config(db, "reading")' in source
        # The environment is the fallback, not the answer.
        assert "settings.SEARCH_PROVIDER" in source
        assert "settings.EXTRACTION_PROVIDER" in source

    def test_the_resolver_survives_a_missing_table(self):
        """Before the migration there is nothing to read, and that is not an error."""
        from app.services import discovery

        assert "is_installed(db)" in inspect.getsource(discovery.resolved_providers)

    def test_run_creation_records_the_real_providers(self):
        from app.services import discovery

        source = inspect.getsource(discovery.start_run)
        assert "initial_stages(kind, *resolved_providers(db))" in source

    def test_the_runner_corrects_the_badge_at_execution_time(self):
        """The active configuration can change between queueing and starting."""
        from app.services import discovery

        source = inspect.getsource(discovery.run_discovery)
        assert "provider=search_provider" in source
        assert "provider=reading_provider" in source

    def test_the_reading_provider_is_known_before_the_stage_is_marked_running(self):
        """Or the badge is written from an unassigned name."""
        from app.services import discovery

        source = inspect.getsource(discovery.run_discovery)
        assert source.index("reading_provider = resolved_providers(db)[1]") < source.index(
            "provider=reading_provider"
        )


class TestDiscoveryUsesTheActivatedProvider:
    def test_the_runner_prefers_the_stored_configuration(self):
        from app.services import discovery

        source = inspect.getsource(discovery.run_discovery)
        assert 'ai_settings.active_config(db, "search")' in source
        assert "providers.configured_reading_model(db)" in source

    def test_the_environment_remains_a_fallback(self):
        """So upgrading does not break a working deployment before anyone visits the page."""
        from app.services import discovery

        source = inspect.getsource(discovery.run_discovery)
        assert "providers.search_client()" in source
        assert "providers.reading_model()" in source
