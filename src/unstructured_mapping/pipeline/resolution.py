"""Entity resolution — map mentions to KG entities.

The resolution stage takes ``Mention`` objects from
detection and maps them to concrete KG entities,
producing ``ResolvedMention`` records for persistence.

Three components:

- :class:`EntityResolver` — abstract base class defining
  the resolution interface.
- :class:`AliasResolver` — baseline implementation that
  resolves single-candidate mentions directly via exact
  alias lookup. Mentions with zero or multiple candidates
  are left unresolved for a downstream LLM-based resolver.
- :class:`LLMEntityResolver` — LLM-based resolver that
  sends chunk text and KG candidates to a language model
  for entity resolution. Handles ambiguous and unknown
  mentions that the alias resolver cannot resolve.

Why a baseline resolver?
    The LLM-based resolver is expensive and slow. In
    practice, many mentions have exactly one candidate
    — the alias is unambiguous. The ``AliasResolver``
    handles these "easy" cases without an LLM call,
    reducing cost and latency. The LLM resolver only needs
    to handle the ambiguous remainder.

See ``docs/pipeline/01_design.md`` for how resolution fits
into the broader pipeline.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from unstructured_mapping.knowledge_graph.models import (
    Entity,
)
from unstructured_mapping.pipeline._llm_retry import (
    retry_llm_call,
)
from unstructured_mapping.pipeline.budget import (
    compute_budget,
    fit_candidates,
)
from unstructured_mapping.pipeline.llm_parsers import (
    parse_pass1_response,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProvider,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
    Mention,
    ResolvedMention,
    ResolutionResult,
)
from unstructured_mapping.pipeline.prompts import (
    PASS1_SYSTEM_PROMPT,
    build_kg_context_block,
    build_pass1_user_prompt,
)

logger = logging.getLogger(__name__)

#: Default number of characters on each side of a mention
#: to include in the context snippet.
CONTEXT_WINDOW: int = 100


class EntityResolver(ABC):
    """Abstract base class for entity resolution.

    Subclasses implement :meth:`resolve` to map detected
    mentions to KG entities. The pipeline calls this once
    per chunk, after detection.
    """

    @abstractmethod
    def resolve(
        self,
        chunk: Chunk,
        mentions: tuple[Mention, ...],
    ) -> ResolutionResult:
        """Resolve mentions against the knowledge graph.

        :param chunk: The text chunk being processed.
        :param mentions: Mentions detected in this chunk.
        :return: Resolution result separating resolved
            from unresolved mentions.
        """


def _extract_snippet(
    text: str,
    start: int,
    end: int,
    window: int = CONTEXT_WINDOW,
) -> str:
    """Extract a context snippet around a mention.

    Returns the mention text plus up to ``window``
    characters on each side, trimmed to word boundaries
    to avoid cutting words in half. Leading/trailing
    ellipsis indicates truncation.

    :param text: Full chunk text.
    :param start: Mention start offset.
    :param end: Mention end offset.
    :param window: Characters of context on each side.
    :return: Context snippet string.
    """
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)

    # Trim to word boundaries (don't cut mid-word)
    if ctx_start > 0:
        space = text.find(" ", ctx_start)
        if space != -1 and space < start:
            ctx_start = space + 1

    if ctx_end < len(text):
        space = text.rfind(" ", end, ctx_end)
        if space != -1:
            ctx_end = space

    snippet = text[ctx_start:ctx_end]

    if ctx_start > 0:
        snippet = "..." + snippet
    if ctx_end < len(text):
        snippet = snippet + "..."

    return snippet


class AliasResolver(EntityResolver):
    """Baseline resolver using exact alias lookup.

    Resolves mentions that have exactly one candidate
    entity ID — the alias is unambiguous, so no LLM call
    is needed. Mentions with zero candidates (unknown
    entity) or multiple candidates (ambiguous alias) are
    returned as unresolved.

    :param context_window: Number of characters on each
        side of a mention to include in the context
        snippet. Defaults to :data:`CONTEXT_WINDOW`.

    Usage::

        resolver = AliasResolver()
        result = resolver.resolve(chunk, mentions)

        for rm in result.resolved:
            print(f"{rm.surface_form} -> {rm.entity_id}")

        for um in result.unresolved:
            print(f"{um.surface_form} needs LLM")
    """

    def __init__(
        self, context_window: int = CONTEXT_WINDOW
    ) -> None:
        self._context_window = context_window

    def resolve(
        self,
        chunk: Chunk,
        mentions: tuple[Mention, ...],
    ) -> ResolutionResult:
        """Resolve single-candidate mentions directly.

        :param chunk: The text chunk being processed.
        :param mentions: Mentions detected in this chunk.
        :return: Result with resolved (single-candidate)
            and unresolved (zero or multi-candidate)
            mentions.
        """
        resolved: list[ResolvedMention] = []
        unresolved: list[Mention] = []

        for mention in mentions:
            if len(mention.candidate_ids) == 1:
                snippet = _extract_snippet(
                    chunk.text,
                    mention.span_start,
                    mention.span_end,
                    self._context_window,
                )
                resolved.append(
                    ResolvedMention(
                        entity_id=mention.candidate_ids[
                            0
                        ],
                        surface_form=mention.surface_form,
                        context_snippet=snippet,
                        section_name=chunk.section_name,
                    )
                )
            else:
                unresolved.append(mention)

        return ResolutionResult(
            resolved=tuple(resolved),
            unresolved=tuple(unresolved),
        )


class LLMEntityResolver(EntityResolver):
    """LLM-based resolver for ambiguous mentions.

    Sends chunk text and KG candidate entities to a
    language model, which returns resolved entity IDs
    and/or proposals for new entities not yet in the KG.

    The resolver composes the prompt builder, token budget
    manager, and response parser into a single
    :meth:`resolve` call. It does **not** retry on
    validation failure — that is handled by a separate
    retry wrapper (backlog item 2e).

    :param provider: The LLM backend to call.
    :param entity_lookup: Callable that returns an
        ``Entity`` for a given entity ID, or ``None``
        if not found. Typically
        ``KnowledgeStore.get_entity``.
    :param prev_entities: Resolved mentions from
        earlier chunks in the same document, used for
        the running entity header. Defaults to empty.

    Why ``entity_lookup`` instead of ``KnowledgeStore``?
        Accepting a callable avoids coupling the resolver
        to the storage layer. Tests inject a simple dict
        lookup; production code passes
        ``store.get_entity``.

    Usage::

        resolver = LLMEntityResolver(
            provider=ollama,
            entity_lookup=store.get_entity,
        )
        result = resolver.resolve(chunk, mentions)

        for rm in result.resolved:
            print(f"{rm.surface_form} -> {rm.entity_id}")

        for ep in resolver.proposals:
            print(f"NEW: {ep.canonical_name}")
    """

    def __init__(
        self,
        provider: LLMProvider,
        entity_lookup: Callable[[str], Entity | None],
        prev_entities: Sequence[ResolvedMention] = (),
    ) -> None:
        self._provider = provider
        self._entity_lookup = entity_lookup
        self._prev_entities = prev_entities
        self._proposals: tuple[EntityProposal, ...] = ()

    @property
    def proposals(self) -> tuple[EntityProposal, ...]:
        """Entity proposals from the last :meth:`resolve`.

        New entities that the LLM identified but that
        do not exist in the KG. Empty until
        :meth:`resolve` is called.
        """
        return self._proposals

    def resolve(
        self,
        chunk: Chunk,
        mentions: tuple[Mention, ...],
    ) -> ResolutionResult:
        """Resolve mentions via an LLM call.

        Collects candidate entities from mention IDs,
        fits them into the token budget, builds the
        prompt, calls the LLM, and parses/validates the
        response.

        On validation failure the error message is
        appended to the user prompt and one retry is
        attempted (per ``03_llm_interface.md`` §
        "Retry and error feedback"). After two failures
        a :class:`LLMProviderError` is raised so the
        orchestrator can skip the chunk.

        :param chunk: The text chunk being processed.
        :param mentions: Mentions detected in this chunk.
        :return: Resolution result. Proposals for new
            entities are available via :attr:`proposals`.
        :raises LLMProviderError: After two consecutive
            validation failures.
        """
        self._proposals = ()

        if not mentions:
            return ResolutionResult()

        candidates = self._collect_candidates(mentions)

        budget = compute_budget(
            self._provider.context_window,
            PASS1_SYSTEM_PROMPT,
        )
        fitted, chunk_text = fit_candidates(
            candidates, chunk.text, budget.flexible
        )

        kg_block = build_kg_context_block(fitted)
        user_prompt = build_pass1_user_prompt(
            kg_block, chunk_text, self._prev_entities
        )
        fitted_ids = {e.entity_id for e in fitted}

        resolved, proposals = retry_llm_call(
            self._provider,
            user_prompt,
            PASS1_SYSTEM_PROMPT,
            lambda raw: parse_pass1_response(
                raw, fitted_ids, chunk.chunk_index
            ),
            pass_label="Pass 1",
        )

        resolved = tuple(
            ResolvedMention(
                entity_id=rm.entity_id,
                surface_form=rm.surface_form,
                context_snippet=rm.context_snippet,
                section_name=chunk.section_name,
            )
            for rm in resolved
        )
        self._proposals = proposals
        return ResolutionResult(resolved=resolved)

    def _collect_candidates(
        self,
        mentions: tuple[Mention, ...],
    ) -> list[Entity]:
        """Gather unique candidate entities from mentions.

        Looks up each candidate ID via the injected
        ``entity_lookup``. Missing entities (``None``)
        are silently skipped — they may have been
        deleted between detection and resolution.
        """
        seen: set[str] = set()
        candidates: list[Entity] = []
        for mention in mentions:
            for eid in mention.candidate_ids:
                if eid in seen:
                    continue
                seen.add(eid)
                entity = self._entity_lookup(eid)
                if entity is not None:
                    candidates.append(entity)
                else:
                    logger.warning(
                        "Candidate %s not found in KG",
                        eid,
                    )
        return candidates
