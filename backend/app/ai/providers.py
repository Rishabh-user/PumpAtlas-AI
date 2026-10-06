"""Which provider does the reading, and which does the searching.

One place that resolves a provider name to a client, so the rest of the codebase asks
for a capability rather than naming a vendor. `discovery` wants "something that reads a
page" and "something that finds pages"; it should not know that two of the three reading
providers share a client and the third does not.

Three reading providers:

* ``openrouter`` - Gemma, the original. Chat Completions.
* ``openai`` - the same client pointed at ``api.openai.com``; the contract is identical,
  only the base URL, key and model differ.
* ``anthropic`` - Claude, via the Messages API and its own client.

Three search providers: ``parallel``, ``openai`` and ``anthropic``. All three return the
same :class:`SearchRun`, and in every case the URLs are handed to the capture stage,
which fetches each page itself. That is what keeps provenance honest whichever provider
found it: the evidence quote on a stored field always comes from the page PumpAtlas
read, never from a model's description of a page.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.ai.anthropic_client import AnthropicClient, AnthropicWebSearchClient
from app.ai.openai_search import OpenAiWebSearchClient
from app.ai.openrouter import AiResult, OpenRouterClient
from app.ai.parallel_search import ParallelSearchClient, SearchRun
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

READING_PROVIDERS = ("openrouter", "openai", "anthropic")
SEARCH_PROVIDERS = ("parallel", "openai", "anthropic")


class ReadingModel(Protocol):
    """What the extraction service needs of whoever reads a page."""

    model: str

    @property
    def configured(self) -> bool: ...

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> AiResult: ...


class WebSearch(Protocol):
    """What discovery needs of whoever finds pages."""

    @property
    def configured(self) -> bool: ...

    def search(
        self, objective: str, queries: list[str] | None = None, *, max_results: int = 10
    ) -> SearchRun: ...


class UnknownProviderError(ValueError):
    """Raised for a provider name that does not exist.

    Deliberately loud. A typo in ``EXTRACTION_PROVIDER`` silently falling back to the
    default would mean a run billed to a model nobody chose.
    """


def _from_config(config: Any) -> ReadingModel | WebSearch:
    """Build a client from a stored configuration.

    The key is decrypted here and handed straight to the client, so plaintext exists
    only for the life of the call and never enters a response.
    """
    from app.services import ai_settings

    key = ai_settings.decrypt_key(config)
    provider = config.provider
    if config.role == "search":
        if provider == "parallel":
            return ParallelSearchClient(api_key=key, base_url=config.base_url or None)
        if provider == "openai":
            return OpenAiWebSearchClient(
                api_key=key,
                base_url=config.base_url or None,
                model=config.model or None,
                timeout=config.timeout_seconds or None,
            )
        if provider == "anthropic":
            return AnthropicWebSearchClient(
                api_key=key,
                base_url=config.base_url or None,
                model=config.model or None,
                timeout=config.timeout_seconds or None,
            )
    else:
        if provider in {"openrouter", "openai"}:
            return OpenRouterClient(
                api_key=key,
                base_url=config.base_url or None,
                model=config.model or None,
                timeout=config.timeout_seconds or None,
            )
        if provider == "anthropic":
            return AnthropicClient(
                api_key=key,
                base_url=config.base_url or None,
                model=config.model or None,
                timeout=config.timeout_seconds or None,
            )
    raise UnknownProviderError(
        f"Stored configuration {config.label!r} names provider {provider!r}, which "
        f"cannot do {config.role}."
    )


def configured_reading_model(db: Any) -> ReadingModel | None:
    """The reading model the platform has activated, or None if none is.

    The settings screen is the source of truth for this, not the environment: an
    operator switches model without a deploy, and the run panel shows which one ran.
    """
    from app.services import ai_settings

    config = ai_settings.active_config(db, "reading")
    return None if config is None else _from_config(config)  # type: ignore[return-value]


def configured_search_client(db: Any) -> WebSearch | None:
    """The search provider the platform has activated, or None if none is."""
    from app.services import ai_settings

    config = ai_settings.active_config(db, "search")
    return None if config is None else _from_config(config)  # type: ignore[return-value]


def reading_model(provider: str | None = None) -> ReadingModel:
    """The client that reads captured pages."""
    name = (provider or settings.EXTRACTION_PROVIDER or "openrouter").strip().lower()
    if name == "openrouter":
        return OpenRouterClient()
    if name == "openai":
        # Same contract, different endpoint. The attribution headers OpenRouter wants
        # are suppressed by the client when the base URL is not OpenRouter's.
        return OpenRouterClient(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            model=settings.OPENAI_MODEL,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        )
    if name == "anthropic":
        return AnthropicClient()
    raise UnknownProviderError(
        f"Unknown EXTRACTION_PROVIDER {name!r}. Expected one of: {', '.join(READING_PROVIDERS)}."
    )


def search_client(provider: str | None = None) -> WebSearch:
    """The client that finds candidate pages."""
    name = (provider or settings.SEARCH_PROVIDER or "parallel").strip().lower()
    if name == "parallel":
        return ParallelSearchClient()
    if name == "openai":
        return OpenAiWebSearchClient()
    if name == "anthropic":
        return AnthropicWebSearchClient()
    raise UnknownProviderError(
        f"Unknown SEARCH_PROVIDER {name!r}. Expected one of: {', '.join(SEARCH_PROVIDERS)}."
    )
