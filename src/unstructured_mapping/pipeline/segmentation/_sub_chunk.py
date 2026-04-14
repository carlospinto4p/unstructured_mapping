"""Hybrid-fallback paragraph sub-chunking.

Shared by every non-news segmenter for the case where a
single section (a 30-page Risk Factors, a long analyst
preamble, a hour-long keynote turn) exceeds the caller's
token budget. The design in ``docs/pipeline/09_chunking.md``
calls for paragraph-boundary splitting with 10-20% overlap
between consecutive sub-chunks so boundary entities aren't
dropped.

Size estimation is deliberately crude: word count, not a
real tokenizer. Callers pick a ``max_tokens`` empirically
for their LLM (word count × ~1.3 ≈ GPT-style tokens).
Keeping the estimator stdlib-only avoids a new dependency
just for chunk sizing.
"""

import math
from collections.abc import Iterable

from unstructured_mapping.pipeline.models import Chunk


def estimate_tokens(text: str) -> int:
    """Return a crude token estimate for ``text``.

    Uses whitespace-separated word count. For a GPT-style
    tokenizer, multiply by ~1.3 when choosing the
    ``max_tokens`` budget. The coarse estimate is enough
    to decide *whether* to sub-chunk; exact sizing is not
    worth a tokenizer dependency.
    """
    return len(text.split())


def sub_chunk_by_paragraph(
    text: str,
    max_tokens: int,
    *,
    overlap_ratio: float = 0.15,
) -> list[str]:
    """Split ``text`` into paragraph-aligned sub-chunks.

    Paragraphs are detected as blank-line-separated blocks
    (``"\\n\\n"`` or more). Each sub-chunk packs as many
    consecutive paragraphs as fit under ``max_tokens``; a
    trailing slice of the previous sub-chunk (sized by
    ``overlap_ratio``) is prepended to the next so an
    entity mention that straddles the boundary is still
    visible on both sides.

    A single paragraph that exceeds ``max_tokens`` on its
    own is emitted as one sub-chunk — we never split
    mid-sentence. Callers can inspect
    :func:`estimate_tokens` on each returned string if
    they need to warn on oversized blocks.

    :param text: Section body to split.
    :param max_tokens: Soft upper bound per sub-chunk, in
        :func:`estimate_tokens` units.
    :param overlap_ratio: Fraction of the previous
        sub-chunk's tail re-prepended to the next.
        Clamped to [0.0, 0.5]. Default 0.15 matches the
        design's 10-20% band.
    :return: Non-empty list of sub-chunk strings. Empty
        input yields an empty list.
    :raises ValueError: If ``max_tokens`` is non-positive.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    overlap_ratio = max(0.0, min(0.5, overlap_ratio))

    if not text.strip():
        return []

    paragraphs = [
        p.strip() for p in _iter_paragraphs(text)
    ]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return []

    if estimate_tokens(text) <= max_tokens:
        return [text.strip()]

    sub_chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        # An oversized paragraph gets its own sub-chunk —
        # splitting it further would risk mid-sentence
        # cuts that break entity mentions.
        if para_tokens > max_tokens and current:
            sub_chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
            continue
        if current_tokens + para_tokens > max_tokens and current:
            sub_chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens
    if current:
        sub_chunks.append("\n\n".join(current))

    if overlap_ratio == 0.0 or len(sub_chunks) == 1:
        return sub_chunks

    return _apply_overlap(
        sub_chunks, overlap_ratio, max_tokens
    )


def _iter_paragraphs(text: str) -> Iterable[str]:
    """Split on blank-line boundaries, preserving order."""
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if buf:
                yield "\n".join(buf)
                buf = []
        else:
            buf.append(line)
    if buf:
        yield "\n".join(buf)


def expand_section(
    document_id: str,
    *,
    section_name: str | None,
    body: str,
    start_index: int,
    max_tokens: int | None,
    overlap_ratio: float,
) -> list[Chunk]:
    """Emit one or more chunks for a single section body.

    Shared tail end of every non-news segmenter: given a
    section title and its cleaned body, either produce a
    single chunk (when no sub-chunking budget is set or
    the body fits) or run :func:`sub_chunk_by_paragraph`
    and emit one chunk per sub-piece. All pieces share the
    same ``section_name`` so downstream analytics treat
    them as one logical section.

    :param start_index: Running chunk index in the parent
        document. The caller passes ``len(chunks)`` before
        each call so indexes stay dense across sections.
    """
    if max_tokens is None:
        return [
            Chunk(
                document_id=document_id,
                chunk_index=start_index,
                text=body,
                section_name=section_name,
            )
        ]
    pieces = sub_chunk_by_paragraph(
        body, max_tokens, overlap_ratio=overlap_ratio
    )
    return [
        Chunk(
            document_id=document_id,
            chunk_index=start_index + i,
            text=piece,
            section_name=section_name,
        )
        for i, piece in enumerate(pieces)
    ]


def _apply_overlap(
    sub_chunks: list[str],
    overlap_ratio: float,
    max_tokens: int,
) -> list[str]:
    """Prepend a tail slice of each chunk onto the next.

    The overlap is measured in tokens — we take the last
    ``ceil(max_tokens * overlap_ratio)`` words from the
    preceding chunk and tack them onto the start of the
    current one (with a blank line separator so paragraph
    structure is preserved visually). The first chunk is
    unchanged.
    """
    overlap_tokens = max(
        1, math.ceil(max_tokens * overlap_ratio)
    )
    result: list[str] = [sub_chunks[0]]
    for prev, current in zip(sub_chunks, sub_chunks[1:]):
        prev_words = prev.split()
        tail = " ".join(prev_words[-overlap_tokens:])
        result.append(f"{tail}\n\n{current}" if tail else current)
    return result
