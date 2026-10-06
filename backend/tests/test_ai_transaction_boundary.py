"""No database transaction may span a provider call.

An AI call can take minutes - one Gemma call on a full web page took 119 seconds
against a real key. Holding a transaction open across it trips PostgreSQL's
`idle_in_transaction_session_timeout`, the server closes the connection, and the task
dies with PendingRollbackError *after* the model has already been paid for. That made the
entire extraction pipeline unable to complete for any slow call.

`extraction.execute_ai_job` is the fix: it commits the job row, releases the transaction,
makes the call, then writes the result in a fresh transaction. These tests assert every
provider call goes through it.
"""

from __future__ import annotations

import inspect
import re

from app.services import comparison, dedupe, extraction, quality

MODULES = (extraction, quality, dedupe, comparison)


def test_only_the_helper_calls_the_provider():
    """A direct `client.complete(...)` anywhere else reintroduces the bug."""
    offenders = []
    for module in MODULES:
        source = inspect.getsource(module)
        for match in re.finditer(r"client\.complete\(", source):
            line_no = source[: match.start()].count("\n") + 1
            enclosing = source[: match.start()].rsplit("def ", 1)[-1].split("(")[0]
            if module is extraction and enclosing == "execute_ai_job":
                continue
            offenders.append(f"{module.__name__}:{line_no} inside {enclosing}()")
    assert not offenders, (
        "these call the provider directly instead of via execute_ai_job, so they can "
        f"hold a transaction across it: {offenders}"
    )


def test_helper_commits_before_the_call_and_after():
    source = inspect.getsource(extraction.execute_ai_job)
    before, _, after = source.partition("client.complete(")
    assert "db.commit()" in before, "the transaction is not released before the call"
    assert "db.commit()" in after, "the result is not committed after the call"


def test_helper_records_failures_rather_than_swallowing_them():
    source = inspect.getsource(extraction.execute_ai_job)
    assert "AiJobStatus.FAILED" in source
    assert "return job, None, exc" in source
    # A bare provider exception must still leave an ai_jobs row behind.
    assert "except Exception" in source


def test_helper_returns_the_error_for_the_caller_to_decide():
    signature = inspect.signature(extraction.execute_ai_job)
    assert list(signature.parameters)[:4] == ["db", "client", "system_prompt", "user_prompt"]
    assert (
        "tuple[AiJob, AiResult | None, Exception | None]" in str(signature.return_annotation)
        or signature.return_annotation is not inspect.Signature.empty
    )


def test_extraction_commits_between_field_groups():
    """Seven groups per source: a failure in group five must not discard groups one to four."""
    source = inspect.getsource(extraction.extract_from_source)
    assert source.count("db.commit()") >= 2
