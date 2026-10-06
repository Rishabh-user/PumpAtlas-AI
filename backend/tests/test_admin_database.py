"""The admin table browser: what it must never do.

A read-only view of every table is useful and also the single most dangerous page in a
multi-tenant system. Three properties are the whole point, and each fails silently if
broken - the page still renders, it just shows more than it should:

* only platform staff can reach it,
* secrets are never read out of the database,
* an identifier from the URL never reaches a query unvalidated.

These are source- and contract-level. The live behaviour - that a tenant admin really
gets a 403 and that a password hash really comes back withheld - is exercised in
``test_live_integration.py`` where a database is available.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.api.v1 import admin_database


class TestOnlyPlatformStaffCanReachIt:
    def test_every_route_requires_platform_admin(self):
        """A tenant admin is not staff. The dependency is the boundary, not the page."""
        tree = ast.parse(pathlib.Path(admin_database.__file__).read_text(encoding="utf-8"))
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
        assert handlers, "expected route handlers in the module"
        for handler in handlers:
            annotations = {
                ast.unparse(arg.annotation) for arg in handler.args.args if arg.annotation
            }
            assert "PlatformAdmin" in annotations, f"{handler.name} does not require PlatformAdmin"

    def test_the_router_is_mounted_under_admin(self):
        assert admin_database.router.prefix == "/admin/database"


class TestSecretsAreNeverRead:
    """Withheld at the SELECT list, so the value never enters the process.

    Filtering after the fact would still pull password hashes across the wire and into
    memory, where a log line or an error payload could carry them out.
    """

    @pytest.mark.parametrize(
        "column",
        ["users.hashed_password", "users.mfa_secret", "api_keys.hashed_key"],
    )
    def test_the_known_secrets_are_listed(self, column):
        assert column in admin_database.REDACTED_COLUMNS

    def test_redaction_happens_in_the_projection(self):
        source = inspect.getsource(admin_database.read_table)
        assert "REDACTION_MARKER" in source
        # The marker is substituted into the SELECT list rather than the row being
        # fetched and then scrubbed.
        assert "AS" in source and "projection" in source

    def test_a_redacted_column_is_still_listed(self):
        """Hiding that the column exists would be more confusing than withholding it."""
        source = inspect.getsource(admin_database._columns)
        assert '"redacted"' in source

    def test_no_secret_is_matched_by_pattern(self):
        """Explicit names, because a regex over "hash" hides ordinary data too.

        ``prompt_tokens``, ``content_hash`` and ``password_changed_at`` are all useful
        and none of them is a secret; a denylist that hides them gets worked around.
        """
        source = inspect.getsource(admin_database)
        assert "re.compile" not in source
        for harmless in ("prompt_tokens", "content_hash", "password_changed_at"):
            assert harmless not in str(admin_database.REDACTED_COLUMNS), harmless


class TestNoSqlComesFromTheCaller:
    def test_there_is_no_query_or_filter_parameter(self):
        """Not a SQL box, not a WHERE clause, not an ORDER BY expression.

        "Admin only" is not a defence: it turns one stolen session into arbitrary read
        access across every tenant.
        """
        for handler in (admin_database.list_tables, admin_database.read_table):
            params = set(inspect.signature(handler).parameters)
            for forbidden in ("sql", "query", "where", "filter", "order_by", "columns"):
                assert forbidden not in params, f"{handler.__name__} accepts {forbidden}"

    def test_a_table_name_is_resolved_against_the_catalogue(self):
        """An identifier cannot be parameterised, so it must be matched, then quoted."""
        source = inspect.getsource(admin_database._resolve_table)
        assert "HTTP_404_NOT_FOUND" in source
        # The value used downstream comes from the catalogue, not from the request.
        assert "next(name for name in known if name == table)" in source

    def test_the_reader_resolves_before_it_builds_sql(self):
        source = inspect.getsource(admin_database.read_table)
        assert source.index("_resolve_table(") < source.index("quoted_table")

    def test_identifiers_are_quoted_by_the_dialect(self):
        source = inspect.getsource(admin_database.read_table)
        assert "identifier_preparer" in source
        assert "preparer.quote(" in source

    def test_only_base_tables_in_public_are_offered(self):
        """So `pg_shadow` and other catalogue tables are simply not addressable."""
        source = inspect.getsource(admin_database._tables)
        assert "nspname = 'public'" in source
        assert "relkind = 'r'" in source

    def test_paging_is_parameterised(self):
        source = inspect.getsource(admin_database.read_table)
        assert ":lim" in source and ":off" in source
        assert "LIMIT :lim OFFSET :off" in source


class TestItIsReadOnly:
    def test_the_module_issues_no_writes(self):
        """A direct UPDATE here would produce a value with no provenance.

        Which is the one thing the platform promises never to hold, so corrections go
        through the service layer instead.

        Checks the SQL the module actually builds - every string handed to ``text()`` -
        rather than the file's prose, which discusses writes in order to rule them out.
        """
        tree = ast.parse(pathlib.Path(admin_database.__file__).read_text(encoding="utf-8"))
        statements: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "text"
                and node.args
            ):
                literal = node.args[0]
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    statements.append(literal.value.upper())
                elif isinstance(literal, ast.JoinedStr):
                    # An f-string: only the literal halves are ours to inspect, and the
                    # interpolated halves are quoted identifiers, never keywords.
                    statements.append(
                        " ".join(
                            part.value.upper()
                            for part in literal.values
                            if isinstance(part, ast.Constant) and isinstance(part.value, str)
                        )
                    )
        assert statements, "expected SQL in the module"
        for sql in statements:
            assert sql.lstrip().startswith("SELECT"), sql[:80]
            for write in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALTER", "DROP"):
                assert write not in sql, f"{write} in {sql[:80]}"

    def test_only_get_routes_exist(self):
        methods = {method for route in admin_database.router.routes for method in route.methods}
        assert methods == {"GET"}, methods


class TestItSaysWhatItIsShowing:
    def test_reading_a_table_is_audited(self):
        """Browsing raw rows is exactly what read_sensitive is for."""
        source = inspect.getsource(admin_database.read_table)
        assert "READ_SENSITIVE" in source
        assert "record_audit" in source

    def test_the_listing_admits_its_counts_are_estimates(self):
        """36 exact counts is 36 round trips just to draw a list."""
        source = inspect.getsource(admin_database.list_tables)
        assert "row_counts_are_estimates" in source

    def test_the_listing_admits_it_crosses_tenants(self):
        """A viewer that looks tenant-scoped while showing every tenant is worse."""
        source = inspect.getsource(admin_database.list_tables)
        assert "scope" in source

    def test_an_unordered_table_is_reported_as_such(self):
        """Without a single-column primary key, paging order is not guaranteed."""
        source = inspect.getsource(admin_database.read_table)
        assert "ordered_by" in source
        assert "indisprimary" in source

    def test_the_page_size_is_capped(self):
        """Rows here are wide - one spec table has 161 columns - and the database is
        remote, so an uncapped limit is a denial of service against your own API."""
        assert admin_database.MAX_LIMIT <= 500
        assert admin_database.DEFAULT_LIMIT <= admin_database.MAX_LIMIT
