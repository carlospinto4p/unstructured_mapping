"""LLM provider abstraction for pipeline stages.

The pipeline's LLM-dependent stages (entity resolution
and relationship extraction) talk to models through the
:class:`LLMProvider` ABC rather than any concrete
backend. This keeps the stages:

- **Swappable** between local (Ollama) and hosted
  (Claude, OpenAI) providers without touching pipeline
  code.
- **Testable** via lightweight fakes that implement the
  ABC, so resolver/extractor tests don't need a real
  model.
- **Trackable** -- each provider reports its
  ``model_name`` and ``provider_name`` so
  :class:`~unstructured_mapping.knowledge_graph.models.IngestionRun`
  records capture "who produced this mention?".

See ``docs/pipeline/llm_interface.md`` for the full
contract, JSON schemas, prompt architecture, and token
budget rationale.

Concrete providers live in sibling modules so importing
the ABC never drags in optional third-party SDKs:

- :mod:`llm_ollama` -- ``OllamaProvider`` (requires the
  optional ``llm`` extras group).

This module intentionally has no third-party imports so
that ``from unstructured_mapping.pipeline import
LLMProvider`` works in the slimmest install.
"""

from abc import ABC, abstractmethod


class LLMProviderError(Exception):
    """Base exception for LLM provider failures.

    Providers raise subclasses so callers (typically the
    pipeline's retry/error-feedback layer) can
    distinguish retryable transient problems from
    permanent ones.
    """


class LLMConnectionError(LLMProviderError):
    """The provider could not reach its backend.

    Treated as a pipeline-level failure in
    ``docs/pipeline/design.md``: the run is marked
    :attr:`RunStatus.FAILED` because no further article
    can be processed.
    """


class LLMTimeoutError(LLMProviderError):
    """A ``generate`` call exceeded its timeout.

    Treated as article-level: the pipeline retries once
    per the policy in ``docs/pipeline/design.md``, then
    skips the article if the second attempt also times
    out.
    """


class LLMEmptyResponseError(LLMProviderError):
    """The provider returned an empty response.

    The caller logs the failure and skips the current
    chunk, per the error policy in
    ``docs/pipeline/design.md``.
    """


class LLMProvider(ABC):
    """Abstract base for LLM backends.

    Implementations wrap a concrete client (Ollama,
    Anthropic, OpenAI, ...) and expose a uniform
    ``generate`` call plus metadata needed by the
    orchestrator's token-budget calculator and run
    tracking.

    The ABC has four responsibilities:

    1. **Generate**: send a system + user prompt and
       return raw text. Parsing and validation are the
       pipeline's job, not the provider's, because JSON
       mode is implemented differently across backends
       (Ollama ``format="json"``, Anthropic tool-use,
       OpenAI ``response_format``).
    2. **Identify**: expose ``model_name`` and
       ``provider_name`` so
       :class:`IngestionRun` rows capture which model
       produced which entities/relationships.
    3. **Budget**: expose ``context_window`` so the
       orchestrator can size KG context and chunk text
       to fit.
    4. **Capabilities**: expose ``supports_json_mode``
       so callers know whether to rely on
       format-constrained output.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Send a prompt to the LLM and return raw text.

        The response is **not** parsed or validated --
        the caller (pipeline stage) is responsible for
        JSON parsing, schema validation, and retry
        logic. This split exists because validation
        rules are stage-specific while generation is
        provider-specific.

        :param prompt: The user prompt. Holds the
            stage's per-chunk payload (KG context block,
            chunk text, etc.).
        :param system: Optional system prompt. Holds
            fixed instructions that don't change between
            chunks, saving tokens across a batch.
        :param json_mode: When ``True``, ask the
            provider to constrain output to valid JSON.
            Providers that cannot honor this MUST raise
            ``ValueError`` -- check
            :attr:`supports_json_mode` before calling.
        :return: Raw text response from the model.
        :raises LLMConnectionError: Backend unreachable.
        :raises LLMTimeoutError: Timeout exceeded.
        :raises LLMEmptyResponseError: Empty response.
        :raises LLMProviderError: Any other
            provider-specific failure.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier (e.g. ``"llama3.1:8b"``).

        Written to
        :class:`~unstructured_mapping.knowledge_graph.models.IngestionRun`
        metadata so runs can be correlated with the
        exact model that produced them.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short provider identifier (e.g. ``"ollama"``).

        Paired with :attr:`model_name` in run metadata.
        Use a stable snake_case string so it works as a
        lookup key.
        """

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Total token capacity of the backing model.

        The orchestrator subtracts the system prompt and
        response headroom to compute the flexible budget
        (KG context + chunk text). See
        ``docs/pipeline/llm_interface.md`` for the
        budget allocation strategy.
        """

    @property
    @abstractmethod
    def supports_json_mode(self) -> bool:
        """Whether the provider honors ``json_mode=True``.

        Callers MUST check this before passing
        ``json_mode=True`` to :meth:`generate`; providers
        without JSON mode raise ``ValueError`` rather
        than silently returning unconstrained text.
        """
