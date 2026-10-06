"""OpenRouter client for Gemma.

Gemma is used for extraction, normalisation, classification, summarisation and data
quality checks. It never writes to the database directly - it returns candidate JSON
which the services layer validates, scores and records with provenance.

Notes on making a small open model behave:
* JSON is requested with ``response_format`` and re-asserted in the prompt, then
  parsed defensively (fenced blocks, leading prose, trailing commas).
* One repair round-trip is attempted on unparseable output before failing.
* Temperature defaults to 0 for extraction so re-running a source is reproducible.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai import timeouts
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


class _Unset:
    """Sentinel for "argument not supplied", where None is a meaningful value."""


UNSET = _Unset()


class AiUnavailableError(RuntimeError):
    """Raised when the provider cannot be reached or is not configured."""


class AiResponseError(RuntimeError):
    """Raised when the model returned something unusable."""


@dataclass
class AiResult:
    text: str
    data: dict[str, Any] | None
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    cost_usd: float | None
    raw_response: dict[str, Any]

    @property
    def total_tokens(self) -> int:
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON recovery from a chatty completion."""
    if not text:
        return None
    candidates: list[str] = []
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    stripped = text.strip()
    candidates.append(stripped)
    # Widest brace span, for output wrapped in prose.
    first, last = stripped.find("{"), stripped.rfind("}")
    if first != -1 and last > first:
        candidates.append(stripped[first : last + 1])

    for candidate in candidates:
        for attempt in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
            try:
                parsed = json.loads(attempt)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"items": parsed}
    return None


class OpenRouterClient:
    """Thin, synchronous OpenRouter wrapper. Safe to use from Celery workers."""

    def __init__(
        self,
        api_key: str | None | _Unset = UNSET,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        # `UNSET` rather than None, so "use the OpenRouter key" and "this provider has
        # no key" are distinguishable. With `api_key or settings.OPENROUTER_API_KEY`,
        # pointing this client at OpenAI without an OpenAI key silently sent the
        # OpenRouter key to api.openai.com - a credential handed to the wrong vendor,
        # reported as configured, and only visible as a puzzling 401.
        self.api_key = settings.OPENROUTER_API_KEY if isinstance(api_key, _Unset) else api_key
        self.base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")
        self.model = model or settings.OPENROUTER_MODEL
        self.timeout = timeout or settings.OPENROUTER_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(settings.AI_ENABLED and self.api_key)

    @property
    def is_openrouter(self) -> bool:
        """Whether the configured endpoint is OpenRouter itself.

        The request body is the OpenAI chat-completions shape, which OpenRouter, OpenAI
        and most hosted gateways all speak - so pointing ``OPENROUTER_BASE_URL`` at
        another provider is a configuration change rather than a new client. Only the
        attribution headers are OpenRouter's own, and they are the one thing that should
        not be sent elsewhere.
        """
        return "openrouter.ai" in self.base_url

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.is_openrouter:
            # Attribution, for OpenRouter's dashboard. Meaningless to other providers.
            headers["HTTP-Referer"] = "https://targeticon.com/pumpatlas"
            headers["X-Title"] = "PumpAtlas AI"
        return headers

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(settings.OPENROUTER_MAX_RETRIES),
        wait=wait_exponential(multiplier=1.5, min=2, max=20),
        reraise=True,
    )
    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=timeouts.bounded(self.timeout)) as client:
            response = client.post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
            )
        if response.status_code == 429:
            raise AiUnavailableError("OpenRouter rate limit reached")
        if response.status_code >= 500:
            raise AiUnavailableError(f"OpenRouter upstream error {response.status_code}")
        if response.status_code >= 400:
            raise AiResponseError(f"OpenRouter rejected the request: {response.text[:500]}")
        return response.json()

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
            # Names the endpoint this client is actually pointed at. This class serves
            # both OpenRouter and OpenAI, so a fixed message sent someone who had
            # selected OpenAI off to set OPENROUTER_API_KEY instead.
            if self.is_openrouter:
                raise AiUnavailableError(
                    "OpenRouter is not configured. Set OPENROUTER_API_KEY, or "
                    "AI_ENABLED=false to run the platform without the assistant layer."
                )
            raise AiUnavailableError(
                f"No API key for the reading provider at {self.base_url}. Set the key "
                "for the provider named by EXTRACTION_PROVIDER (OPENAI_API_KEY for "
                "OpenAI), or point EXTRACTION_PROVIDER at one that has a key."
            )

        # Guard the context window: sources can be entire PDFs.
        limit = settings.OPENROUTER_MAX_INPUT_CHARS
        if len(user_prompt) > limit:
            log.warning("ai.input_truncated", original_chars=len(user_prompt), limit=limit)
            user_prompt = user_prompt[:limit] + "\n\n[TRUNCATED BY PUMPATLAS]"

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        body = self._post(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AiResponseError(f"Unexpected OpenRouter payload: {str(body)[:400]}") from exc

        usage = body.get("usage") or {}
        data = extract_json(text) if json_mode else None
        if json_mode and data is None:
            data = self._repair_json(text, payload["model"])

        cost = usage.get("cost")
        return AiResult(
            text=text,
            data=data,
            model=body.get("model") or payload["model"],
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
            raw_response=body,
        )

    def _repair_json(self, broken: str, model: str) -> dict[str, Any] | None:
        """One cheap retry that asks the model to re-emit valid JSON only."""
        log.warning("ai.json_repair_attempt", chars=len(broken))
        repair_system = (
            "You repair malformed JSON. Reply with a single valid JSON object and "
            "nothing else. Do not add commentary."
        )
        try:
            body = self._post(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": repair_system},
                        {"role": "user", "content": broken[:20000]},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 4096,
                    "response_format": {"type": "json_object"},
                }
            )
            return extract_json(body["choices"][0]["message"]["content"] or "")
        except Exception as exc:  # noqa: BLE001 - repair is best effort
            log.warning("ai.json_repair_failed", error=str(exc))
            return None


def get_openrouter_client() -> OpenRouterClient:
    return OpenRouterClient()
