"""Parallel AI client - web search orchestration and result aggregation.

Parallel AI is the discovery layer: it runs the web searches that find vendor pages,
datasheets and press releases, and returns ranked results with excerpts. Everything it
returns is written to ``sources`` before any extraction happens, so the crawl is
auditable and re-runnable.

The response normaliser accepts the documented Search API shape plus the common
variants rather than assuming one exact envelope, because the API is versioned beta.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.ai import timeouts
from app.core.config import settings
from app.core.countries import PUMP_SUPPLY_COUNTRIES, country_name
from app.core.logging import get_logger

log = get_logger(__name__)


class SearchUnavailableError(RuntimeError):
    """Raised when Parallel AI is not configured or unreachable."""


@dataclass
class SearchExcerpt:
    text: str
    locator: str | None = None


@dataclass
class SearchResult:
    url: str
    title: str | None
    excerpts: list[SearchExcerpt] = field(default_factory=list)
    published_at: str | None = None
    rank: int | None = None
    score: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def combined_excerpt(self) -> str:
        return "\n\n".join(e.text for e in self.excerpts if e.text)


@dataclass
class SearchRun:
    search_id: str | None
    objective: str
    queries: list[str]
    results: list[SearchResult]
    latency_ms: int
    raw_response: dict[str, Any] = field(default_factory=dict)


class ParallelSearchClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.PARALLEL_API_KEY
        self.base_url = (base_url or settings.PARALLEL_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.PARALLEL_TIMEOUT_SECONDS
        self.search_path = "/v1beta/search"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key or "", "Content-Type": "application/json"}

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=timeouts.bounded(self.timeout)) as client:
            response = client.post(f"{self.base_url}{path}", headers=self._headers(), json=payload)
        if response.status_code == 429:
            raise SearchUnavailableError("Parallel AI rate limit reached")
        if response.status_code >= 500:
            raise SearchUnavailableError(f"Parallel AI upstream error {response.status_code}")
        if response.status_code >= 400:
            raise SearchUnavailableError(f"Parallel AI rejected the request: {response.text[:500]}")
        return response.json()

    def search(
        self,
        objective: str,
        queries: list[str] | None = None,
        *,
        max_results: int | None = None,
        processor: str = "base",
        max_chars_per_result: int = 6000,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> SearchRun:
        """Run one search. ``objective`` is the natural-language research goal."""
        if not self.configured:
            raise SearchUnavailableError(
                "Parallel AI is not configured. Set PARALLEL_API_KEY to enable web discovery."
            )

        payload: dict[str, Any] = {
            "objective": objective,
            "processor": processor,
            "max_results": max_results or settings.PARALLEL_MAX_RESULTS,
            "max_chars_per_result": max_chars_per_result,
        }
        if queries:
            payload["search_queries"] = queries[:5]
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        started = time.perf_counter()
        body = self._post(self.search_path, payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        results = self._normalise_results(body)
        log.info(
            "parallel.search_complete",
            objective=objective[:120],
            results=len(results),
            latency_ms=latency_ms,
        )
        return SearchRun(
            search_id=body.get("search_id") or body.get("id"),
            objective=objective,
            queries=queries or [],
            results=results,
            latency_ms=latency_ms,
            raw_response=body,
        )

    @staticmethod
    def _normalise_results(body: dict[str, Any]) -> list[SearchResult]:
        rows = body.get("results")
        if rows is None:
            rows = body.get("data") or body.get("items") or []
        out: list[SearchResult] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            url = row.get("url") or row.get("link")
            if not url:
                continue
            raw_excerpts = row.get("excerpts") or row.get("snippets") or []
            if isinstance(raw_excerpts, str):
                raw_excerpts = [raw_excerpts]
            excerpts: list[SearchExcerpt] = []
            for item in raw_excerpts:
                if isinstance(item, str):
                    excerpts.append(SearchExcerpt(text=item))
                elif isinstance(item, dict):
                    excerpts.append(
                        SearchExcerpt(text=str(item.get("text", "")), locator=item.get("locator"))
                    )
            if not excerpts and row.get("content"):
                excerpts = [SearchExcerpt(text=str(row["content"]))]
            out.append(
                SearchResult(
                    url=url,
                    title=row.get("title") or row.get("name"),
                    excerpts=excerpts,
                    published_at=row.get("published_date") or row.get("published_at"),
                    rank=row.get("rank", index + 1),
                    score=row.get("score") or row.get("relevance"),
                    raw=row,
                )
            )
        return out


# ---------------------------------------------------------------------------
# Domain-specific search recipes. Keeping the query wording here means the
# Oil & Gas framing is consistent everywhere discovery is triggered.
# ---------------------------------------------------------------------------


def vendor_discovery_objective(subject: str, country: str | None = None) -> tuple[str, list[str]]:
    """Find companies that supply Oil & Gas pumps.

    ``subject`` is whatever the run is sweeping over: a pump type ("API 610 BB3
    multistage") for a type sweep, or a phrase naming a country for a country sweep. Both
    read as English in the objective, which is what the provider is answering.
    """
    place = country_name(country) or country
    where = f" with manufacturing, packaging or service presence in {place}" if place else ""
    objective = (
        f"Identify companies that manufacture or supply {subject} for Oil & Gas "
        f"service{where}. Include OEMs, licensed packagers and authorised service "
        "centres. For each, capture the legal entity name, headquarters city and "
        "country, website, the pump types and API/ISO standards it covers, its "
        "certifications and any offshore or FPSO references. Prioritise company and "
        "OEM websites over directories, marketplaces and news."
    )
    # The place goes in every query, not just one: a country sweep whose queries do not
    # name the country is 60 searches for the same global OEMs.
    at = f" in {place}" if place else ""
    queries = [
        f"{subject} manufacturer API 610 oil and gas{at}",
        f"{subject} supplier offshore FPSO reference list{at}",
        f"{subject} company ISO 9001 API certification{at or ' global'}",
    ]
    return objective, queries


def pump_discovery_objective(duty: str, country: str | None = None) -> tuple[str, list[str]]:
    """Find pump *models* for a duty, rather than the companies that make them.

    Deliberately biased toward datasheets and performance curves: a product landing page
    names a model but rarely states capacity, head or NPSHr, and a model without a duty
    point is not worth a row in this database.
    """
    where = f" available from suppliers in {country}" if country else ""
    objective = (
        f"Find specific pump models and their technical datasheets for {duty} duty in "
        f"Oil & Gas service{where}. Each result should name a manufacturer and a model "
        "code and state performance data: rated capacity, head, NPSH required, "
        "efficiency, speed, materials and seal arrangement. Prefer OEM datasheets, "
        "performance curves and API 610 / ISO 13709 product pages over brochures, "
        "directories and marketplaces."
    )
    region = f" {country}" if country else ""
    queries = [
        f"{duty} pump datasheet capacity head NPSH pdf",
        f"{duty} pump model API 610 performance curve",
        f"{duty} pump technical specification materials seal plan{region}",
    ]
    return objective, queries


def vendor_range_objective(vendor_name: str) -> tuple[str, list[str]]:
    """Find the pump models a manufacturer actually sells.

    The question to ask when a record has no product designation to search for. A
    datasheet hunt needs a model code; this needs only the company, and what comes back
    are the products themselves - which is what the placeholder row was standing in for.
    """
    objective = (
        f"Find the pump models {vendor_name} manufactures or packages for Oil & Gas "
        "service. Each result should name a model or product-series designation and "
        "state what it is: pump type or API 610 configuration, the duty it is built for, "
        "and any performance data given. Prefer the manufacturer's own product pages and "
        "datasheets over directories, marketplaces and news."
    )
    queries = [
        f"{vendor_name} pump product range models",
        f"{vendor_name} API 610 pump model datasheet",
        f"{vendor_name} pumps series specification oil gas",
    ]
    return objective, queries


def vendor_intelligence_objective(vendor_name: str) -> tuple[str, list[str]]:
    objective = (
        f"Collect procurement-relevant intelligence on the pump supplier {vendor_name}: "
        "legal entity and registration, manufacturing locations, API/ISO and marine "
        "certifications, offshore and FPSO references, service network, financial "
        "standing, HSE record and ESG disclosures. Prefer primary sources."
    )
    queries = [
        f"{vendor_name} pumps company profile manufacturing locations",
        f"{vendor_name} API 610 ISO 9001 certification pumps",
        f"{vendor_name} FPSO offshore pump reference list",
        f"{vendor_name} annual report revenue",
    ]
    return objective, queries


def pump_model_objective(vendor_name: str, model_code: str) -> tuple[str, list[str]]:
    objective = (
        f"Find the technical datasheet and performance data for the {vendor_name} "
        f"{model_code} pump: capacity, head, NPSH required, efficiency, speed, "
        "materials of construction, seal plan, weights and dimensions."
    )
    queries = [
        f"{vendor_name} {model_code} pump datasheet pdf",
        f"{vendor_name} {model_code} performance curve capacity head NPSH",
        f"{vendor_name} {model_code} weight dimensions materials",
    ]
    return objective, queries


def get_parallel_client() -> ParallelSearchClient:
    return ParallelSearchClient()


# ------------------------------------------------------------------------- sweeps

#: Search phrasing for every pump type the platform recognises.
#:
#: A sweep exists because there is no "fetch the whole web" call to make: Parallel AI, like
#: every retrieval API, answers an objective. What it *can* do is answer a lot of them, so
#: instead of asking the user to imagine every duty, the segments are generated from the
#: controlled vocabulary the database already enforces. That makes coverage a property of
#: the domain model rather than of somebody's memory.
#:
#: ``other`` is deliberately absent: it is the escape hatch for a type the platform does
#: not model, so there is no useful query for it.
PUMP_TYPE_PHRASES: dict[str, str] = {
    "centrifugal_oh1": "API 610 OH1 foot-mounted overhung centrifugal pump",
    "centrifugal_oh2": "API 610 OH2 centreline-mounted overhung process pump",
    "centrifugal_oh3": "API 610 OH3 vertical in-line pump",
    "centrifugal_oh5": "API 610 OH5 close-coupled vertical in-line pump",
    "centrifugal_oh6": "API 610 OH6 high-speed integrally geared pump",
    "between_bearings_bb1": "API 610 BB1 axially split single-stage between-bearings pump",
    "between_bearings_bb2": "API 610 BB2 radially split single-stage between-bearings pump",
    "between_bearings_bb3": "API 610 BB3 axially split multistage pump",
    "between_bearings_bb4": "API 610 BB4 radially split multistage pump",
    "between_bearings_bb5": "API 610 BB5 barrel casing multistage pump",
    "vertically_suspended_vs1": "API 610 VS1 vertical wet-pit diffuser pump",
    "vertically_suspended_vs4": "API 610 VS4 vertical line-shaft sump pump",
    "vertically_suspended_vs6": "API 610 VS6 vertical double-casing can pump",
    "submersible": "submersible pump for Oil & Gas service",
    "reciprocating_plunger": "API 674 reciprocating plunger pump",
    "reciprocating_diaphragm": "API 675 controlled-volume diaphragm pump",
    "rotary_screw": "API 676 rotary twin-screw pump",
    "rotary_gear": "API 676 rotary internal gear pump",
    "rotary_progressive_cavity": "progressive cavity pump for crude and heavy oil",
    "metering_dosing": "API 675 chemical injection metering pump",
    "multiphase": "subsea multiphase booster pump",
    "esp": "electrical submersible pump ESP for oil wells",
    "firewater": "NFPA 20 firewater pump for offshore platforms",
}


#: The duties an Oil & Gas pump is bought for, as a person in procurement would say
#: them.
#:
#: This exists because "what should I type to find a supplier?" has no good answer. A
#: buyer knows the duty - they are replacing a crude export pump, or specifying chemical
#: injection for a new well - and rarely knows which manufacturers serve it; that is the
#: whole reason to search. So the form offers duties, and composes the query itself.
#:
#: Phrases rather than codes: this text goes into a search objective, which a provider
#: answers as prose.
SERVICE_PHRASES: dict[str, str] = {
    "crude_export": "crude oil export and shipping",
    "pipeline_transfer": "pipeline transfer and booster duty",
    "water_injection": "water injection for reservoir pressure maintenance",
    "produced_water": "produced water handling and re-injection",
    "chemical_injection": "chemical injection and metering",
    "refinery_process": "refinery and petrochemical process duty",
    "hot_oil": "hot oil and thermal transfer",
    "lng": "LNG liquefaction and cryogenic transfer",
    "fpso_topside": "FPSO and offshore topside duty",
    "subsea_boosting": "subsea multiphase boosting",
    "well_service": "well service, drilling and mud circulation",
    "amine_sweetening": "amine circulation and gas sweetening",
    "sour_service": "sour service to NACE MR0175",
    "firewater": "offshore firewater and deluge",
    "tank_farm": "tank farm and terminal loading",
    "condensate": "condensate and light hydrocarbon transfer",
}


@dataclass
class SweepSegment:
    """One search in a sweep: a label for progress, plus the query it stands for.

    ``country`` is set by an axis that *is* a country, so the objective can name it as a
    place instead of having it pasted into the subject - "supply pumps ... in Norway",
    not "supply Oil & Gas pump suppliers in Norway for Oil & Gas service".
    """

    key: str
    label: str
    query: str
    country: str | None = None


def pump_type_segments(
    country: str | None = None, countries: Sequence[str] | None = None
) -> list[SweepSegment]:
    """One segment per pump type in the platform's vocabulary.

    Takes `countries` it does not use: every sweep axis shares one signature so
    `DiscoveryKind.segments_for` can call whichever is configured without knowing which.
    """
    del countries
    where = f" {country}" if country else ""
    return [
        SweepSegment(key=key, label=phrase, query=f"{phrase}{where}")
        for key, phrase in PUMP_TYPE_PHRASES.items()
    ]


def country_segments(
    country: str | None = None, countries: Sequence[str] | None = None
) -> list[SweepSegment]:
    """One segment per country, for finding *suppliers* rather than pump models.

    Sweeping pump types finds the same global OEMs again and again: a search for "API 610
    BB3 multistage" returns Sulzer, Flowserve and Ruhrpumpen whichever way it is phrased.
    The vendors nobody has heard of are regional - a packager in Abu Dhabi, a foundry in
    Coimbatore - and the way to reach them is to ask per country, because that is the axis
    the provider's index is actually organised along.

    Defaults to :data:`PUMP_SUPPLY_COUNTRIES`, in its order, so a run cancelled half way
    through has covered the countries that matter first.
    """
    if isinstance(countries, str):
        # A single code arriving where a list is expected would otherwise be iterated
        # character by character, sweeping the countries "A" and "E".
        countries = [countries]
    selected = (
        list(countries) if countries else [country] if country else list(PUMP_SUPPLY_COUNTRIES)
    )
    return [
        SweepSegment(
            key=code.lower(),
            label=country_name(code) or code,
            # The subject stays neutral and the place travels in `country`, so the
            # objective reads "supply pumps ... in Norway" rather than "supply Oil & Gas
            # pump suppliers in Norway for Oil & Gas service".
            query="pumps",
            country=code,
        )
        for code in selected
    ]
