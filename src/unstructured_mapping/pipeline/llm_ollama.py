"""Ollama concrete :class:`LLMProvider`.

Ollama-first was chosen in ``docs/pipeline/01_design.md``
because it is free, local, and avoids API key
management while the pipeline is still iterating.
Users who need hosted-model quality can later swap in a
``ClaudeProvider`` or ``OpenAIProvider`` without
touching pipeline code -- that's the whole point of the
:class:`LLMProvider` ABC.

The ``ollama`` Python package is an optional dependency
(install with ``pip install
unstructured-mapping[llm]``). This module guards its
import so that:

- ``from unstructured_mapping.pipeline import
  LLMProvider`` still works without the extras
  installed.
- A clear, actionable ``ImportError`` is raised only
  when someone actually constructs an
  :class:`OllamaProvider`.
"""

import logging

import httpx

try:
    import ollama as _ollama
except ImportError:  # pragma: no cover - exercised via tests
    _ollama = None  # type: ignore[assignment]

from unstructured_mapping.pipeline.llm_provider import (
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

#: Fallback context window for Ollama models when the
#: ``/api/show`` metadata does not report ``num_ctx``.
#: 4K is the conservative default most Ollama models
#: ship with; users can pass ``context_window``
#: explicitly to override.
DEFAULT_CONTEXT_WINDOW = 4096

#: Default per-call timeout in seconds. Matches the
#: policy in ``docs/pipeline/01_design.md`` ("Timeout:
#: configurable, default 120 seconds per call").
DEFAULT_TIMEOUT = 120.0


class OllamaProvider(LLMProvider):
    """LLM provider backed by a local Ollama daemon.

    :param model: Ollama model tag (e.g.
        ``"llama3.1:8b"``, ``"mistral:7b"``).
    :param host: Ollama daemon URL. ``None`` uses the
        ``ollama`` package default (``http://localhost:11434``
        or ``$OLLAMA_HOST``).
    :param timeout: Per-call timeout in seconds. Wraps
        ``httpx.TimeoutException`` into
        :class:`LLMTimeoutError`.
    :param context_window: Override the model's context
        window in tokens. When ``None``, the provider
        attempts to read ``num_ctx`` from the model's
        ``/api/show`` metadata and falls back to
        :data:`DEFAULT_CONTEXT_WINDOW`. Passing an
        explicit value avoids the ``show`` call on
        construction.
    :raises ImportError: If the ``ollama`` package is
        not installed (the ``llm`` extras group is not
        present).

    Example::

        provider = OllamaProvider(
            model="llama3.1:8b",
            context_window=8192,
        )
        text = provider.generate(
            "List the entities in: Apple reported Q3.",
            system="You extract entity mentions.",
            json_mode=True,
        )
    """

    provider_name = "ollama"
    supports_json_mode = True

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        context_window: int | None = None,
    ) -> None:
        if _ollama is None:
            raise ImportError(
                "OllamaProvider requires the 'llm' "
                "optional dependency group. Install "
                "with: pip install "
                "unstructured-mapping[llm]"
            )
        self._model = model
        self._timeout = timeout
        self._client = _ollama.Client(
            host=host, timeout=timeout
        )
        if context_window is None:
            context_window = self._query_context_window()
        self._context_window = context_window

    # -- LLMProvider contract ---------------------------------

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def context_window(self) -> int:
        return self._context_window

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Call ``ollama.Client.generate``.

        Translates ``httpx`` and ``ollama`` errors into
        the provider-agnostic exception hierarchy so
        pipeline retry logic can treat all backends the
        same.
        """
        kwargs: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
        }
        if system is not None:
            kwargs["system"] = system
        if json_mode:
            kwargs["format"] = "json"
        try:
            response = self._client.generate(**kwargs)
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
        ) as exc:
            raise LLMConnectionError(
                f"Ollama unreachable: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama call timed out after "
                f"{self._timeout}s: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            # ollama.ResponseError and anything else the
            # client might raise. Wrap so callers only
            # have to handle LLMProviderError subclasses.
            raise LLMProviderError(
                f"Ollama generate failed: {exc}"
            ) from exc

        text = _extract_response_text(response)
        if not text:
            raise LLMEmptyResponseError(
                "Ollama returned an empty response"
            )
        return text

    # -- Internal helpers -------------------------------------

    def _query_context_window(self) -> int:
        """Best-effort lookup of ``num_ctx`` via ``show``.

        Ollama exposes model parameters through the
        ``/api/show`` endpoint. The response shape
        varies slightly across Ollama versions, so we
        search the ``parameters`` text and the
        ``model_info`` dict for a ``num_ctx`` hint.
        Failures fall back to
        :data:`DEFAULT_CONTEXT_WINDOW` with a debug log
        -- users who care about exact sizing should pass
        ``context_window`` explicitly.
        """
        try:
            info = self._client.show(self._model)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Ollama show(%s) failed, using default "
                "context window %d: %s",
                self._model,
                DEFAULT_CONTEXT_WINDOW,
                exc,
            )
            return DEFAULT_CONTEXT_WINDOW

        num_ctx = _find_num_ctx(info)
        if num_ctx is None:
            logger.debug(
                "Ollama show(%s) did not report "
                "num_ctx, using default %d",
                self._model,
                DEFAULT_CONTEXT_WINDOW,
            )
            return DEFAULT_CONTEXT_WINDOW
        return num_ctx


def _extract_response_text(response: object) -> str:
    """Pull the generated text out of Ollama's response.

    The ``ollama`` package has returned both plain dicts
    and a ``GenerateResponse`` dataclass across versions.
    Handle both shapes.
    """
    if isinstance(response, dict):
        value = response.get("response", "")
    else:
        value = getattr(response, "response", "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _ctx_from_model_info(
    model_info: object,
) -> int | None:
    """Extract context length from ``model_info`` dict.

    Looks for keys ending in ``".context_length"`` whose
    value is an ``int`` (e.g. ``"llama.context_length"``).
    """
    if not isinstance(model_info, dict):
        return None
    for key, value in model_info.items():
        if (
            isinstance(key, str)
            and key.endswith(".context_length")
            and isinstance(value, int)
        ):
            return value
    return None


def _ctx_from_parameters(
    parameters: object,
) -> int | None:
    """Extract ``num_ctx`` from plain-text parameters.

    Parses lines like ``num_ctx 8192`` in the
    plain-text ``parameters`` field.
    """
    if not isinstance(parameters, str):
        return None
    for line in parameters.splitlines():
        parts = line.strip().split()
        if (
            len(parts) == 2
            and parts[0] == "num_ctx"
            and parts[1].isdigit()
        ):
            return int(parts[1])
    return None


def _find_num_ctx(info: object) -> int | None:
    """Search a ``show`` response for a ``num_ctx`` int.

    Checks the structured ``model_info`` dict first
    (keys like ``"llama.context_length"``), then the
    plain-text ``parameters`` field (``num_ctx 8192``).
    Returns ``None`` when neither yields a usable value.
    """
    if isinstance(info, dict):
        model_info = info.get("model_info")
        parameters = info.get("parameters")
    else:
        model_info = getattr(info, "model_info", None)
        parameters = getattr(info, "parameters", None)

    return (
        _ctx_from_model_info(model_info)
        or _ctx_from_parameters(parameters)
    )
