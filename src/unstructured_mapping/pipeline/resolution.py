"""Entity resolution — map mentions to KG entities.

The resolution stage takes ``Mention`` objects from
detection and maps them to concrete KG entities,
producing ``ResolvedMention`` records for persistence.

Two components:

- :class:`EntityResolver` — abstract base class defining
  the resolution interface.
- :class:`AliasResolver` — baseline implementation that
  resolves single-candidate mentions directly via exact
  alias lookup. Mentions with zero or multiple candidates
  are left unresolved for a downstream LLM-based resolver.

Why a baseline resolver?
    The LLM-based resolver (future) is expensive and slow.
    In practice, many mentions have exactly one candidate
    — the alias is unambiguous. The ``AliasResolver``
    handles these "easy" cases without an LLM call,
    reducing cost and latency. The LLM resolver only needs
    to handle the ambiguous remainder.

See ``docs/pipeline/design.md`` for how resolution fits
into the broader pipeline.
"""

from abc import ABC, abstractmethod

from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
    ResolvedMention,
    ResolutionResult,
)

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
