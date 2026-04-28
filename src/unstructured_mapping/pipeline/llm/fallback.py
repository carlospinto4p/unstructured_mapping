"""Two-provider fallback chain.

Wraps two :class:`LLMProvider` instances so the pipeline
can run a fast/cheap primary by default and escalate to
a higher-quality secondary only on the genuinely hard
chunks. Keeps cost low for the common case while
rescuing ambiguous calls without a full cross-provider
run.

Why this exists
---------------

The resolver and extractor already talk to one provider
at a time via the :class:`LLMProvider` ABC, but in
practice operators pick one backend per run — there's no
graceful way to say "use Ollama for the easy stuff, fall
back to Claude when Ollama is unsure". This class adds
that routing at the provider layer, so callers swap
``OllamaProvider`` for ``FallbackLLMProvider(primary=...,
secondary=...)`` and nothing else in the pipeline needs
to change.

Escalation triggers
-------------------

Two paths escalate to the secondary:

1. **Primary raises** — any :class:`LLMProviderError`
   from the primary (connection error, timeout, empty
   response) is caught, logged, and the call is retried
   with the secondary.
2. **Primary output is ambiguous** — an injectable
   ``ambiguity_fn`` scores the raw response; if the
   score exceeds ``ambiguity_threshold`` the call is
   retried. The default scorer handles Pass 1 / Pass 2
   JSON shapes: invalid JSON → 1.0, missing/empty
   ``entities`` → 1.0, otherwise the fraction of entries
   that were new proposals (a high proposal ratio
   signals KG coverage gaps the secondary may resolve
   better).

Non-goals
---------

* Chains of more than two providers — nest
  ``FallbackLLMProvider(primary, FallbackLLMProvider(...))``
  if you really want a 3-deep cascade.
* Per-pass routing — one scorer runs for every
  ``generate`` call. Callers who need "Pass 1 to primary,
  Pass 2 always to secondary" should wire two
  pipelines.
"""

import json
import logging
from collections.abc import Callable

from unstructured_mapping.pipeline.llm.provider import (
    LLMProvider,
    LLMProviderError,
    TokenUsage,
)

logger = logging.getLogger(__name__)

#: Default ambiguity threshold. A pass-1 response where
#: >50% of entries were new proposals (rather than
#: resolutions against the KG) is treated as ambiguous
#: enough to warrant a secondary look. Tunable via the
#: constructor.
DEFAULT_AMBIGUITY_THRESHOLD = 0.5


def default_ambiguity_score(response: str) -> float:
    """Score the raw response on a 0..1 ambiguity scale.

    Designed for Pass 1 / Pass 2 JSON output shapes. The
    result is consumed by :class:`FallbackLLMProvider`;
    callers can plug in their own scorer when the
    response schema is different.

    Rules (first match wins):

    * Response is not valid JSON → ``1.0``. Malformed
      output is the strongest "try something else" signal.
    * Top-level object is missing both ``entities`` and
      ``relationships`` → ``1.0``. Neither schema present
      usually means the model drifted off-prompt.
    * ``entities`` is an empty list → ``1.0``. The LLM
      saw no entities in a chunk that presumably had at
      least one. High-precision recall gap.
    * ``entities`` is non-empty → proportion of entries
      that carry ``new_entity`` (vs. ``entity_id``). High
      ratio means the primary could not find matches in
      the KG context and chose to propose — the secondary
      may do better.
    * ``relationships`` present and an array → ``0.0``.
      Pass 2 responses are considered non-ambiguous at
      this layer; a fancier scorer can inspect confidence
      scores if needed.
    """
    try:
        data = json.loads(response)
    except json.JSONDecodeError, ValueError:
        return 1.0
    if not isinstance(data, dict):
        return 1.0
    entities = data.get("entities")
    relationships = data.get("relationships")
    if entities is None and relationships is None:
        return 1.0
    if entities is not None:
        if not isinstance(entities, list):
            return 1.0
        if not entities:
            return 1.0
        proposals = sum(
            1
            for e in entities
            if isinstance(e, dict)
            and (e.get("new_entity") is not None)
            and (not e.get("entity_id"))
        )
        return proposals / len(entities)
    # Pass 2 shape — non-ambiguous at this layer.
    if not isinstance(relationships, list):
        return 1.0
    return 0.0


class FallbackLLMProvider(LLMProvider):
    """LLM provider that escalates to a secondary on demand.

    :param primary: The fast/cheap provider tried first.
    :param secondary: The higher-quality provider tried
        when the primary raises or produces an ambiguous
        response.
    :param ambiguity_threshold: Score above which the
        primary's output triggers a retry. Defaults to
        :data:`DEFAULT_AMBIGUITY_THRESHOLD`. Set to
        ``1.0`` to only escalate on hard failures.
    :param ambiguity_fn: Function mapping a raw response
        string to a float in ``[0, 1]``. Defaults to
        :func:`default_ambiguity_score`, which handles
        Pass 1 / Pass 2 JSON shapes.

    Example::

        from unstructured_mapping.pipeline import (
            ClaudeProvider,
            FallbackLLMProvider,
            OllamaProvider,
        )

        primary = OllamaProvider(model="llama3.1:8b")
        secondary = ClaudeProvider(model="claude-sonnet-4-6")
        provider = FallbackLLMProvider(
            primary=primary,
            secondary=secondary,
            ambiguity_threshold=0.5,
        )
        text = provider.generate(prompt, system=sys, json_mode=True)
        # provider.last_token_usage sums both sides.
    """

    def __init__(
        self,
        primary: LLMProvider,
        secondary: LLMProvider,
        *,
        ambiguity_threshold: float = DEFAULT_AMBIGUITY_THRESHOLD,
        ambiguity_fn: Callable[[str], float] | None = None,
    ) -> None:
        if not 0.0 <= ambiguity_threshold <= 1.0:
            raise ValueError(
                "ambiguity_threshold must be in [0, 1], "
                f"got {ambiguity_threshold!r}"
            )
        self._primary = primary
        self._secondary = secondary
        self._threshold = ambiguity_threshold
        self._ambiguity_fn = ambiguity_fn or default_ambiguity_score
        #: Summed usage for the most recent call. Reset at
        #: the start of every :meth:`generate` so pipeline
        #: metrics accumulate both sides when escalation
        #: fires.
        self._last_usage: TokenUsage | None = None
        #: Which branch served the most recent call, for
        #: tests and operator logs.
        self.last_served_by: str | None = None
        #: Count of calls where the secondary was invoked
        #: (either hard-failure or ambiguity escalation).
        #: Operators can read this to monitor fallback
        #: pressure over a run.
        self.escalations: int = 0

    # -- LLMProvider contract ---------------------------------

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self._last_usage = None
        try:
            response = self._primary.generate(
                prompt, system=system, json_mode=json_mode
            )
        except LLMProviderError as exc:
            logger.info(
                "Primary %s failed (%s); escalating to secondary %s.",
                self._primary.provider_name,
                exc.__class__.__name__,
                self._secondary.provider_name,
            )
            self.escalations += 1
            response = self._secondary.generate(
                prompt, system=system, json_mode=json_mode
            )
            self._last_usage = self._secondary.last_token_usage
            self.last_served_by = self._secondary.provider_name
            return response

        primary_usage = self._primary.last_token_usage
        score = self._ambiguity_fn(response)
        if score > self._threshold:
            logger.info(
                "Primary %s ambiguity %.2f > threshold %.2f; "
                "escalating to secondary %s.",
                self._primary.provider_name,
                score,
                self._threshold,
                self._secondary.provider_name,
            )
            self.escalations += 1
            secondary_response = self._secondary.generate(
                prompt, system=system, json_mode=json_mode
            )
            self._last_usage = self._combine_usage(
                primary_usage, self._secondary.last_token_usage
            )
            self.last_served_by = self._secondary.provider_name
            return secondary_response

        self._last_usage = primary_usage
        self.last_served_by = self._primary.provider_name
        return response

    @property
    def model_name(self) -> str:
        # Composite name so run metadata distinguishes a
        # fallback chain from a bare primary call.
        return (
            f"{self._primary.provider_name}:"
            f"{self._primary.model_name}->"
            f"{self._secondary.provider_name}:"
            f"{self._secondary.model_name}"
        )

    @property
    def provider_name(self) -> str:
        return (
            f"fallback({self._primary.provider_name}->"
            f"{self._secondary.provider_name})"
        )

    @property
    def context_window(self) -> int:
        # Smaller of the two: the pipeline sizes prompts
        # to this number, and a bigger primary would
        # produce prompts the secondary cannot ingest on
        # escalation.
        return min(
            self._primary.context_window,
            self._secondary.context_window,
        )

    @property
    def supports_json_mode(self) -> bool:
        # Both sides must honour json_mode for the caller
        # to safely pass ``json_mode=True``. If only one
        # does, the non-supporting side would raise on
        # escalation.
        return (
            self._primary.supports_json_mode
            and self._secondary.supports_json_mode
        )

    @property
    def last_token_usage(self) -> TokenUsage | None:
        return self._last_usage

    # -- Internal helpers -----------------------------------

    @staticmethod
    def _combine_usage(
        primary: TokenUsage | None,
        secondary: TokenUsage | None,
    ) -> TokenUsage | None:
        """Sum usage across primary + secondary calls.

        Callers read ``last_token_usage`` once per
        ``generate``, so we hand back the combined total
        rather than one of the two.
        """
        if primary is None:
            return secondary
        if secondary is None:
            return primary
        return primary + secondary


__all__ = [
    "DEFAULT_AMBIGUITY_THRESHOLD",
    "FallbackLLMProvider",
    "default_ambiguity_score",
]
