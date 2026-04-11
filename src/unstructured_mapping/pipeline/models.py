"""Data models for the ingestion pipeline.

Intermediate representations passed between pipeline
stages. All models follow the same conventions as the
KG models: frozen dataclasses with slots, string FKs,
and tuples for immutable sequences.

See ``docs/pipeline/02_models.md`` for field rationale.
"""

from dataclasses import dataclass
from datetime import datetime

from unstructured_mapping.knowledge_graph.models import (
    EntityType,
)


@dataclass(frozen=True, slots=True)
class Chunk:
    """A segment of a document to be processed.

    For news articles (no chunking), the orchestrator
    wraps the article body in a single `Chunk` with
    ``chunk_index=0``, ``section_name=None``, and the
    full text. This keeps downstream stages uniform.

    :param document_id: Parent document's ID.
    :param chunk_index: Zero-based position within
        the document.
    :param text: The chunk's text content.
    :param section_name: Human-readable section label
        (e.g. ``"Q&A"``). ``None`` for unsegmented
        documents.
    :param token_estimate: Approximate token count
        for budget checks. Uses character count / 4
        as a rough approximation.
    """

    document_id: str
    chunk_index: int
    text: str
    section_name: str | None = None
    token_estimate: int = 0


@dataclass(frozen=True, slots=True)
class Mention:
    """A surface form found in text during detection.

    Represents a potential entity mention before
    resolution. The resolution stage uses
    ``candidate_ids`` to narrow the LLM prompt to
    relevant KG entities.

    :param surface_form: Exact text found
        (e.g. ``"the Fed"``).
    :param span_start: Character offset where the
        mention starts in the chunk text.
    :param span_end: Character offset where the
        mention ends in the chunk text.
    :param candidate_ids: Entity IDs whose aliases
        matched this surface form. Multiple candidates
        arise when an alias is shared (e.g. ``"Apple"``
        matches both Apple Inc. and AAPL).
    """

    surface_form: str
    span_start: int
    span_end: int
    candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedMention:
    """A mention matched to an existing KG entity.

    Produced by the resolution stage when a mention can
    be confidently linked to a single entity. Becomes a
    ``Provenance`` record during persistence.

    :param entity_id: The matched KG entity.
    :param surface_form: Original text that was resolved.
    :param context_snippet: Surrounding text for
        provenance and future disambiguation.
    :param section_name: Inherited from the chunk.
        ``None`` for unsegmented documents.
    """

    entity_id: str
    surface_form: str
    context_snippet: str
    section_name: str | None = None


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Output of the resolution stage for one chunk.

    Separates resolved mentions (ready for provenance)
    from unresolved mentions (need LLM disambiguation
    or represent unknown entities).

    :param resolved: Mentions matched to KG entities.
    :param unresolved: Mentions that could not be
        resolved — either zero candidates (unknown
        entity) or multiple candidates (ambiguous).
    """

    resolved: tuple[ResolvedMention, ...] = ()
    unresolved: tuple[Mention, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityProposal:
    """A new entity proposed by the LLM during resolution.

    Intermediate representation — not yet a full
    :class:`~unstructured_mapping.knowledge_graph.models.Entity`
    because it has not been validated against alias
    collisions, type constraints, or cross-chunk
    conflicts. The persistence stage creates the
    ``Entity`` after aggregation resolves any conflicts.

    See ``docs/pipeline/02_models.md`` § "EntityProposal"
    for field rationale.

    :param canonical_name: Proposed authoritative name.
    :param entity_type: Proposed type classification.
    :param description: LLM-generated context for future
        resolution and disambiguation.
    :param subtype: Optional finer classification within
        the entity type.
    :param aliases: Surface forms the LLM observed.
    :param source_chunk: Chunk index where this entity
        was first proposed.
    :param context_snippet: Surrounding text from the
        originating chunk.
    """

    canonical_name: str
    entity_type: EntityType
    description: str
    subtype: str | None = None
    aliases: tuple[str, ...] = ()
    source_chunk: int = 0
    context_snippet: str = ""


@dataclass(frozen=True, slots=True)
class ExtractedRelationship:
    """A relationship extracted by the LLM in pass 2.

    Intermediate representation before KG persistence.
    The orchestrator converts this into a full
    :class:`~unstructured_mapping.knowledge_graph.models.Relationship`
    by adding persistence fields (``document_id``,
    ``discovered_at``, ``run_id``, ``description``).

    Why not reuse ``Relationship`` directly?
        ``Relationship`` carries persistence metadata that
        the extractor should not set — those are the
        orchestrator's responsibility. Separating the
        extraction output from the storage model keeps
        the extractor focused on what the LLM produced.

    :param source_id: Subject entity ID.
    :param target_id: Object entity ID.
    :param relation_type: Free-form relationship label
        (e.g. ``"raised"``, ``"appointed"``).
    :param qualifier_id: Optional entity ID for n-ary
        qualification (typically a ROLE entity).
    :param valid_from: Relationship start date, or
        ``None`` if not mentioned or unparseable.
    :param valid_until: Relationship end date, or
        ``None`` if not mentioned or unparseable.
    :param context_snippet: ~100 chars of surrounding
        text from the source chunk.
    """

    source_id: str
    target_id: str
    relation_type: str
    qualifier_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    context_snippet: str = ""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Output of the extraction stage for one chunk.

    :param relationships: Directed relationships
        extracted between resolved entities.
    """

    relationships: tuple[ExtractedRelationship, ...] = ()
