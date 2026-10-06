"""Audit snapshots go into JSONB columns.

Every type below once caused, or would cause, psycopg to refuse the write with
"Object of type X is not JSON serializable" - which fails the whole spec write, not just
the audit row. A plain `date` did exactly that: `data_submission_date` is set on every
new spec version, so no spec could be written at all.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from ipaddress import IPv4Address

from app.models.enums import AuditAction, ConfidenceLevel
from app.services.audit import _jsonable, diff


def assert_json_safe(value):
    rendered = _jsonable(value)
    json.dumps(rendered)  # raises if psycopg would have refused it
    return rendered


def test_plain_date_is_serialised():
    assert assert_json_safe(date(2026, 3, 14)) == "2026-03-14"


def test_datetime_is_serialised_and_not_shadowed_by_date():
    """datetime subclasses date, so the isinstance order matters."""
    moment = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)
    assert assert_json_safe(moment).startswith("2026-03-14T09:30")


def test_time_and_timedelta():
    assert assert_json_safe(time(14, 5)) == "14:05:00"
    assert assert_json_safe(timedelta(hours=2)) == 7200.0


def test_decimal_keeps_full_precision_as_a_string():
    # A float would silently round a price in the audit trail.
    assert assert_json_safe(Decimal("310000.55")) == "310000.55"


def test_enum_members_become_their_value():
    assert assert_json_safe(ConfidenceLevel.VERIFIED) == "verified"
    assert assert_json_safe(AuditAction.AI_SUGGESTION_APPLIED) == "ai_suggestion_applied"


def test_uuid_and_ip_address():
    identifier = uuid.uuid4()
    assert assert_json_safe(identifier) == str(identifier)
    assert assert_json_safe(IPv4Address("10.1.2.3")) == "10.1.2.3"


def test_nested_structures_are_walked():
    payload = {
        "duty": {"capacity": Decimal("305.5"), "captured": date(2026, 1, 2)},
        "certs": ["ATEX", ConfidenceLevel.VENDOR_DECLARED],
        "ids": (uuid.uuid4(),),
    }
    rendered = assert_json_safe(payload)
    assert rendered["duty"]["capacity"] == "305.5"
    assert rendered["duty"]["captured"] == "2026-01-02"
    assert rendered["certs"][1] == "vendor_declared"


def test_bytes_are_summarised_not_embedded():
    assert assert_json_safe(b"\x00\x01\x02") == "<3 bytes>"


def test_unknown_objects_fall_back_to_str():
    class Odd:
        def __str__(self) -> str:
            return "odd-object"

    assert assert_json_safe(Odd()) == "odd-object"


def test_diff_is_json_safe_and_drops_updated_at():
    before = {"rated_head_m": Decimal("138"), "updated_at": datetime.now(UTC)}
    after = {"rated_head_m": Decimal("141.5"), "updated_at": datetime.now(UTC)}
    changes = diff(before, after)
    assert "updated_at" not in changes
    assert changes["rated_head_m"]["from"] == Decimal("138")
    json.dumps(_jsonable(changes))
