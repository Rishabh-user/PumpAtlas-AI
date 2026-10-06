"""A login is a database row, not configuration.

`FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` used to live in `.env`, and the seeder
hashed whatever it found there into a platform administrator. The default shipped in this
repository was `ChangeMe!123`, so any installation that never edited the file ran its most
privileged account on a published password - and rotating it meant editing configuration
and re-running a seeder.

These tests pin the replacement: no credential in the settings object, none in the
template, no account created unattended, and no password passed where a shell would
record it.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from app.core.config import Settings, settings
from scripts import manage_user, seed

REPO = pathlib.Path(__file__).resolve().parents[2]


class TestConfigurationCarriesNoLogin:
    @pytest.mark.parametrize("name", ["FIRST_ADMIN_EMAIL", "FIRST_ADMIN_PASSWORD"])
    def test_the_setting_is_gone(self, name):
        assert name not in Settings.model_fields
        assert not hasattr(settings, name)

    def test_no_setting_looks_like_a_login(self):
        """A new `ADMIN_PASSWORD` would be the same mistake under another name."""
        suspicious = [
            name
            for name in Settings.model_fields
            if ("ADMIN" in name and ("PASSWORD" in name or "EMAIL" in name))
            or name.endswith("_LOGIN")
        ]
        assert suspicious == []

    def test_the_env_template_ships_no_account(self):
        """The template is what gets copied to `.env`, so a password in it is a default."""
        template = (REPO / ".env.example").read_text(encoding="utf-8")
        assert "FIRST_ADMIN" not in template
        assert "ChangeMe" not in template

    def test_the_deployment_blueprint_asks_for_no_account(self):
        blueprint = (REPO / "render.yaml").read_text(encoding="utf-8")
        assert "FIRST_ADMIN" not in blueprint

    @pytest.mark.parametrize("key", ["S3_ACCESS_KEY", "S3_SECRET_KEY"])
    def test_the_template_ships_no_storage_credential(self, key):
        """A filled-in credential in the template is a default, whatever it unlocks.

        These two shipped as `minioadmin`, and setting them is what selects the S3
        backend - so a machine without MinIO sent every document to a dead endpoint
        rather than falling back to local disk.
        """
        template = (REPO / ".env.example").read_text(encoding="utf-8")
        empty = [line for line in template.splitlines() if line.strip() == f"{key}="]
        assert empty, f"{key} must ship empty in the template"


class TestTheSeederCreatesNoAdministrator:
    """An unattended seeder cannot ask for a password, so it must not invent one."""

    def test_it_no_longer_has_a_platform_admin_writer(self):
        assert not hasattr(seed, "seed_platform_admin")

    def test_it_only_counts_administrators(self):
        source = inspect.getsource(seed.platform_admin_count)
        assert "select(User)" in source
        for forbidden in ("db.add(", "hash_password("):
            assert forbidden not in source

    def test_it_reads_no_credential_from_settings(self):
        source = inspect.getsource(seed)
        assert "settings.FIRST_ADMIN" not in source

    def test_the_demo_password_is_generated_not_shared_with_the_admin(self):
        """These are `.example` accounts on a tenant production never seeds."""
        source = inspect.getsource(seed.seed_demo_tenant)
        assert "secrets.token_urlsafe" in source

    def test_it_says_how_to_create_the_first_login(self):
        """A run that leaves nobody able to sign in has to say so."""
        source = inspect.getsource(seed.main)
        assert "scripts.manage_user create" in source
        assert "No platform administrator exists yet" in source


class TestThePasswordNeverReachesArgvOrALog:
    def test_the_parser_accepts_no_password_argument(self):
        """An argument is visible in shell history and to `ps` while the command runs."""
        for command in ("create", "set-password"):
            actions = _actions_for(command)
            assert not any("--password" in option for option in actions), command

    def test_it_is_read_without_echo(self):
        source = inspect.getsource(manage_user.read_new_password)
        assert "getpass.getpass(" in source
        assert "input(" not in source

    def test_a_typed_password_is_confirmed(self):
        """A typo in a value nobody can see would lock the account out silently."""
        source = inspect.getsource(manage_user.read_new_password)
        assert source.count("getpass.getpass(") >= 2

    @pytest.mark.parametrize("name", ["cmd_create", "cmd_set_password"])
    def test_only_a_generated_password_is_ever_printed(self, name):
        """`--random` exists to hand an account to someone else; a typed one stays unseen.

        Checked by position rather than by eye: every line that interpolates the value
        has to fall inside the `if generated:` branch.
        """
        source = inspect.getsource(getattr(manage_user, name))
        branch = source.index("if generated:")
        interpolations = [
            index for index in range(len(source)) if source.startswith("{password}", index)
        ]
        assert interpolations, "expected the generated branch to print the password"
        assert all(index > branch for index in interpolations)

    def test_nothing_is_logged_with_the_password(self):
        source = inspect.getsource(manage_user)
        assert "log.info" not in source or "password=" not in source


class TestAnAccountLandsWhereItBelongs:
    def test_a_platform_admin_has_no_tenant(self):
        """A null tenant is how row level security recognises one."""
        assert manage_user.resolve_tenant(None, None, True) is None

    def test_a_platform_admin_cannot_also_be_a_tenant_user(self):
        with pytest.raises(SystemExit) as caught:
            manage_user.resolve_tenant(None, "demo-operator", True)
        assert "belongs to no tenant" in str(caught.value)

    def test_neither_flag_is_refused_rather_than_guessed(self):
        """Defaulting to a tenant would silently create the wrong kind of account."""
        with pytest.raises(SystemExit) as caught:
            manage_user.resolve_tenant(None, None, False)
        assert "--platform-admin" in str(caught.value)

    def test_no_roles_asked_for_means_no_roles(self):
        assert manage_user.resolve_roles(None, []) == []

    def test_an_administrator_gets_a_role_by_default(self):
        """Otherwise the account signs in and can see nothing, which reads as a bug."""
        source = inspect.getsource(manage_user.cmd_create)
        assert "UserRoleName.ADMIN.value" in source


class TestAWeakPasswordIsRefused:
    def test_a_short_password_is_refused(self):
        with pytest.raises(ValueError, match="at least"):
            manage_user._check_password("short")

    @pytest.mark.parametrize("password", ["ChangeMe!123", "changeme!123", " password "])
    def test_a_documented_default_is_refused(self, password):
        """Including the one this repository shipped: that is the whole point."""
        with pytest.raises(ValueError, match="default password"):
            manage_user._check_password(password)

    def test_a_long_passphrase_is_accepted(self):
        manage_user._check_password("correct horse battery staple")

    def test_the_minimum_is_a_length_not_a_character_class_rule(self):
        """Complexity rules mostly produce "Passw0rd!"; length is what helps."""
        assert manage_user.MIN_PASSWORD_CHARS >= 12
        manage_user._check_password("aaaaaaaaaaaaaaaa")


class TestTheLiveTestsCleanUpAfterThemselves:
    """A test that writes into a shared database has to remove what it wrote.

    Every run used to leave a "Confidential Rival Vendor rival-epc-…" in the vendor list
    and a searchable SECRET-… pump model. Nothing on the row says it came from a test, so
    it reads as real supply-chain data - and the platform's whole claim is that a stored
    record is traceable.
    """

    def test_the_isolation_fixture_tears_down_what_it_created(self):
        source = (REPO / "backend/tests/test_live_integration.py").read_text(encoding="utf-8")
        rival = source[source.index("def rival(") :]
        rival = rival.split(chr(10) + "def ")[0]
        assert "yield" in rival, "a fixture that returns cannot clean up"
        assert "client.delete(" in rival
        assert "/tenants/" in rival

    def test_teardown_cannot_fail_the_suite(self):
        """A failing teardown would mask the test result that actually matters."""
        source = (REPO / "backend/tests/test_live_integration.py").read_text(encoding="utf-8")
        rival = source[source.index("def rival(") :]
        assert rival.count("except Exception") >= 2

    def test_a_mop_up_script_exists_for_a_crashed_run(self):
        script = REPO / "backend/scripts/remove_test_residue.py"
        assert script.exists()
        text = script.read_text(encoding="utf-8")
        # It must match on generated names, not on "not AI-extracted": hand-entered data
        # is legitimate, and deleting by origin would take the real with the fake.
        assert "TEST_VENDOR_PATTERNS" in text
        assert "vendor_declared" not in text.split('"""')[2]
        assert "--commit" in text


class TestTheLiveTestsCarryNoCredential:
    def test_they_read_the_login_from_the_environment(self):
        source = (REPO / "backend/tests/test_live_integration.py").read_text(encoding="utf-8")
        assert "ChangeMe" not in source
        assert "PUMPATLAS_TEST_ADMIN_PASSWORD" in source

    def test_they_skip_when_no_credential_is_supplied(self):
        """Rather than failing with a 401 that looks like a broken API."""
        source = (REPO / "backend/tests/test_live_integration.py").read_text(encoding="utf-8")
        assert 'not ADMIN["password"]' in source


def _actions_for(command: str) -> list[str]:
    """The option strings one subcommand accepts."""
    parser = manage_user.build_parser()
    subparsers = [
        action
        for action in parser._actions  # noqa: SLF001 - argparse exposes no public API
        if hasattr(action, "choices") and isinstance(action.choices, dict)
    ][0]
    return [
        option
        for action in subparsers.choices[command]._actions  # noqa: SLF001
        for option in action.option_strings
    ]
