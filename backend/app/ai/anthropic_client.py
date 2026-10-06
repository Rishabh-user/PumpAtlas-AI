"""Anthropic client for page extraction, and for web search as a server tool.

Why this is a separate module rather than a base-URL change: OpenRouter and OpenAI both
speak chat-completions, so switching between those two is configuration. Anthropic's
Messages API is a different contract - the key travels in ``x-api-key`` rather than a
bearer token, a pinned ``anthropic-version`` header is mandatory, the system prompt is a
top-level field instead of a message, and the reply is a list of content blocks.

Two capabilities live here because they are the same endpoint:

* :class:`AnthropicClient` reads a captured page and returns candidate JSON, satisfying
  the same contract as :class:`app.ai.openrouter.OpenRouterClient` so the extraction
  service cannot tell them apart.
* :class:`AnthropicWebSearchClient` uses the server-side web search tool to *find*
  pages, returning the same :class:`app.ai.parallel_search.SearchRun` shape Parallel AI
  does, so the capture and provenance path downstream is unchanged.

Neither writes to the database. Both return candidates for the services layer to
validate, score and record with provenance, exactly as the rest of the assistant layer
does.
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
from app.ai.openrouter import (
    AiResponseError,
    AiResult,
    AiUnavailableError,
    extract_json,
)
from app.ai.parallel_search import (
    SearchResult,
    SearchRun,
    SearchUnavailableError,
)
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: Anthropic's hosted web search tool. Pinned because the name carries its version and
#: a different version is a different tool contract.
WEB_SEARCH_TOOL = "web_search_20250305"

#: Request features a given model refuses, learned from its own 400s.
#:
#: Two are in play, and each is wanted by some models and refused by others:
#:
#: * ``temperature`` - newer Claude models deprecate it; older ones need it, because
#:   their default is 1.0 and extraction has to be reproducible, so reading one source
#:   twice yields the same fields.
#: * ``prefill`` - seeding the assistant turn with "{" is the documented way to force a
#:   bare JSON object on an API with no ``response_format``. Newer models refuse it:
#:   "the conversation must end with a user message".
#:
#: Sending both and dropping whichever is refused keeps the strictest behaviour each
#: model allows, without a per-release list of model names that would be stale within
#: the month. Remembered for the life of the process, so a 150-page sweep pays each
#: rejection once rather than on every page.
_UNSUPPORTED: dict[str, set[str]] = {}


def _refused_feature(exc: Exception) -> str | None:
    """Which request feature this 400 is complaining about, if any."""
    text = str(exc).lower()
    if "temperature" in text and ("deprecated" in text or "not supported" in text):
        return "temperature"
    if "prefill" in text or "must end with a user message" in text:
        return "prefill"
    return None


class _AnthropicTransport:
    """Shared endpoint, auth and retry policy for both capabilities."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.base_url = (base_url or settings.ANTHROPIC_BASE_URL).rstrip("/")
        self.model = model or settings.ANTHROPIC_MODEL
        self.timeout = timeout or settings.ANTHROPIC_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(settings.AI_ENABLED and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            # Not a bearer token: Anthropic authenticates on its own header.
            "x-api-key": self.api_key or "",
            "anthropic-version": settings.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(settings.OPENROUTER_MAX_RETRIES),
        wait=wait_exponential(multiplier=1.5, min=2, max=20),
        reraise=True,
    )
    def post_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=timeouts.bounded(self.timeout)) as http:
                response = http.post(
                    f"{self.base_url}/v1/messages", headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise AiUnavailableError(f"Anthropic request failed: {exc}") from exc

        if response.status_code >= 400:
            # Surfaced verbatim but truncated: the body names the cause (bad key,
            # unknown model, rate limit) and guessing at it wastes an operator's time.
            raise AiResponseError(
                f"Anthropic returned {response.status_code}: {response.text[:400]}"
            )
        return response.json()


def _text_of(body: dict[str, Any]) -> str:
    """Join the text blocks of a Messages reply.

    The reply is a list of blocks and only some are text - a run that used the search
    tool also carries tool_use and web_search_tool_result blocks, which must not be
    concatenated into the model's answer.
    """
    parts: list[str] = []
    for block in body.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


class AnthropicClient(_AnthropicTransport):
    """Reads one captured page and returns candidate JSON.

    Deliberately mirrors ``OpenRouterClient.complete`` down to the keyword arguments, so
    :func:`app.services.extraction.execute_ai_job` can call either without knowing which
    provider it holds.
    """

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> AiResult:
        if not self.configured:
            raise AiUnavailableError(
                "Anthropic is not configured. Set ANTHROPIC_API_KEY, or point "
                "EXTRACTION_PROVIDER at a provider that is configured."
            )

        if json_mode:
            # Belt and braces for models that refuse prefill: `extract_json` copes with
            # fences and leading prose, but asking plainly costs nothing and means the
            # repair path is rarely needed.
            system_prompt = (
                f"{system_prompt}\n\nReply with a single valid JSON object and nothing "
                "else. No prose, no code fences."
            )

        limit = settings.ANTHROPIC_MAX_INPUT_CHARS
        if len(user_prompt) > limit:
            log.warning("ai.input_truncated", original_chars=len(user_prompt), limit=limit)
            user_prompt = user_prompt[:limit] + "\n\n[TRUNCATED BY PUMPATLAS]"

        chosen = model or self.model
        refused = _UNSUPPORTED.setdefault(chosen, set())

        def build() -> dict[str, Any]:
            payload: dict[str, Any] = {
                "model": chosen,
                "max_tokens": max_tokens,
                # A top-level field here, not a message with role "system".
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if "temperature" not in refused:
                payload["temperature"] = temperature
            if json_mode and "prefill" not in refused:
                payload["messages"].append({"role": "assistant", "content": "{"})
            return payload

        started = time.perf_counter()
        payload = build()
        # At most one retry per feature: a model refusing both would otherwise need two
        # rounds, and a bad key must not be retried at all.
        for _ in range(len(("temperature", "prefill"))):
            try:
                body = self.post_messages(payload)
                break
            except AiResponseError as exc:
                feature = _refused_feature(exc)
                if feature is None or feature in refused:
                    raise
                log.info("ai.feature_unsupported", model=chosen, feature=feature)
                refused.add(feature)
                payload = build()
        else:
            body = self.post_messages(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        prefilled = json_mode and "prefill" not in refused
        text = _text_of(body)
        if not text and not json_mode:
            raise AiResponseError(f"Unexpected Anthropic payload: {str(body)[:400]}")
        if prefilled:
            # Put back the brace the prefill consumed before parsing.
            text = "{" + text

        usage = body.get("usage") or {}
        return AiResult(
            text=text,
            data=extract_json(text) if json_mode else None,
            model=body.get("model") or payload["model"],
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            latency_ms=latency_ms,
            # Anthropic bills from token counts rather than reporting a cost per call.
            cost_usd=None,
            raw_response=body,
        )


class AnthropicWebSearchClient(_AnthropicTransport):
    """Finds candidate pages using Anthropic's server-side web search tool.

    Returns the same :class:`SearchRun` Parallel AI does. Only the URLs matter
    downstream: the capture stage fetches each page itself, so what a record cites as
    its source is always the page PumpAtlas read, never a model's summary of it.
    """

    def search(
        self,
        objective: str,
        queries: list[str] | None = None,
        *,
        max_results: int = 10,
    ) -> SearchRun:
        if not self.configured:
            raise SearchUnavailableError(
                "Anthropic is not configured. Set ANTHROPIC_API_KEY, or point "
                "SEARCH_PROVIDER at a provider that is configured."
            )

        asked = queries or []
        instruction = (
            "Search the web and list the pages that best satisfy this objective. "
            "Prefer manufacturer datasheets, product pages and technical documents "
            "over directories, marketplaces and news.\n\n"
            f"Objective: {objective}"
        )
        if asked:
            instruction += "\n\nSuggested searches:\n" + "\n".join(f"- {q}" for q in asked)

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": instruction}],
            "tools": [
                {
                    "type": WEB_SEARCH_TOOL,
                    "name": "web_search",
                    "max_uses": settings.SEARCH_MAX_USES,
                }
            ],
        }

        started = time.perf_counter()
        body = self.post_messages(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        return SearchRun(
            search_id=body.get("id"),
            objective=objective,
            queries=asked,
            results=_results_from_search_blocks(body, max_results),
            latency_ms=latency_ms,
            raw_response=body,
        )


def _results_from_search_blocks(body: dict[str, Any], max_results: int) -> list[SearchResult]:
    """Pull the cited pages out of a Messages reply that used the search tool.

    Results arrive inside ``web_search_tool_result`` blocks. De-duplicated by URL and
    ranked in the order the tool returned them, which is the order it considered most
    relevant.
    """
    found: list[SearchResult] = []
    seen: set[str] = set()

    for block in body.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content")
        if not isinstance(content, list):
            # An error block carries a dict here instead of a list of results.
            log.info("search.anthropic_tool_block_not_results", block=str(content)[:200])
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            # No excerpt: a web_search_result carries `title`, `url`, `page_age` and an
            # `encrypted_content` blob meant for feeding back to Anthropic, not a
            # readable snippet. The capture stage therefore has to fetch the page for
            # these results - it does, but only because that was fixed after a run
            # found two pages, stored them empty and reported nothing found.
            found.append(
                SearchResult(
                    url=url,
                    title=item.get("title"),
                    published_at=item.get("page_age"),
                    rank=len(found) + 1,
                    raw=item,
                )
            )
            if len(found) >= max_results:
                return found
    return found


def get_anthropic_client() -> AnthropicClient:
    return AnthropicClient()
