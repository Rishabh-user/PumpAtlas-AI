"""OpenAI web search, as an alternative to Parallel AI for finding candidate pages.

Reading a page with OpenAI needs no code of its own - the Chat Completions contract is
what :class:`app.ai.openrouter.OpenRouterClient` already speaks, so pointing it at
``api.openai.com`` is configuration. Searching does need code: the web search tool lives
on the Responses API, which has a different request and reply shape, and the URLs come
back as citation annotations rather than as a result list.

Returns the same :class:`app.ai.parallel_search.SearchRun` Parallel AI does, so the
capture and provenance stages downstream cannot tell which provider found the page.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai import timeouts
from app.ai.openrouter import AiResponseError, AiUnavailableError
from app.ai.parallel_search import SearchResult, SearchRun, SearchUnavailableError
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class OpenAiWebSearchClient:
    """Finds candidate pages using OpenAI's hosted web search tool."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.model = model or settings.OPENAI_MODEL
        self.timeout = timeout or settings.OPENAI_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(settings.AI_ENABLED and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(settings.OPENROUTER_MAX_RETRIES),
        wait=wait_exponential(multiplier=1.5, min=2, max=20),
        reraise=True,
    )
    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=timeouts.bounded(self.timeout)) as http:
                response = http.post(
                    f"{self.base_url}/responses", headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise AiUnavailableError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            raise AiResponseError(f"OpenAI returned {response.status_code}: {response.text[:400]}")
        return response.json()

    def search(
        self,
        objective: str,
        queries: list[str] | None = None,
        *,
        max_results: int = 10,
    ) -> SearchRun:
        if not self.configured:
            raise SearchUnavailableError(
                "OpenAI is not configured. Set OPENAI_API_KEY, or point SEARCH_PROVIDER "
                "at a provider that is configured."
            )

        asked = queries or []
        instruction = (
            "Search the web and list the pages that best satisfy this objective. "
            "Prefer manufacturer datasheets, product pages and technical documents "
            "over directories, marketplaces and news. Cite every page you use.\n\n"
            f"Objective: {objective}"
        )
        if asked:
            instruction += "\n\nSuggested searches:\n" + "\n".join(f"- {q}" for q in asked)

        payload = {
            "model": self.model,
            "tools": [{"type": "web_search"}],
            "input": instruction,
        }

        started = time.perf_counter()
        body = self._post_responses(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        return SearchRun(
            search_id=body.get("id"),
            objective=objective,
            queries=asked,
            results=_results_from_citations(body, max_results),
            latency_ms=latency_ms,
            raw_response=body,
        )


def _results_from_citations(body: dict[str, Any], max_results: int) -> list[SearchResult]:
    """Pull the cited pages out of a Responses reply.

    The pages the model actually used appear as ``url_citation`` annotations on the
    message content, not as a search-result list - so the citations *are* the result
    set. De-duplicated by URL and ranked in the order cited.
    """
    found: list[SearchResult] = []
    seen: set[str] = set()

    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            for annotation in part.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                if annotation.get("type") != "url_citation":
                    continue
                url = (annotation.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                found.append(
                    SearchResult(
                        url=url,
                        title=annotation.get("title"),
                        rank=len(found) + 1,
                        raw=annotation,
                    )
                )
                if len(found) >= max_results:
                    return found
    return found
