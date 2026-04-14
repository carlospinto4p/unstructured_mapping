"""Segmenter for earnings-call transcripts.

Two natural boundaries exist in a typical transcript:

1. **Major sections** — a transcript is split into
   prepared remarks (management narrative) and a Q&A
   block. Published transcripts label the divide with a
   line such as ``Q&A`` or ``Questions and Answers``.
   Analysts probing competitors, supplier risks, or
   regulatory exposure tend to surface Q&A-only entities,
   so the Q&A block deserves to be its own chunk at
   minimum.
2. **Speaker turns** — inside each section, every turn
   is headed by a speaker label like
   ``Tim Cook - CEO:`` or ``Operator:``. A speaker turn
   is a coherent semantic unit — a single answer, a
   single question — and is the right granularity for
   entity resolution.

The segmenter picks per-speaker-turn chunking because
that yields the most useful ``section_name`` metadata
(who spoke) for later filtering. A caller that wants the
coarser "prepared-remarks vs Q&A" view can still
aggregate post-hoc because the Q&A header appears as its
own speaker-less chunk.
"""

import re

from unstructured_mapping.pipeline.models import Chunk
from unstructured_mapping.pipeline.segmentation.base import (
    DocumentSegmenter,
)

#: Matches a speaker label at the start of a line. A
#: label is a ``Name`` (1–5 capitalised words), optional
#: ``- Title`` suffix, and a trailing colon. The trailing
#: text on the same line is captured as the first part of
#: the turn body.
_SPEAKER_LABEL = re.compile(
    r"^(?P<speaker>"
    r"[A-Z][\w.'-]*"
    r"(?:\s+[A-Z][\w.'-]*){0,4}"
    r"(?:\s*-\s*[A-Z][\w\s.,&'-]*?)?"
    r")\s*:\s*(?P<rest>.*)$"
)

#: Standalone divider lines that announce the Q&A block.
#: Compared case-insensitively against the stripped line.
_QA_DIVIDERS = {
    "q&a",
    "qa",
    "questions and answers",
    "question and answer session",
    "question-and-answer session",
}


class TranscriptSegmenter(DocumentSegmenter):
    """Split a transcript into one chunk per speaker turn.

    A Q&A divider line becomes its own zero-body chunk
    with ``section_name="Q&A"`` so downstream consumers
    can recover the macro structure without re-parsing.
    """

    def segment(
        self, document_id: str, text: str
    ) -> list[Chunk]:
        if not text.strip():
            return []

        turns = list(_parse_turns(text))
        if not turns:
            # No speaker labels detected — fall back to
            # one chunk so the content isn't lost.
            return [
                Chunk(
                    document_id=document_id,
                    chunk_index=0,
                    text=text.strip(),
                )
            ]

        chunks: list[Chunk] = []
        for speaker, body in turns:
            body_clean = body.strip()
            if not body_clean and speaker != "Q&A":
                continue
            chunks.append(
                Chunk(
                    document_id=document_id,
                    chunk_index=len(chunks),
                    text=body_clean,
                    section_name=speaker,
                )
            )
        return chunks


def _parse_turns(text: str):
    """Yield ``(speaker, body)`` pairs in order.

    Q&A divider lines are emitted as
    ``("Q&A", "")`` so the caller keeps the macro-
    structure coordinate.
    """
    current_speaker: str | None = None
    current_body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() in _QA_DIVIDERS:
            if current_speaker is not None:
                yield current_speaker, "\n".join(current_body)
            current_speaker = None
            current_body = []
            yield "Q&A", ""
            continue
        match = _SPEAKER_LABEL.match(line)
        if match is not None:
            if current_speaker is not None:
                yield current_speaker, "\n".join(current_body)
            current_speaker = match.group("speaker").strip()
            rest = match.group("rest")
            current_body = [rest] if rest else []
        else:
            if current_speaker is not None:
                current_body.append(line)
    if current_speaker is not None:
        yield current_speaker, "\n".join(current_body)
