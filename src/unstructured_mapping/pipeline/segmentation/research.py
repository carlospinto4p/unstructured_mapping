"""Section-aware segmenter for research reports.

Equity and macro research reports are markdown-ish —
section titles appear as ATX headings (``## Valuation``,
``### Risks``), as setext headings (an underline of ``=``
or ``-``), or as bolded all-caps / title-case lines
separated by blank lines. Entity density is highest in
Valuation, Risks, Comparables, and Business Overview,
which are scattered rather than front-loaded; section-
aware splitting preserves that locality without dragging
the whole report through a single prompt.

Sub-chunking of oversized sections (hybrid fallback in
the design doc) is intentionally deferred — see the
follow-up backlog item. For first-pass coverage, one
section = one chunk, and the caller can notice a section
exceeding its token budget later.
"""

import re

from unstructured_mapping.pipeline.models import Chunk
from unstructured_mapping.pipeline.segmentation._sub_chunk import (
    expand_section,
)
from unstructured_mapping.pipeline.segmentation.base import (
    DocumentSegmenter,
)

#: Matches ATX headings (``# Title``, ``## Title`` …).
#: Anchored to line start so the body is never
#: mis-segmented on incidental hash characters.
_ATX_HEADING = re.compile(
    r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$"
)

#: Setext headings: a title line followed by ``===`` or
#: ``---`` of matching length. We detect the underline
#: and attribute the previous line as the title.
_SETEXT_UNDERLINE = re.compile(r"^\s*([=\-])\1{2,}\s*$")


class ResearchSegmenter(DocumentSegmenter):
    """Split a research report by markdown-style headings.

    Ignores content *before* the first heading — that is
    typically a cover or title block with no substantive
    entities. If the document has no detectable headings
    at all, the whole body is returned as a single
    chunk with ``section_name=None`` so nothing is lost.

    :param max_tokens: Optional soft cap (in
        :func:`segmentation._sub_chunk.estimate_tokens`
        units, i.e. whitespace-word count) triggering
        paragraph-level sub-chunking of oversized
        sections. ``None`` disables the hybrid fallback.
    :param overlap_ratio: Forwarded to
        :func:`sub_chunk_by_paragraph` when
        ``max_tokens`` fires.
    """

    def __init__(
        self,
        *,
        max_tokens: int | None = None,
        overlap_ratio: float = 0.15,
    ) -> None:
        self._max_tokens = max_tokens
        self._overlap_ratio = overlap_ratio

    def segment(
        self, document_id: str, text: str
    ) -> list[Chunk]:
        if not text.strip():
            return []

        sections = list(_parse_sections(text))
        if not sections:
            return expand_section(
                document_id,
                section_name=None,
                body=text.strip(),
                start_index=0,
                max_tokens=self._max_tokens,
                overlap_ratio=self._overlap_ratio,
            )

        chunks: list[Chunk] = []
        for name, body in sections:
            body_clean = body.strip()
            if not body_clean:
                continue
            chunks.extend(
                expand_section(
                    document_id,
                    section_name=name,
                    body=body_clean,
                    start_index=len(chunks),
                    max_tokens=self._max_tokens,
                    overlap_ratio=self._overlap_ratio,
                )
            )
        return chunks




def _parse_sections(text: str):
    """Yield ``(section_name, body_text)`` pairs.

    Recognises both ATX and setext heading styles, and
    drops any preamble that precedes the first heading.

    Setext headings are a title line immediately followed
    by a ``===``/``---`` underline. The title line has
    already been appended to the previous section when we
    notice the underline, so we pop it back off before
    emitting.
    """
    lines = text.splitlines()
    current_name: str | None = None
    current_body: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        atx = _ATX_HEADING.match(line)
        is_setext = (
            i + 1 < len(lines)
            and _SETEXT_UNDERLINE.match(lines[i + 1])
            and line.strip() != ""
        )
        if atx is not None:
            if current_name is not None:
                yield current_name, "\n".join(current_body)
            current_name = atx.group("title").strip()
            current_body = []
        elif is_setext:
            if current_name is not None:
                yield current_name, "\n".join(current_body)
            current_name = line.strip()
            current_body = []
            i += 2  # skip title + underline together
            continue
        else:
            if current_name is not None:
                current_body.append(line)
        i += 1
    if current_name is not None:
        yield current_name, "\n".join(current_body)
