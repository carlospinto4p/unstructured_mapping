"""Cold-start entity discovery from raw article text.

Normal pipeline flow assumes the KG already contains the
entities we care about: the detector finds mentions of
known aliases, and the resolver maps them to IDs. When the
KG is empty or tiny, detection finds nothing and the LLM
never sees the article. Cold-start mode solves that by
skipping detection/resolution entirely and asking the LLM
to discover entities straight from the text.

Design notes
------------

- **Reuses the pass 1 prompt and parser.** The pass 1
  schema already supports proposals for entities not in
  the KG (``new_entity`` field). With no candidates
  supplied, every returned entity is a proposal — exactly
  what we want for discovery. This keeps the JSON
  contract identical across modes so parser, retry logic,
  and validators are shared.
- **No detector, no resolver.** The orchestrator treats
  a configured :class:`ColdStartEntityDiscoverer` as a
  mode switch and bypasses the usual pipeline stages for
  the article.
- **Relationships deferred to the next run.** Cold-start
  focuses exclusively on populating the entity catalog;
  once entities exist, the normal pipeline will detect
  them in subsequent articles and extract relationships
  there. Doing both in one pass would require synthesising
  :class:`ResolvedMention` objects for freshly-created
  entities — possible, but kept out of the MVP to keep
  the code path small and auditable.

See ``docs/pipeline/13_cold_start.md`` for the full
rationale and usage recipes.
"""

import logging

from unstructured_mapping.pipeline.llm._retry import (
    retry_llm_call,
)
from unstructured_mapping.pipeline.llm.budget import (
    compute_budget,
)
from unstructured_mapping.pipeline.llm.parsers import (
    parse_pass1_response,
)
from unstructured_mapping.pipeline.llm.prompts import (
    PASS1_SYSTEM_PROMPT,
    build_pass1_user_prompt,
)
from unstructured_mapping.pipeline.llm.provider import (
    LLMProvider,
    TokenUsage,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
)

logger = logging.getLogger(__name__)


class ColdStartEntityDiscoverer:
    """Discover entities in raw text via an LLM.

    Calls the configured provider with the pass 1 prompt
    but no candidate entities, so the LLM treats every
    named entity it finds as a new proposal. The parser
    is invoked with an empty candidate set — any attempt
    to resolve to a pre-existing ID would therefore fail
    hallucination validation, which is the intended
    behaviour.

    :param provider: LLM backend to call. Any
        :class:`LLMProvider` implementation works.

    Usage::

        discoverer = ColdStartEntityDiscoverer(
            provider=OllamaProvider(model="llama3.1:8b"),
        )
        proposals = discoverer.discover(chunk)
        for p in proposals:
            print(p.canonical_name, p.entity_type)

    Typical integration is through :class:`Pipeline` with
    the ``cold_start_discoverer`` kwarg; the orchestrator
    handles persistence.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._last_token_usage: TokenUsage = TokenUsage()

    @property
    def provider(self) -> LLMProvider:
        """The LLM provider backing this discoverer."""
        return self._provider

    @property
    def last_token_usage(self) -> TokenUsage:
        """Token usage from the last :meth:`discover` call.

        Summed across retry attempts. Zero-valued when no
        call has been made or the provider does not expose
        usage counts.
        """
        return self._last_token_usage

    def discover(self, chunk: Chunk) -> tuple[EntityProposal, ...]:
        """Ask the LLM to propose entities from ``chunk``.

        :param chunk: The article or chunk text.
        :return: Entity proposals. Empty when the LLM
            finds no named entities.
        :raises LLMProviderError: After two consecutive
            validation failures (same retry policy as
            pass 1).
        """
        self._last_token_usage = TokenUsage()
        budget = compute_budget(
            self._provider.context_window,
            PASS1_SYSTEM_PROMPT,
        )
        chunk_text = chunk.text
        # Keep the text within the flexible budget so a
        # very long article does not exceed the context
        # window. Discovery is best-effort — truncation
        # is preferred over failure.
        if len(chunk_text) > budget.flexible * 4:
            chunk_text = chunk_text[: budget.flexible * 4]
            logger.warning(
                "Chunk %d truncated for cold-start "
                "discovery (context budget)",
                chunk.chunk_index,
            )

        user_prompt = build_pass1_user_prompt(
            kg_block="",
            chunk_text=chunk_text,
        )

        (resolved, proposals), usage = retry_llm_call(
            self._provider,
            user_prompt,
            PASS1_SYSTEM_PROMPT,
            lambda raw: parse_pass1_response(
                raw,
                candidate_ids=set(),
                chunk_index=chunk.chunk_index,
            ),
            pass_label="Cold-start",
        )
        self._last_token_usage = usage

        if resolved:
            # With no candidates, the LLM should never
            # return resolved mentions; log and drop.
            logger.warning(
                "Cold-start returned %d resolved "
                "mentions with empty candidate set; "
                "dropping.",
                len(resolved),
            )

        return proposals
