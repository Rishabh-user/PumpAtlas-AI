"""Three providers can read a page, three can find one, and the swap must be safe.

Verified against recorded response shapes rather than a live endpoint: what can go wrong
here is sending the wrong request or misreading the reply, and both are visible without
a key. What cannot be checked offline - whether a given model obeys the evidence-quote
contract - needs a real call and belongs in a manual comparison, not a test suite.

The one fault worth more than a wrong answer is a credential going to the wrong vendor,
so that has its own test.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.ai import anthropic_client, providers
from app.ai.anthropic_client import AnthropicClient, AnthropicWebSearchClient
from app.ai.openai_search import OpenAiWebSearchClient
from app.ai.openrouter import AiResponseError, OpenRouterClient
from app.core.config import settings


class TestAKeyNeverGoesToTheWrongVendor:
    """The failure that matters most: one provider's key sent to another's endpoint.

    ``api_key or settings.OPENROUTER_API_KEY`` did exactly that. Selecting the OpenAI
    provider without an OpenAI key fell back to the OpenRouter key, reported itself as
    configured, and posted that credential to api.openai.com - where it is both useless
    and disclosed.
    """

    def test_no_openai_key_means_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-key-should-not-travel")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
        monkeypatch.setattr(settings, "AI_ENABLED", True)

        client = providers.reading_model("openai")
        assert client.api_key != "or-key-should-not-travel"
        assert not client.configured

    def test_the_openrouter_client_still_defaults_to_its_own_key(self, monkeypatch):
        """The sentinel must not break the ordinary case."""
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-key")
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        assert OpenRouterClient().api_key == "or-key"
        assert OpenRouterClient().configured

    def test_attribution_headers_only_go_to_openrouter(self):
        """`HTTP-Referer` and `X-Title` are OpenRouter's own and mean nothing elsewhere."""
        openrouter = OpenRouterClient(api_key="k", base_url="https://openrouter.ai/api/v1")
        openai = OpenRouterClient(api_key="k", base_url="https://api.openai.com/v1")
        assert "X-Title" in openrouter._headers()
        assert "X-Title" not in openai._headers()

    def test_anthropic_authenticates_on_its_own_header(self):
        headers = AnthropicClient(api_key="a-key")._headers()
        assert headers["x-api-key"] == "a-key"
        assert "Authorization" not in headers
        # Mandatory, and pinned: the version *is* the contract.
        assert headers["anthropic-version"] == settings.ANTHROPIC_VERSION


class TestTheFactoryRefusesToGuess:
    @pytest.mark.parametrize("name", providers.READING_PROVIDERS)
    def test_every_named_reading_provider_resolves(self, name):
        assert providers.reading_model(name) is not None

    @pytest.mark.parametrize("name", providers.SEARCH_PROVIDERS)
    def test_every_named_search_provider_resolves(self, name):
        assert providers.search_client(name) is not None

    def test_an_unknown_reading_provider_raises(self):
        """A typo must not quietly bill a run to whichever model was the default."""
        with pytest.raises(providers.UnknownProviderError):
            providers.reading_model("gpt-9")

    def test_an_unknown_search_provider_raises(self):
        with pytest.raises(providers.UnknownProviderError):
            providers.search_client("bing")


def _anthropic_reply(text: str) -> dict[str, Any]:
    """A minimal Messages reply carrying one text block."""
    return {
        "id": "msg_1",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 11, "output_tokens": 22},
    }


class TestAnthropicReadsAPage:
    def test_the_request_matches_the_messages_contract(self, monkeypatch):
        """System prompt at the top level, and JSON forced by prefilling the reply.

        There is no `response_format` on this API, so the opening brace in the assistant
        turn is what stops the model answering with prose or a fenced block.
        """
        captured: dict[str, Any] = {}

        def fake_post(self, payload):
            captured.update(payload)
            return _anthropic_reply('"vendor_name": "Sulzer"}')

        monkeypatch.setattr(AnthropicClient, "post_messages", fake_post, raising=True)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        # Learned refusals live for the life of the process, so a test that expects the
        # unnegotiated request has to start from a clean slate.
        anthropic_client._UNSUPPORTED.clear()
        client = AnthropicClient(api_key="a-key")

        result = client.complete("SYSTEM RULES", "PAGE TEXT")

        # The caller's prompt, plus the JSON instruction appended for json_mode - which
        # is what keeps the reply parseable on models that refuse prefill.
        assert captured["system"].startswith("SYSTEM RULES")
        assert "single valid JSON object" in captured["system"]
        assert captured["messages"][0] == {"role": "user", "content": "PAGE TEXT"}
        # Prefill is sent until a model refuses it; this stub accepts everything.
        assert captured["messages"][-1] == {"role": "assistant", "content": "{"}
        assert "response_format" not in captured
        # The brace the prefill consumed is restored before parsing.
        assert result.data == {"vendor_name": "Sulzer"}
        assert result.prompt_tokens == 11 and result.completion_tokens == 22

    def test_only_text_blocks_become_the_answer(self, monkeypatch):
        """A reply that used a tool carries blocks that are not the model's answer."""
        body = {
            "id": "msg_2",
            "model": "claude-sonnet-5",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "web_search", "input": {}},
                {"type": "text", "text": '"a": 1}'},
            ],
            "usage": {},
        }
        monkeypatch.setattr(AnthropicClient, "post_messages", lambda self, p: body)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        assert AnthropicClient(api_key="k").complete("s", "u").data == {"a": 1}

    def test_an_http_error_names_the_cause(self, monkeypatch):
        """A 401 or an unknown model has to reach the operator, not be swallowed."""

        def fake_send(*_args, **_kwargs):
            return httpx.Response(401, text='{"error":{"message":"invalid x-api-key"}}')

        monkeypatch.setattr(httpx.Client, "post", fake_send, raising=True)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        with pytest.raises(AiResponseError) as caught:
            AnthropicClient(api_key="bad").complete("s", "u")
        assert "401" in str(caught.value)
        assert "invalid x-api-key" in str(caught.value)


class TestUnsupportedFeaturesAreNegotiated:
    """Two request features are wanted by some Claude models and refused by others.

    * ``temperature`` - newer models deprecate it; older ones need it, because their
      default is 1.0 and extraction has to be reproducible.
    * ``prefill`` - seeding the assistant turn with "{" is the documented way to force a
      bare JSON object on an API with no ``response_format``. Newer models refuse it.

    Sending both and dropping whichever comes back refused keeps the strictest behaviour
    each model allows, without a list of model names that goes stale every release. Both
    of these were found by a real run failing, not by reading the docs.
    """

    def _client(self, monkeypatch, refuse: set[str]):
        """A client whose endpoint refuses the named features."""
        calls: list[dict[str, Any]] = []

        def fake_post(self, payload):
            calls.append(dict(payload))
            if "temperature" in refuse and "temperature" in payload:
                raise AiResponseError("400: `temperature` is deprecated for this model.")
            if "prefill" in refuse and any(
                m.get("role") == "assistant" for m in payload["messages"]
            ):
                raise AiResponseError(
                    "400: This model does not support assistant message prefill. "
                    "The conversation must end with a user message."
                )
            return _anthropic_reply('"ok": true}' if "prefill" not in refuse else '{"ok": true}')

        monkeypatch.setattr(AnthropicClient, "post_messages", fake_post, raising=True)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        anthropic_client._UNSUPPORTED.clear()
        return AnthropicClient(api_key="k", model="claude-sonnet-5"), calls

    def test_temperature_alone_is_dropped_and_retried(self, monkeypatch):
        client, calls = self._client(monkeypatch, {"temperature"})
        assert client.complete("s", "u").data == {"ok": True}
        assert len(calls) == 2
        assert "temperature" in calls[0] and "temperature" not in calls[1]

    def test_both_refusals_are_negotiated(self, monkeypatch):
        """claude-sonnet-5 refuses both, so it takes two adjustments."""
        client, calls = self._client(monkeypatch, {"temperature", "prefill"})
        assert client.complete("s", "u").data == {"ok": True}
        assert len(calls) == 3
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]
        assert any(m.get("role") == "assistant" for m in calls[1]["messages"])
        assert not any(m.get("role") == "assistant" for m in calls[2]["messages"])

    def test_each_rejection_is_paid_once_not_per_page(self, monkeypatch):
        """A 150-page sweep must not spend wasted calls on every page."""
        client, calls = self._client(monkeypatch, {"temperature", "prefill"})
        client.complete("s", "page one")
        calls.clear()
        client.complete("s", "page two")
        assert len(calls) == 1

    def test_a_model_that_accepts_both_gets_both(self, monkeypatch):
        """Determinism and strict JSON are not abandoned where they are available."""
        client, calls = self._client(monkeypatch, set())
        client.complete("s", "u")
        assert calls[0]["temperature"] == 0.0
        assert any(m.get("role") == "assistant" for m in calls[0]["messages"])

    def test_an_unrelated_400_is_not_swallowed(self, monkeypatch):
        """Only a feature refusal is retried - a bad key must still surface."""

        def fake_post(self, payload):
            raise AiResponseError("Anthropic returned 401: invalid x-api-key")

        monkeypatch.setattr(AnthropicClient, "post_messages", fake_post, raising=True)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        anthropic_client._UNSUPPORTED.clear()
        with pytest.raises(AiResponseError, match="401"):
            AnthropicClient(api_key="bad", model="claude-sonnet-5").complete("s", "u")

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("`temperature` is deprecated for this model.", "temperature"),
            ("temperature is not supported", "temperature"),
            ("does not support assistant message prefill", "prefill"),
            ("The conversation must end with a user message.", "prefill"),
            ("invalid x-api-key", None),
            ("max_tokens is too large", None),
        ],
    )
    def test_the_detector_reads_the_message_not_a_model_list(self, message, expected):
        assert anthropic_client._refused_feature(AiResponseError(message)) == expected

    def test_json_is_still_asked_for_in_words(self, monkeypatch):
        """Without prefill the instruction is what keeps the reply parseable."""
        client, calls = self._client(monkeypatch, {"prefill"})
        client.complete("SYSTEM RULES", "u")
        assert "single valid JSON object" in calls[-1]["system"]
        assert "SYSTEM RULES" in calls[-1]["system"]


class TestSearchProvidersReturnTheSameShape:
    """Whichever provider finds a page, capture fetches it and provenance is identical."""

    def test_anthropic_search_results_are_read_from_tool_blocks(self, monkeypatch):
        body = {
            "id": "msg_3",
            "content": [
                {"type": "text", "text": "Here are some pumps."},
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {
                            "type": "web_search_result",
                            "url": "https://sulzer.com/msd",
                            "title": "MSD datasheet",
                            "page_age": "2024-01-01",
                        },
                        {
                            "type": "web_search_result",
                            "url": "https://sulzer.com/msd",  # duplicate
                            "title": "again",
                        },
                        {
                            "type": "web_search_result",
                            "url": "https://flowserve.com/hpx",
                            "title": "HPX",
                        },
                    ],
                },
            ],
        }
        monkeypatch.setattr(AnthropicWebSearchClient, "post_messages", lambda self, p: body)
        monkeypatch.setattr(settings, "AI_ENABLED", True)

        run = AnthropicWebSearchClient(api_key="k").search("find pumps", ["api 610"])
        assert [r.url for r in run.results] == [
            "https://sulzer.com/msd",
            "https://flowserve.com/hpx",
        ]
        assert run.results[0].title == "MSD datasheet"
        assert [r.rank for r in run.results] == [1, 2]

    def test_anthropic_search_survives_an_error_block(self, monkeypatch):
        """A failed tool call puts a dict where the result list goes."""
        body = {
            "id": "msg_4",
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": {"type": "web_search_tool_result_error", "error_code": "max_uses"},
                }
            ],
        }
        monkeypatch.setattr(AnthropicWebSearchClient, "post_messages", lambda self, p: body)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        assert AnthropicWebSearchClient(api_key="k").search("x").results == []

    def test_openai_search_results_come_from_citations(self, monkeypatch):
        """The pages the model cited *are* the result set on the Responses API."""
        body = {
            "id": "resp_1",
            "output": [
                {"type": "web_search_call", "id": "ws_1"},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Two options.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://sundyne.com/lmv311",
                                    "title": "LMV 311",
                                },
                                {"type": "file_citation", "file_id": "f1"},
                                {
                                    "type": "url_citation",
                                    "url": "https://sundyne.com/lmv311",
                                    "title": "dupe",
                                },
                            ],
                        }
                    ],
                },
            ],
        }
        monkeypatch.setattr(OpenAiWebSearchClient, "_post_responses", lambda self, p: body)
        monkeypatch.setattr(settings, "AI_ENABLED", True)

        run = OpenAiWebSearchClient(api_key="k").search("find pumps")
        assert [r.url for r in run.results] == ["https://sundyne.com/lmv311"]
        assert run.search_id == "resp_1"

    def test_openai_search_asks_for_the_web_search_tool(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_post(self, payload):
            captured.update(payload)
            return {"id": "r", "output": []}

        monkeypatch.setattr(OpenAiWebSearchClient, "_post_responses", fake_post)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        OpenAiWebSearchClient(api_key="k").search("objective text", ["q1", "q2"])

        assert captured["tools"] == [{"type": "web_search"}]
        assert "objective text" in captured["input"]
        assert "q1" in captured["input"] and "q2" in captured["input"]

    @pytest.mark.parametrize("max_results", [1, 2])
    def test_max_results_is_honoured(self, monkeypatch, max_results):
        body = {
            "id": "m",
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {"type": "web_search_result", "url": f"https://e{n}.com", "title": str(n)}
                        for n in range(5)
                    ],
                }
            ],
        }
        monkeypatch.setattr(AnthropicWebSearchClient, "post_messages", lambda self, p: body)
        monkeypatch.setattr(settings, "AI_ENABLED", True)
        run = AnthropicWebSearchClient(api_key="k").search("x", max_results=max_results)
        assert len(run.results) == max_results

    def test_an_unconfigured_provider_says_so(self, monkeypatch):
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
        monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
        from app.ai.parallel_search import SearchUnavailableError

        with pytest.raises(SearchUnavailableError):
            AnthropicWebSearchClient().search("x")
        with pytest.raises(SearchUnavailableError):
            OpenAiWebSearchClient().search("x")


class TestTheRunSaysWhichProviderRan:
    def test_discovery_records_the_configured_search_provider(self):
        """The job list must name the provider that ran, not a hardcoded one."""
        import inspect

        from app.services import discovery

        source = inspect.getsource(discovery.run_discovery)
        assert 'provider="parallel"' not in source
        assert "provider=search_provider" in source

    def test_every_provider_has_a_display_label(self):
        from app.services import discovery

        for name in set(providers.READING_PROVIDERS) | set(providers.SEARCH_PROVIDERS):
            assert name in discovery._PROVIDER_LABELS, name

    def test_the_unconfigured_message_names_the_setting(self):
        """So the fix is obvious from the run panel rather than the source."""
        import inspect

        from app.services import discovery

        source = inspect.getsource(discovery.run_discovery)
        assert "EXTRACTION_PROVIDER" in source


def test_settings_expose_both_provider_choices():
    """Switching provider must be one line in .env, not a code change."""
    for field in (
        "EXTRACTION_PROVIDER",
        "SEARCH_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
    ):
        assert field in type(settings).model_fields, field


def test_json_extraction_is_shared_not_reimplemented():
    """Anthropic reuses the defensive parser rather than growing a second one.

    Fenced blocks, leading prose and trailing commas are all handled in one place; a
    second copy would drift and only some providers would tolerate messy output.
    """
    import inspect

    from app.ai import anthropic_client

    assert "extract_json" in inspect.getsource(anthropic_client.AnthropicClient.complete)
