"""Segmenter ABC and document-type enum.

A :class:`DocumentSegmenter` takes raw document text plus
its parent document id and returns an ordered list of
:class:`~..models.Chunk` objects. Each concrete subclass
handles one document format — the caller picks the class
based on the known document type, rather than having the
segmenter auto-detect (which would be brittle and hide
configuration in the splitter).

The ``DocumentType`` enum names the formats the pipeline
supports today. It is deliberately *not* persisted as part
of the KG: document type is an ingestion-time property
(see ``docs/pipeline/09_chunking.md``), so it lives with
the article and feeds into segmenter selection but never
crosses into entity storage.
"""

from abc import ABC, abstractmethod
from enum import Enum

from unstructured_mapping.pipeline.models import Chunk


class DocumentType(str, Enum):
    """Ingestion-time document format.

    The segmenter for a given document is chosen from this
    tag. News articles keep the current pipeline
    behaviour (one chunk, truncation handled downstream);
    the other three types require format-aware splitting
    because key entities sit far from the document head.
    """

    NEWS = "news"
    RESEARCH = "research"
    TRANSCRIPT = "transcript"
    FILING = "filing"


class DocumentSegmenter(ABC):
    """Split a document into ordered pipeline chunks.

    Contract:

    - Input is plain text plus a stable ``document_id``.
      PDF/HTML conversion is a preprocessing concern, not
      a segmenter responsibility (see the design doc's
      "What this design does NOT cover" section).
    - Output is a non-empty, ordered list of
      :class:`Chunk`. Empty input produces an empty list
      so callers don't have to special-case it.
    - ``chunk_index`` is zero-based and dense. Callers
      can assume ``chunks[i].chunk_index == i``.
    - ``section_name`` carries the human-readable section
      label (``"Risk Factors"``, ``"Q&A"``, …) when the
      segmenter recognises one. ``None`` is used for
      fallback/fixed splits and for segmenters that have
      no section concept (news).
    """

    @abstractmethod
    def segment(
        self, document_id: str, text: str
    ) -> list[Chunk]:
        """Split ``text`` into chunks for the pipeline."""
