"""Document segmentation for the ingestion pipeline.

Splits a document into :class:`~..models.Chunk` units
before the existing detection / resolution / extraction
stages. News articles get a single chunk (preserving the
current truncation-based behaviour); research reports,
earnings transcripts, and regulatory filings each use a
format-aware splitter.

See ``docs/pipeline/09_chunking.md`` for the full design
rationale and why section-aware splitting beats fixed-size
or embedding-based alternatives for the target document
types.

Pipeline integration (document-level alias pre-scan,
running entity header, chunk aggregation before
persistence) is the remit of the companion ``aggregation``
module — tracked as a follow-up in ``backlog.md``.
"""

from unstructured_mapping.pipeline.segmentation.base import (
    DocumentSegmenter,
    DocumentType,
)
from unstructured_mapping.pipeline.segmentation._filing import (
    FilingSegmenter,
)
from unstructured_mapping.pipeline.segmentation._news import (
    NewsSegmenter,
)
from unstructured_mapping.pipeline.segmentation._research import (
    ResearchSegmenter,
)
from unstructured_mapping.pipeline.segmentation._transcript import (
    TranscriptSegmenter,
)

__all__ = [
    "DocumentSegmenter",
    "DocumentType",
    "FilingSegmenter",
    "NewsSegmenter",
    "ResearchSegmenter",
    "TranscriptSegmenter",
]
