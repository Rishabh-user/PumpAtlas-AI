"""Ask a question; get an answer from the record and the web, with citations.

Two routes, and the split between them is the point:

* ``/chat/ask`` reads. It searches what is held, searches the web, and has the active
  reading model compose an answer citing both. It writes nothing.
* ``/chat/capture`` writes - by starting an ordinary discovery run. The chat does not
  store anything itself, because a model's prose is not evidence: a stored field has to
  carry a verbatim quote from a page PumpAtlas fetched, and that is what capture does.

So the chat can lead to new records, but only down the same path `/pumps` and `/vendors`
use, with the same provenance gate and the same review queue.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.deps import CurrentPrincipal, DbSession, require
from app.core.logging import get_logger
from app.services import chat, discovery, dispatch, pump_discovery, vendor_discovery
from app.workers import tasks

log = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=1000)
    use_web: bool = Field(
        default=True,
        description=(
            "Search the web as well as the held records. Turn it off for a faster answer "
            "from what the platform already holds."
        ),
    )


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=3,
        max_length=160,
        description="Used as the discovery query, so the run is labelled with what was asked",
    )
    kind: str = Field(default="pump", description="pump | vendor")
    max_results: int = Field(default=4, ge=1, le=25)
    urls: list[str] = Field(
        default_factory=list,
        max_length=discovery.MAX_SEED_URLS,
        description=(
            "Pages to read, normally the ones the answer cited. Given these, the run "
            "reads them instead of searching again - the answer already searched, and "
            "asking the same question twice returns a different set of pages."
        ),
    )
    auto_store: bool = Field(
        default=False,
        description=(
            "Write confident candidates straight into the record. Off by default: the "
            "chat found these, but nothing has read the pages yet."
        ),
    )


#: The copy every Ask screen shows before the first question.
#:
#: Served rather than hard-coded in a frontend, because there is more than one
#: frontend: this platform's own Ask page and the client deployments that reach
#: the same endpoint through their own backend. Two hard-coded lists meant the
#: same product suggested different questions depending on which door you came
#: in by, and drifted further with every edit.
#:
#: So this is the presentation contract. Editing a prompt here changes it
#: everywhere, with no consumer deploy — which is the whole point of the
#: endpoint's original promise: "what the screen needs before the first
#: question".
#:
#: The examples are chosen against what the catalogue can answer. The reading
#: model answers strictly from retrieved records and says "not stated"
#: otherwise, so a general engineering question comes back empty and reads as a
#: broken assistant. These do not.
ASK_SCREEN = {
    "title": "Ask about pumps, vendors, duties or standards",
    "lede": (
        "Answers are built from the records this platform holds and, when a "
        "provider is active, from a live web search. Every claim is marked with "
        "where it came from — [R1] for a held record, [W1] for a web page. Click "
        "a marker to open what it points at. Asking itself writes nothing."
    ),
    "placeholder": "Ask about a pump, a duty, a vendor or a standard…",
    # One list, shared with the greeting the assistant gives when someone opens
    # with "hi" - two copies of these drifted apart once already.
    "examples": chat.EXAMPLE_QUESTIONS,
}


@router.get("/context", dependencies=[Depends(require("search", "read"))])
def context(principal: CurrentPrincipal, db: DbSession) -> dict[str, Any]:
    """What the screen needs before the first question, so it can set expectations."""
    return {
        "web_available": chat.web_is_available(db),
        "kinds": ["pump", "vendor"],
        **ASK_SCREEN,
    }


@router.post("/ask", dependencies=[Depends(require("search", "read"))])
def ask(payload: AskRequest, principal: CurrentPrincipal, db: DbSession) -> dict[str, Any]:
    """Answer a question. Reads only."""
    result = chat.answer(
        db,
        payload.question.strip(),
        use_web=payload.use_web,
        tenant_id=principal.tenant_id,
    )
    log.info(
        "chat.answered",
        records=len(result.get("records") or []),
        web=len(result.get("web") or []),
        new=len(result.get("new_on_web") or []),
        answered=bool(result.get("answer")),
    )
    return result


@router.post(
    "/capture",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def capture(payload: CaptureRequest, principal: CurrentPrincipal, db: DbSession) -> dict[str, Any]:
    """Start a discovery run for what the chat turned up.

    Deliberately the ordinary pipeline: search, fetch each page, have the reading model
    extract fields with evidence, then either queue for review or store. The chat's own
    answer plays no part in what gets written.

    A separate permission from asking, because this one spends money and writes rows.
    """
    kind = payload.kind.strip().lower()
    if kind == "pump":
        discovery_kind = pump_discovery.KIND
    elif kind == "vendor":
        discovery_kind = vendor_discovery.KIND
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown kind {payload.kind!r}. Expected 'pump' or 'vendor'.",
        )

    objective, queries = discovery_kind.build_objective(payload.question.strip(), None)
    batch = discovery.start_run(
        db,
        discovery_kind,
        tenant_id=principal.tenant_id,
        query=payload.question.strip(),
        country=None,
        objective=objective,
        max_results=payload.max_results,
        user_id=principal.user_id,
        sweep=False,
        auto_store=payload.auto_store,
        transport=None,
        urls=payload.urls,
    )
    db.commit()

    outcome = dispatch.dispatch(
        celery_task=tasks.discovery_task,
        # The kind travels as a slug because a Celery argument has to survive JSON.
        celery_args=(
            discovery_kind.slug,
            str(batch.id),
            str(principal.tenant_id) if principal.tenant_id else None,
            str(principal.user_id) if principal.user_id else None,
        ),
        fallback=_runner(discovery_kind),
        fallback_kwargs={"batch_id": batch.id, "user_id": principal.user_id},
        tenant_id=principal.tenant_id,
        name=f"chat-{kind}-discovery",
    )
    discovery.record_transport(db, batch.id, outcome["transport"], outcome["task_id"])
    db.commit()

    return {
        "run_id": str(batch.id),
        "kind": kind,
        # Empty when pages were supplied: nothing was searched for.
        "queries": [] if payload.urls else queries,
        "transport": outcome.get("transport"),
        # So the screen can link to the run rather than reimplementing progress.
        "watch": f"/{kind}s",
    }


def _runner(kind: Any):
    """Bind the kind for the in-process fallback, which passes only ids."""

    def run(db: Any, *, batch_id: Any, user_id: Any) -> Any:
        return discovery.run_discovery(db, kind, batch_id, user_id)

    return run
