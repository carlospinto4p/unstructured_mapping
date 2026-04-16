"""Anthropic (Claude) concrete :class:`LLMProvider`.

Provides access to Claude models via the Anthropic
Messages API for quality/cost benchmarking against the
local Ollama baseline. See
``docs/pipeline/03_llm_interface.md`` for the full
provider contract.

The ``anthropic`` Python package is an optional
dependency (install with ``pip install
unstructured-mapping[llm]``). This module guards its
import so that:

- ``from unstructured_mapping.pipeline import
  LLMProvider`` still works without the extras
  installed.
- A clear, actionable ``ImportError`` is raised only
  when someone actually constructs a
  :class:`ClaudeProvider`.
"""

import logging

from unstructured_mapping.pipeline._optional_import import (
    require_llm_extra,
    try_import,
)
from unstructured_mapping.pipeline.llm_provider import (
    DEFAULT_TIMEOUT,
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
    TokenUsage,
)

_anthropic = try_import("anthropic")

logger = logging.getLogger(__name__)

#: Default context window for Claude 3+ models (200K
#: tokens). Override via ``context_window`` if using an
#: older or fine-tuned model with a smaller window.
DEFAULT_CONTEXT_WINDOW = 200_000

#: Default maximum tokens in the response. The
#: Anthropic Messages API requires ``max_tokens``.
#: 4096 is generous for entity-resolution JSON but
#: can be overridden for longer outputs.
DEFAULT_MAX_TOKENS = 4096


class ClaudeProvider(LLMProvider):
    """LLM provider backed by the Anthropic Messages API.

    :param model: Claude model identifier (e.g.
        ``"claude-sonnet-4-6"``,
        ``"claude-haiku-4-5-20251001"``).
    :param api_key: Anthropic API key. When ``None``,
        the ``anthropic`` SDK reads from the
        ``ANTHROPIC_API_KEY`` environment variable.
    :param timeout: Per-call timeout in seconds.
    :param context_window: Model context window in
        tokens. Defaults to
        :data:`DEFAULT_CONTEXT_WINDOW` (200K), suitable
        for Claude 3+ models. Override for older models
        or to limit budget calculations.
    :param max_tokens: Maximum tokens in the response.
        Defaults to :data:`DEFAULT_MAX_TOKENS` (4096).
        The Anthropic API requires this parameter.
    :raises ImportError: If the ``anthropic`` package is
        not installed (the ``llm`` extras group is not
        present).

    Example::

        provider = ClaudeProvider(
            model="claude-sonnet-4-6",
            context_window=200_000,
        )
        text = provider.generate(
            "List the entities in: Apple reported Q3.",
            system="You extract entity mentions.",
        )
    """

    provider_name = "anthropic"
    supports_json_mode = False

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        require_llm_extra(_anthropic, "ClaudeProvider")
        self._model = model
        self._timeout = timeout
        self._context_window = context_window
        self._max_tokens = max_tokens
        self._client = _anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout,
        )
        self._last_token_usage: TokenUsage | None = None

    # -- LLMProvider contract ---------------------------------

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def last_token_usage(self) -> TokenUsage | None:
        return self._last_token_usage

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Call ``anthropic.Anthropic.messages.create``.

        Translates ``anthropic`` SDK errors into the
        provider-agnostic exception hierarchy so pipeline
        retry logic can treat all backends the same.

        Claude does not currently expose a native JSON
        mode; the pipeline's prompt instructions are
        sufficient to get structured output. Passing
        ``json_mode=True`` raises ``ValueError`` -- check
        :attr:`supports_json_mode` before calling.
        """
        if json_mode:
            raise ValueError(
                "ClaudeProvider does not support "
                "json_mode=True. Check "
                "supports_json_mode before calling."
            )
        kwargs: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }
        if system is not None:
            kwargs["system"] = system
        try:
            response = self._client.messages.create(**kwargs)
        except _anthropic.APITimeoutError as exc:
            # Catch before APIConnectionError because
            # APITimeoutError is a subclass of it in the
            # anthropic SDK.
            raise LLMTimeoutError(
                f"Anthropic call timed out after {self._timeout}s: {exc}"
            ) from exc
        except _anthropic.APIConnectionError as exc:
            raise LLMConnectionError(
                f"Anthropic API unreachable: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(
                f"Anthropic generate failed: {exc}"
            ) from exc

        self._last_token_usage = _extract_usage(response)
        text = _extract_response_text(response)
        if not text:
            raise LLMEmptyResponseError(
                "Anthropic returned an empty response"
            )
        return text


def _extract_usage(response: object) -> TokenUsage | None:
    """Pull input/output token counts from a Message.

    The Anthropic Messages API returns a ``usage`` object
    on every response with ``input_tokens`` and
    ``output_tokens`` integers. Returns ``None`` when the
    attributes are missing so the caller can tell "provider
    didn't report" apart from zero tokens.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if input_tokens is None or output_tokens is None:
        return None
    return TokenUsage(
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
    )


def _extract_response_text(response: object) -> str:
    """Pull text from Anthropic's Message response.

    The Messages API returns a ``Message`` object with
    a ``content`` list of content blocks. Text blocks
    have a ``text`` attribute. Returns the first text
    block found, stripped of whitespace.
    """
    if not hasattr(response, "content"):
        return ""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    return ""
