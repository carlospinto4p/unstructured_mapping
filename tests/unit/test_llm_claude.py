"""Tests for the ClaudeProvider (Anthropic Messages API).

Covers the `ClaudeProvider` concrete implementation of
`LLMProvider`. Anthropic calls are mocked at the
`anthropic.Anthropic` level via the module-level
`_anthropic` symbol so tests don't require an API key
or network access.
"""

from unittest.mock import MagicMock, patch

import pytest

from unstructured_mapping.pipeline import (
    ClaudeProvider,
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMProviderError,
    LLMTimeoutError,
)
from unstructured_mapping.pipeline.llm import claude as llm_claude


# -- Helpers --


def make_claude_provider(
    client: MagicMock,
    *,
    context_window: int = 200_000,
    max_tokens: int = 4096,
) -> ClaudeProvider:
    """Build a ClaudeProvider with a mocked client."""
    with patch.object(
        llm_claude._anthropic,
        "Anthropic",
        return_value=client,
    ):
        return ClaudeProvider(
            model="test-model",
            context_window=context_window,
            max_tokens=max_tokens,
        )


def _text_block(text: str) -> MagicMock:
    """Create a mock content block with a text attr."""
    block = MagicMock()
    block.text = text
    return block


def _message_response(text: str) -> MagicMock:
    """Create a mock Message with one text block."""
    msg = MagicMock()
    msg.content = [_text_block(text)]
    return msg


# -- ClaudeProvider.generate: happy path --


def test_claude_generate_text_response():
    """Text content blocks are extracted and stripped."""
    client = MagicMock()
    client.messages.create.return_value = _message_response("  Apple Inc.  ")
    provider = make_claude_provider(client)

    out = provider.generate(
        "List entities.",
        system="You are helpful.",
    )

    assert out == "Apple Inc."
    client.messages.create.assert_called_once()
    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["max_tokens"] == 4096
    assert call_kwargs["messages"] == [
        {"role": "user", "content": "List entities."},
    ]
    assert call_kwargs["system"] == "You are helpful."


def test_claude_generate_no_system():
    """System prompt is omitted when None."""
    client = MagicMock()
    client.messages.create.return_value = _message_response("Microsoft")
    provider = make_claude_provider(client)

    out = provider.generate("hi")

    assert out == "Microsoft"
    kwargs = client.messages.create.call_args.kwargs
    assert "system" not in kwargs


def test_claude_provider_metadata():
    """Provider metadata is exposed for run tracking."""
    client = MagicMock()
    provider = make_claude_provider(client, context_window=100_000)

    assert provider.model_name == "test-model"
    assert provider.provider_name == "anthropic"
    assert provider.context_window == 100_000
    assert provider.supports_json_mode is False


# -- ClaudeProvider.generate: json_mode --


def test_claude_json_mode_raises():
    """json_mode=True raises ValueError."""
    client = MagicMock()
    provider = make_claude_provider(client)

    with pytest.raises(ValueError, match="supports_json_mode"):
        provider.generate("hi", json_mode=True)


# -- ClaudeProvider.generate: error translation --


def test_claude_connection_error():
    """APIConnectionError -> LLMConnectionError."""
    client = MagicMock()
    client.messages.create.side_effect = (
        llm_claude._anthropic.APIConnectionError(request=MagicMock())
    )
    provider = make_claude_provider(client)

    with pytest.raises(LLMConnectionError):
        provider.generate("hi")


def test_claude_timeout_error():
    """APITimeoutError -> LLMTimeoutError."""
    client = MagicMock()
    client.messages.create.side_effect = (
        llm_claude._anthropic.APITimeoutError(request=MagicMock())
    )
    provider = make_claude_provider(client)

    with pytest.raises(LLMTimeoutError):
        provider.generate("hi")


def test_claude_other_exception_is_provider_error():
    """Unknown errors wrap as LLMProviderError."""
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("unexpected")
    provider = make_claude_provider(client)

    with pytest.raises(LLMProviderError) as exc:
        provider.generate("hi")
    assert not isinstance(exc.value, LLMConnectionError)
    assert not isinstance(exc.value, LLMTimeoutError)


def test_claude_empty_response_raises():
    """Empty text content -> LLMEmptyResponseError."""
    client = MagicMock()
    client.messages.create.return_value = _message_response("   ")
    provider = make_claude_provider(client)

    with pytest.raises(LLMEmptyResponseError):
        provider.generate("hi")


def test_claude_no_content_raises():
    """Response with no content attr -> empty error."""
    client = MagicMock()
    response = MagicMock(spec=[])  # no content attr
    client.messages.create.return_value = response
    provider = make_claude_provider(client)

    with pytest.raises(LLMEmptyResponseError):
        provider.generate("hi")


def test_claude_no_text_blocks_raises():
    """Content with no text blocks -> empty error."""
    client = MagicMock()
    response = MagicMock()
    block = MagicMock(spec=[])  # no text attr
    response.content = [block]
    client.messages.create.return_value = response
    provider = make_claude_provider(client)

    with pytest.raises(LLMEmptyResponseError):
        provider.generate("hi")


# -- ClaudeProvider: optional dependency guard --


def test_claude_provider_missing_anthropic_package():
    """ImportError when 'llm' extras not installed."""
    with patch.object(llm_claude, "_anthropic", None):
        with pytest.raises(ImportError, match="llm"):
            ClaudeProvider(model="test-model")


# -- ClaudeProvider: custom max_tokens --


def test_claude_custom_max_tokens():
    """max_tokens is forwarded to the API call."""
    client = MagicMock()
    client.messages.create.return_value = _message_response("ok")
    provider = make_claude_provider(client, max_tokens=1024)

    provider.generate("hi")

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 1024


# -- Token usage --


def test_claude_exposes_token_usage_from_response():
    """Anthropic's usage.input_tokens / .output_tokens
    surface as TokenUsage on the provider after
    generate()."""
    from unstructured_mapping.pipeline import TokenUsage

    client = MagicMock()
    msg = _message_response("ok")
    msg.usage = MagicMock(input_tokens=123, output_tokens=45)
    client.messages.create.return_value = msg
    provider = make_claude_provider(client)

    provider.generate("hi")

    assert provider.last_token_usage == TokenUsage(
        input_tokens=123, output_tokens=45
    )


def test_claude_missing_usage_returns_none():
    """Responses lacking a usage object report None."""
    client = MagicMock()
    msg = _message_response("ok")
    del msg.usage
    client.messages.create.return_value = msg
    provider = make_claude_provider(client)

    provider.generate("hi")

    assert provider.last_token_usage is None
