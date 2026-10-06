"""A derived row must be stamped with the tenant it was derived *for*.

Two bugs of this shape have already been shipped and found only against a live database,
because RLS is the thing that rejects them and RLS is inert for the owner role:

1. `comparison._upsert_score` took its tenant from `records.flatten_pump_model`, which
   has never emitted a `tenant_id` at all. Every scorecard was therefore inserted with
   `tenant_id = NULL` and every `POST /comparisons` without a requirement profile failed
   with "new row violates row-level security policy for table confidence_scores".

2. `audit.record_audit` wrote the caller-supplied host straight into an INET column, so
   any non-address value (a test client's "testclient", a misconfigured proxy's
   `X-Forwarded-For`) aborted the audit INSERT and took the audited request down with it.

Both are asserted here at the source and unit level, because neither is reachable from a
test that connects as the schema owner.
"""

from __future__ import annotations

import inspect

from app.services import audit, comparison, records


class TestScorecardTenant:
    def test_flattened_record_still_has_no_tenant_id(self):
        """The trap: if this ever changes, the comment in comparison.py is stale."""
        source = inspect.getsource(records.flatten_pump_model)
        assert '"tenant_id"' not in source, (
            "flatten_pump_model now emits tenant_id; revisit whether the scorecard owner "
            "should still come from the session rather than the record"
        )

    def test_scorecard_owner_comes_from_the_session_not_the_record(self):
        source = inspect.getsource(comparison.score_pump_model)
        assert "current_tenant_id(db)" in source, (
            "the scorecard tenant must come from the session's bound tenant; a "
            "shared-master pump model's own tenant_id is NULL"
        )
        assert 'record.get("tenant_id")' not in source, (
            "flatten_pump_model never emits tenant_id, so this always resolved to None "
            "and RLS rejected every insert"
        )

    def test_persistence_is_skipped_rather_than_inserting_a_null_tenant(self):
        """An unscoped platform admin cannot own a tenant-scoped row."""
        source = inspect.getsource(comparison.score_pump_model)
        assert (
            "if owner is not None:" in source
        ), "with no tenant bound, persisting would insert tenant_id=NULL and 500 again"


class TestAuditIpAddress:
    def test_addresses_are_preserved(self):
        assert audit._valid_ip("127.0.0.1") == "127.0.0.1"
        assert audit._valid_ip("  10.0.0.5  ") == "10.0.0.5"
        assert audit._valid_ip("::1") == "::1"

    def test_zone_index_is_stripped_because_inet_rejects_it(self):
        assert audit._valid_ip("fe80::1%eth0") == "fe80::1"

    def test_non_addresses_are_dropped_not_raised(self):
        for value in ("testclient", "unknown", "localhost", "1.2.3", "", None):
            assert audit._valid_ip(value) is None, value

    def test_the_writer_validates_before_inserting(self):
        source = inspect.getsource(audit.record_audit)
        assert (
            "ip_address=_valid_ip(ip_address)" in source
        ), "the raw value reaching an INET column aborts the whole INSERT"
