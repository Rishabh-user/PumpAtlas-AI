"""AI discovery payloads, shared by vendor and pump discovery."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.countries import is_country

#: The axes a sweep can run along. Not every kind offers both - `DiscoveryKind` decides,
#: and the API reports what it accepted - but the request shape is shared.
SWEEP_SCOPES = ("country", "pump_type")

#: A country sweep is one search and up to `max_results` pages per country, so the list
#: is what actually sets the size of the run. 249 countries at 10 pages each is 2,490
#: reading-model calls; this cap keeps a mistyped request from becoming a day of them.
MAX_SWEEP_COUNTRIES = 80


class DiscoveryStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        min_length=2,
        max_length=160,
        description=(
            "What to search for. For vendors, a pump type the supplier makes; for pumps, "
            'the duty, e.g. "API 610 BB3 multistage" or "ESP electrical submersible". '
            "Required unless `sweep` is set."
        ),
    )
    sweep: bool = Field(
        default=False,
        description=(
            "Search a whole axis instead of one query: every pump type, or every country. "
            "`query` is ignored and `max_results` becomes per-segment, so the run makes "
            "one search per segment and reads every unique page it finds."
        ),
    )
    sweep_scope: str | None = Field(
        default=None,
        description=(
            "Which axis to sweep. 'country' asks one search per country, which is how "
            "regional suppliers are found - sweeping pump types returns the same global "
            "OEMs from every angle. 'pump_type' asks one per type in the vocabulary. "
            "Omit for the kind's default: country for vendors, pump type for pumps."
        ),
    )
    countries: list[str] = Field(
        default_factory=list,
        max_length=MAX_SWEEP_COUNTRIES,
        description=(
            "Restrict a country sweep to these ISO 3166-1 alpha-2 codes. Empty means the "
            "countries that actually supply Oil & Gas pumps, in order of how much of the "
            "market sits there, so a cancelled run has covered the ones that matter."
        ),
    )
    auto_store: bool = Field(
        default=False,
        description=(
            "Write each confident candidate straight into the system of record instead "
            "of queueing it for you to pick. This is how a sweep populates the database "
            "unattended. Nothing bypasses the provenance gate: every field still needs a "
            "verbatim evidence quote from the captured page, and a candidate whose "
            "subject name is unusable is left for review rather than stored."
        ),
    )
    min_confidence: float = Field(
        default=0.85,
        ge=0.5,
        le=1.0,
        description=(
            "With `auto_store`, the confidence a candidate needs before it is written. "
            "Below it the candidate waits in the review queue, which is where a doubtful "
            "reading belongs."
        ),
    )
    country: str | None = Field(
        default=None,
        max_length=2,
        description="ISO 3166-1 alpha-2, to bias the search toward a region",
    )
    objective: str | None = Field(
        default=None,
        max_length=1000,
        description="Override the generated research objective sent to Parallel AI",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description=(
            "Pages per search, capped by what the provider returns for one objective. For "
            "a sweep this is per segment, not in total: breadth comes from the number of "
            "segments, which is why a country sweep reaches further than a bigger number "
            "here ever could."
        ),
    )

    @field_validator("country")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("countries")
    @classmethod
    def _known_countries(cls, value: list[str]) -> list[str]:
        """Refuse a code that is not a country rather than sweeping nothing for it.

        A typo here costs a whole segment - one search and up to 25 pages of reading -
        and the run would report it as a country that simply had no suppliers.
        """
        cleaned = [code.strip().upper() for code in value if code.strip()]
        unknown = sorted({code for code in cleaned if not is_country(code)})
        if unknown:
            raise ValueError(f"Not ISO 3166-1 alpha-2 country code(s): {', '.join(unknown)}")
        # Deduplicate, keeping the order given: it decides what a cancelled run covered.
        seen: list[str] = []
        for code in cleaned:
            if code not in seen:
                seen.append(code)
        return seen

    @model_validator(mode="after")
    def _needs_a_target(self):
        """A retrieval API needs something to retrieve. Either a query or a sweep."""
        if not self.sweep and not (self.query or "").strip():
            raise ValueError("Provide a query, or set sweep to search a whole axis")
        if self.sweep_scope is not None and self.sweep_scope not in SWEEP_SCOPES:
            raise ValueError(
                f"Unknown sweep_scope {self.sweep_scope!r}. Expected one of: "
                f"{', '.join(sorted(SWEEP_SCOPES))}."
            )
        if self.countries and (self.sweep_scope or "") != "country":
            raise ValueError(
                "countries only applies to a country sweep. Set sweep_scope='country', "
                "or use `country` to bias a single search."
            )
        return self


class DiscoveryStage(BaseModel):
    """One step of the run, as the UI renders it."""

    key: str
    provider: str | None = Field(
        default=None, description='"parallel" or "gemma"; null for platform-side work'
    )
    label: str
    status: str = Field(description="pending | running | done | failed | skipped")
    detail: str | None = None
    done: int = 0
    total: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class DiscoveryJob(BaseModel):
    provider: str | None = None
    prompt_name: str | None = None
    status: str
    model: str | None = None
    latency_ms: int | None = None
    error: str | None = None


class CandidateField(BaseModel):
    field_name: str
    label: str
    value: Any = None
    confidence: float | None = None
    evidence: str | None = None


class DiscoveryCandidate(BaseModel):
    id: uuid.UUID
    title: str | None = Field(default=None, description="Model code, or the supplier name")
    subtitle: str | None = Field(default=None, description="Manufacturer, or the country")
    vendor_name: str | None = None
    model_code: str | None = None
    pump_name: str | None = None
    website: str | None = None
    hq_country: str | None = None
    hq_city: str | None = None
    vendor_tier: str | None = None
    pump_type: str | None = None
    applicable_standard: str | None = None
    product_families: list[str] = Field(default_factory=list)
    overall_confidence: float | None = None
    relevance_reason: str | None = None
    oil_gas_evidence: str | None = None
    field_count: int = 0
    fields: list[CandidateField] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    source_url: str | None = None
    source_title: str | None = None
    decision: str = Field(description="pending | accepted | accepted_with_edits | rejected")
    blocked_reason: str | None = Field(
        default=None,
        description="Why storing this candidate would fail; null when it can be stored",
    )
    stored_as: str | None = Field(
        default=None,
        description=(
            "The designation this will actually be stored under, when it differs from "
            "the one on the page - an API type code is dropped from the name"
        ),
    )
    stored_id: uuid.UUID | None = Field(
        default=None, description="Set once the candidate has been stored"
    )
    matches_existing_id: uuid.UUID | None = Field(
        default=None,
        description="An existing record this candidate would enrich rather than create",
    )
    matches_existing_label: str | None = None


class DiscoveryRun(BaseModel):
    id: uuid.UUID
    kind: str = Field(description='"vendor" or "pump"')
    sweep: bool = False
    auto_store: bool = Field(
        default=False, description="Candidates were written without a human picking them"
    )
    segment_count: int = Field(default=1, description="Web searches this run makes")
    name: str
    status: str
    objective: str | None = None
    queries: list[str] = Field(default_factory=list)
    query: str | None = None
    country: str | None = None
    transport: str | None = Field(
        default=None, description='"celery" or "in_process" — how the run was dispatched'
    )
    is_running: bool
    cancel_requested: bool = False
    stages: list[DiscoveryStage] = Field(default_factory=list)
    jobs: list[DiscoveryJob] = Field(
        default_factory=list, description="Most recent provider calls, capped by the API"
    )
    job_count: int = Field(
        default=0, description="Provider calls this run has made, including those not listed"
    )
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    pages_found: int = 0
    pages_screened: int = 0
    pages_failed: int = 0
    candidate_count: int = 0
    stored_count: int = 0
    error_summary: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    edits: dict[str, Any] = Field(
        default_factory=dict,
        description="Reviewer corrections, applied over the extracted fields",
    )


class DiscoverySelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store: list[CandidateSelection] = Field(
        default_factory=list,
        max_length=50,
        description="Candidates to write into the system of record",
    )
    reject: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=50,
        description="Candidates to mark as not wanted",
    )


class StoredRecord(BaseModel):
    id: uuid.UUID | None = Field(default=None, description="The vendor or pump model written")
    label: str = ""
    candidate_id: uuid.UUID
    fields_applied: list[str] = Field(default_factory=list)
    fields_refused: dict[str, str] = Field(default_factory=dict)


class DiscoverySelectResponse(BaseModel):
    stored: list[StoredRecord] = Field(default_factory=list)
    rejected: list[uuid.UUID] = Field(default_factory=list)
    failed: dict[str, str] = Field(
        default_factory=dict, description="candidate_id -> why it could not be stored"
    )
