"""Segmenter for SEC regulatory filings (10-K, 10-Q, 8-K).

Filings carry legally-standardised ``Item`` numbering —
``Item 1. Business``, ``Item 1A. Risk Factors``,
``Item 7. Management's Discussion and Analysis`` etc. —
which is the cleanest semantic boundary available and is
consistent across issuers. Entity density is highest in
``Risk Factors`` (competitors, regulators,
jurisdictions) and in ``MD&A`` (products, markets), both
buried well past any executive summary.

The segmenter:

- Splits on the ``Item N.`` / ``Item Nx.`` line pattern
  (case-insensitive, with optional variants like
  ``ITEM 7A``).
- Captures the textual title that follows the Item
  number and uses ``"Item 7A. Management's Discussion
  and Analysis"`` (or similar) as the ``section_name``.
- Drops any preamble before the first Item (typically
  the filing cover page with no substantive entities).
- Returns the whole body as a single untitled chunk when
  the text contains no recognisable Item pattern, so
  non-conforming inputs still flow through the pipeline.

Sub-chunking oversized Items (e.g. a 30-page Risk
Factors section) is deferred to the hybrid-fallback
follow-up.
"""

import re

from unstructured_mapping.pipeline.models import Chunk
from unstructured_mapping.pipeline.segmentation.base import (
    DocumentSegmenter,
)

#: Matches an Item heading such as ``Item 1.``,
#: ``Item 1A.``, or ``ITEM 7B.``. The number+suffix is
#: captured so the section name can be reconstructed
#: cleanly. The title (everything after the period on
#: the same line) is optional — some filings break the
#: title onto the next line, which we accept silently.
_ITEM_HEADING = re.compile(
    r"^\s*ITEM\s+(?P<num>\d+[A-Za-z]?)\.?\s*"
    r"(?P<title>.*?)\s*$",
    re.IGNORECASE,
)


class FilingSegmenter(DocumentSegmenter):
    """Split a SEC filing by ``Item`` heading."""

    def segment(
        self, document_id: str, text: str
    ) -> list[Chunk]:
        if not text.strip():
            return []

        sections = list(_parse_items(text))
        if not sections:
            return [
                Chunk(
                    document_id=document_id,
                    chunk_index=0,
                    text=text.strip(),
                )
            ]

        chunks: list[Chunk] = []
        for name, body in sections:
            body_clean = body.strip()
            if not body_clean:
                continue
            chunks.append(
                Chunk(
                    document_id=document_id,
                    chunk_index=len(chunks),
                    text=body_clean,
                    section_name=name,
                )
            )
        return chunks


def _parse_items(text: str):
    """Yield ``(section_name, body_text)`` per Item."""
    current_name: str | None = None
    current_body: list[str] = []
    for line in text.splitlines():
        match = _ITEM_HEADING.match(line)
        if match is not None and _looks_like_heading(line):
            if current_name is not None:
                yield current_name, "\n".join(current_body)
            num = match.group("num").upper()
            title = match.group("title").strip()
            current_name = (
                f"Item {num}. {title}"
                if title
                else f"Item {num}"
            )
            current_body = []
        else:
            if current_name is not None:
                current_body.append(line)
    if current_name is not None:
        yield current_name, "\n".join(current_body)


def _looks_like_heading(line: str) -> bool:
    """Guard against false positives.

    ``Item 1.`` can appear inside running text ("refer to
    Item 1A. Risk Factors"). We treat a line as a heading
    only when the Item clause dominates — no punctuation
    before the Item keyword, and the line stays short.
    """
    stripped = line.strip()
    if len(stripped) > 200:
        return False
    head = stripped.lower().lstrip(".")
    return head.startswith("item ")
