"""Data models for the ingestion pipeline.

Intermediate representations passed between pipeline
stages. All models follow the same conventions as the
KG models: frozen dataclasses with slots, string FKs,
and tuples for immutable sequences.

See ``docs/pipeline/models.md`` for field rationale.
"""

from dataclasses import dataclass


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
