"""Tests for the LLM provider abstraction.

Covers the `LLMProvider` ABC contract plus the
`OllamaProvider` concrete implementation. Ollama calls
are mocked at the `ollama.Client` level via the
module-level `_ollama` symbol so tests don't require a
running Ollama daemon.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from tests.unit.conftest import FakeProvider

from unstructured_mapping.pipeline import (
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
    OllamaProvider,
)
from unstructured_mapping.pipeline import llm_ollama


def make_ollama_provider(
    client: MagicMock,
    *,
    context_window: int | None = 4096,
) -> OllamaProvider:
    """Build an OllamaProvider with a mocked client."""
    with patch.object(
        llm_ollama._ollama,
        "Client",
        return_value=client,
    ):
        return OllamaProvider(
            model="test-model",
            context_window=context_window,
        )


# -- ABC contract --


def test_llm_provider_is_abstract():
    """LLMProvider cannot be instantiated directly."""
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_fake_provider_satisfies_contract():
    """A concrete subclass works via the ABC interface."""
    p = FakeProvider(response="world", supports_json_mode=False)
    assert p.model_name == "fake-1"
    assert p.provider_name == "fake"
    assert p.context_window == 4096
    assert p.supports_json_mode is False
    assert p.generate("hi", system="s") == "world"
    assert p.calls == [("hi", "s", False)]


# -- LLMProvider exception hierarchy --


def test_exception_hierarchy():
    """All LLM errors derive from LLMProviderError."""
    assert issubclass(LLMConnectionError, LLMProviderError)
    assert issubclass(LLMTimeoutError, LLMProviderError)
    assert issubclass(LLMEmptyResponseError, LLMProviderError)


# -- OllamaProvider.generate: happy path --


def test_ollama_generate_dict_response():
    """Dict responses are unwrapped to plain text."""
    client = MagicMock()
    client.generate.return_value = {"response": "  Apple Inc.  "}
    provider = make_ollama_provider(client)

    out = provider.generate(
        "List entities.",
        system="You are helpful.",
        json_mode=True,
    )

    assert out == "Apple Inc."
    client.generate.assert_called_once()
    call_kwargs = client.generate.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["prompt"] == "List entities."
    assert call_kwargs["system"] == "You are helpful."
    assert call_kwargs["format"] == "json"


def test_ollama_generate_attr_response():
    """Attribute-style responses (dataclass) also work."""
    client = MagicMock()
    response_obj = MagicMock()
    response_obj.response = "Microsoft"
    # Ensure isinstance(response_obj, dict) is False.
    client.generate.return_value = response_obj
    provider = make_ollama_provider(client)

    out = provider.generate("hi")

    assert out == "Microsoft"
    # system and format omitted when defaults are used.
    kwargs = client.generate.call_args.kwargs
    assert "system" not in kwargs
    assert "format" not in kwargs


def test_ollama_provider_metadata():
    """Provider metadata is exposed for run tracking."""
    client = MagicMock()
    provider = make_ollama_provider(client, context_window=8192)

    assert provider.model_name == "test-model"
    assert provider.provider_name == "ollama"
    assert provider.context_window == 8192
    assert provider.supports_json_mode is True


# -- OllamaProvider.generate: error translation --


def test_ollama_connection_error():
    """httpx.ConnectError -> LLMConnectionError."""
    client = MagicMock()
    client.generate.side_effect = httpx.ConnectError("refused")
    provider = make_ollama_provider(client)

    with pytest.raises(LLMConnectionError):
        provider.generate("hi")


def test_ollama_connect_timeout_is_connection_error():
    """ConnectTimeout is also a connection failure."""
    client = MagicMock()
    client.generate.side_effect = httpx.ConnectTimeout("slow")
    provider = make_ollama_provider(client)

    with pytest.raises(LLMConnectionError):
        provider.generate("hi")


def test_ollama_read_timeout_is_timeout_error():
    """httpx.ReadTimeout -> LLMTimeoutError."""
    client = MagicMock()
    client.generate.side_effect = httpx.ReadTimeout("read took too long")
    provider = make_ollama_provider(client)

    with pytest.raises(LLMTimeoutError):
        provider.generate("hi")


def test_ollama_other_exception_is_provider_error():
    """Unknown ollama errors wrap as LLMProviderError."""
    client = MagicMock()
    client.generate.side_effect = RuntimeError("malformed model response")
    provider = make_ollama_provider(client)

    with pytest.raises(LLMProviderError) as exc:
        provider.generate("hi")
    # Not one of the specific subclasses.
    assert not isinstance(exc.value, LLMConnectionError)
    assert not isinstance(exc.value, LLMTimeoutError)


def test_ollama_empty_response_raises():
    """Empty response text -> LLMEmptyResponseError."""
    client = MagicMock()
    client.generate.return_value = {"response": "   "}
    provider = make_ollama_provider(client)

    with pytest.raises(LLMEmptyResponseError):
        provider.generate("hi")


def test_ollama_missing_response_key_raises():
    """Dict without a 'response' key is treated as empty."""
    client = MagicMock()
    client.generate.return_value = {}
    provider = make_ollama_provider(client)

    with pytest.raises(LLMEmptyResponseError):
        provider.generate("hi")


# -- OllamaProvider: context window auto-detection --


def test_ollama_context_window_from_model_info():
    """show() model_info *.context_length is honored."""
    client = MagicMock()
    client.show.return_value = {
        "model_info": {
            "llama.context_length": 8192,
            "llama.vocab_size": 32000,
        }
    }
    provider = make_ollama_provider(client, context_window=None)

    assert provider.context_window == 8192
    client.show.assert_called_once_with("test-model")


def test_ollama_context_window_from_parameters():
    """show() parameters 'num_ctx 16384' is parsed."""
    client = MagicMock()
    client.show.return_value = {
        "parameters": "num_ctx 16384\nstop eos",
    }
    provider = make_ollama_provider(client, context_window=None)

    assert provider.context_window == 16384


def test_ollama_context_window_default_when_unknown():
    """Missing metadata falls back to DEFAULT_CONTEXT_WINDOW."""
    client = MagicMock()
    client.show.return_value = {}
    provider = make_ollama_provider(client, context_window=None)

    assert provider.context_window == (llm_ollama.DEFAULT_CONTEXT_WINDOW)


def test_ollama_context_window_default_on_show_error():
    """show() failures fall back gracefully."""
    client = MagicMock()
    client.show.side_effect = RuntimeError("no model")
    provider = make_ollama_provider(client, context_window=None)

    assert provider.context_window == (llm_ollama.DEFAULT_CONTEXT_WINDOW)


def test_ollama_explicit_context_window_skips_show():
    """Passing context_window avoids the show() call."""
    client = MagicMock()
    provider = make_ollama_provider(client, context_window=2048)

    assert provider.context_window == 2048
    client.show.assert_not_called()


# -- OllamaProvider: optional dependency guard --


def test_ollama_provider_missing_ollama_package():
    """ImportError when the 'llm' extras are not installed."""
    with patch.object(llm_ollama, "_ollama", None):
        with pytest.raises(ImportError, match="llm"):
            OllamaProvider(model="test-model")


# -- TokenUsage and last_token_usage --


def test_token_usage_total_and_add():
    """TokenUsage totals and sums across calls."""
    from unstructured_mapping.pipeline import TokenUsage

    a = TokenUsage(input_tokens=10, output_tokens=3)
    b = TokenUsage(input_tokens=5, output_tokens=2)
    assert a.total_tokens == 13
    combined = a + b
    assert combined.input_tokens == 15
    assert combined.output_tokens == 5


def test_llm_provider_default_last_token_usage_is_none():
    """Fakes that don't override report None usage."""
    p = FakeProvider()
    assert p.last_token_usage is None


def test_ollama_exposes_token_usage_from_response():
    """Ollama's prompt_eval_count/eval_count surface as
    TokenUsage on the provider."""
    from unstructured_mapping.pipeline import TokenUsage

    client = MagicMock()
    client.generate.return_value = {
        "response": "ok",
        "prompt_eval_count": 42,
        "eval_count": 17,
    }
    provider = make_ollama_provider(client)
    provider.generate("hi")
    assert provider.last_token_usage == TokenUsage(
        input_tokens=42, output_tokens=17
    )


def test_ollama_missing_usage_fields_returns_none():
    """When the daemon omits counts, usage is None so
    callers can distinguish 'not reported' from zero."""
    client = MagicMock()
    client.generate.return_value = {"response": "ok"}
    provider = make_ollama_provider(client)
    provider.generate("hi")
    assert provider.last_token_usage is None
