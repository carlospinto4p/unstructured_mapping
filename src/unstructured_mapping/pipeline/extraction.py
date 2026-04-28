"""Relationship extraction — pass 2 of the LLM pipeline.

The extraction stage takes resolved entities from pass 1
and extracts directed relationships between them from the
article text. This is the second of two LLM calls per
chunk, as defined in ``docs/pipeline/03_llm_interface.md``.

Two components:

- :class:`RelationshipExtractor` — abstract base class
  defining the extraction interface.
- :class:`LLMRelationshipExtractor` — LLM-based
  implementation that sends chunk text and resolved
  entities to a language model for relationship
  extraction.

Why a separate ABC?
    The same rationale as :class:`EntityResolver`:
    the ABC decouples the pipeline from any specific LLM
    backend or extraction strategy. Tests inject fakes,
    and alternative implementations (rule-based, hybrid)
    can slot in without touching the orchestrator.

See ``docs/pipeline/01_design.md`` for how extraction
fits into the broader pipeline.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from unstructured_mapping.knowledge_graph.models import (
    Entity,
)
from unstructured_mapping.pipeline._batch_lookup import (
    resolve_batch,
)
from unstructured_mapping.pipeline.llm._retry import (
    retry_llm_call,
)
from unstructured_mapping.pipeline.llm.budget import (
    compute_budget,
)
from unstructured_mapping.pipeline.llm.parsers import (
    parse_pass2_response,
)
from unstructured_mapping.pipeline.llm.prompts import (
    PASS2_SYSTEM_PROMPT,
    build_entity_list_block,
    build_pass2_user_prompt,
)
from unstructured_mapping.pipeline.llm.provider import (
    LLMProvider,
    TokenUsage,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
    ExtractionResult,
    ResolvedMention,
)


class RelationshipExtractor(ABC):
    """Abstract base class for relationship extraction.

    Subclasses implement :meth:`extract` to identify
    directed relationships between resolved entities
    in a chunk of text. The pipeline calls this once
    per chunk, after entity resolution.
    """

    @abstractmethod
    def extract(
        self,
        chunk: Chunk,
        entities: tuple[ResolvedMention, ...],
    ) -> ExtractionResult:
        """Extract relationships from chunk text.

        :param chunk: The text chunk being processed.
        :param entities: Resolved entity mentions from
            pass 1 (both alias-resolved and LLM-resolved).
        :return: Extraction result with directed
            relationships between the provided entities.
        """


class LLMRelationshipExtractor(RelationshipExtractor):
    """LLM-based relationship extractor (pass 2).

    Sends chunk text and the resolved entity list to a
    language model, which returns directed relationships
    between those entities. The extractor validates the
    response, resolves entity references (IDs or names)
    to concrete entity IDs, and drops invalid entries.

    :param provider: The LLM backend to call.
    :param entity_lookup: Callable that returns an
        ``Entity`` for a given entity ID, or ``None``
        if not found. Typically
        ``KnowledgeStore.get_entity``. Used for the
        single-id lookup path in response parsing.
    :param name_lookup: Callable that returns an
        ``Entity`` for a given canonical name, or
        ``None`` if not found. Typically
        ``KnowledgeStore.find_by_name``. Needed because
        the LLM may reference entities by name instead
        of ID.
    :param proposals: Entity proposals from pass 1
        (entities not yet in the KG). The extractor
        tracks these so the LLM can reference them by
        canonical name.
    :param entity_batch_lookup: Optional bulk variant
        of ``entity_lookup`` that accepts a list of ids
        and returns a ``{id: Entity}`` mapping.
        Typically ``KnowledgeStore.get_entities``. When
        supplied, the extractor builds its pre-LLM
        lookup map with one query instead of one per
        resolved mention — the hot-path win for chunks
        with many resolved entities.

    Why ``name_lookup`` in addition to ``entity_lookup``?
        The LLM may return canonical names instead of
        hex IDs (see ``03_llm_interface.md`` § "Why
        allow canonical names, not just IDs?"). The
        name lookup resolves those references.

    Usage::

        extractor = LLMRelationshipExtractor(
            provider=ollama,
            entity_lookup=store.get_entity,
            name_lookup=store.find_by_name,
            proposals=resolver.proposals,
            entity_batch_lookup=store.get_entities,
        )
        result = extractor.extract(chunk, resolved)

        for rel in result.relationships:
            print(f"{rel.source_id} -> {rel.target_id}")
    """

    def __init__(
        self,
        provider: LLMProvider,
        entity_lookup: Callable[[str], Entity | None],
        name_lookup: Callable[[str], Entity | None],
        proposals: Sequence[EntityProposal] = (),
        entity_batch_lookup: (
            Callable[[list[str]], dict[str, Entity]] | None
        ) = None,
    ) -> None:
        self._provider = provider
        self._entity_lookup = entity_lookup
        self._name_lookup = name_lookup
        self._proposals = proposals
        self._entity_batch_lookup = entity_batch_lookup
        self._last_token_usage: TokenUsage = TokenUsage()

    @property
    def last_token_usage(self) -> TokenUsage:
        """Token usage from the last :meth:`extract` call.

        Summed across retry attempts. Zero-valued when no
        call has been made or the provider does not expose
        usage counts.
        """
        return self._last_token_usage

    def extract(
        self,
        chunk: Chunk,
        entities: tuple[ResolvedMention, ...],
    ) -> ExtractionResult:
        """Extract relationships via an LLM call.

        Builds the entity list block and user prompt,
        calls the LLM, and parses/validates the
        response. On validation failure the error
        message is appended to the prompt and one retry
        is attempted. After two failures a
        :class:`LLMProviderError` is raised.

        :param chunk: The text chunk being processed.
        :param entities: Resolved entity mentions from
            pass 1.
        :return: Extraction result with validated
            relationships.
        :raises LLMProviderError: After two consecutive
            validation failures.
        """
        self._last_token_usage = TokenUsage()
        if not entities:
            return ExtractionResult()

        known_ids, name_to_id = self._build_lookup_maps(entities)

        budget = compute_budget(
            self._provider.context_window,
            PASS2_SYSTEM_PROMPT,
        )

        entity_block = build_entity_list_block(entities, self._proposals)
        user_prompt = build_pass2_user_prompt(
            entity_block,
            chunk.text[: budget.flexible * 4],
        )

        relationships, usage = retry_llm_call(
            self._provider,
            user_prompt,
            PASS2_SYSTEM_PROMPT,
            lambda raw: parse_pass2_response(raw, known_ids, name_to_id),
            pass_label="Pass 2",
        )
        self._last_token_usage = usage

        return ExtractionResult(relationships=relationships)

    def _build_lookup_maps(
        self,
        entities: tuple[ResolvedMention, ...],
    ) -> tuple[set[str], dict[str, str]]:
        """Build ID set and name-to-ID mapping.

        Combines resolved entity IDs with proposal
        canonical names so the parser can resolve both
        ID and name references from the LLM response.

        :return: Tuple of (known_ids, name_to_id).
        """
        known_ids: set[str] = set()
        name_to_id: dict[str, str] = {}

        ids = [rm.entity_id for rm in entities]
        known_ids.update(ids)
        found = resolve_batch(
            ids,
            single=self._entity_lookup,
            batch=self._entity_batch_lookup,
        )
        for eid in ids:
            entity = found.get(eid)
            if entity is not None:
                name_to_id[entity.canonical_name] = eid

        for proposal in self._proposals:
            name = self._name_lookup(proposal.canonical_name)
            if name is not None:
                known_ids.add(name.entity_id)
                name_to_id[proposal.canonical_name] = name.entity_id

        return known_ids, name_to_id
