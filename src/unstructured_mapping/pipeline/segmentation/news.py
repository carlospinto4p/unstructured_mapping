"""No-op segmenter for news articles.

News writing follows the inverted pyramid — the lead
paragraphs carry the who/what/where, and truncation to
leading paragraphs is a reasonable strategy elsewhere in
the pipeline. The segmenter therefore emits a single
chunk covering the entire article body; downstream
components apply any length cap.
"""

from unstructured_mapping.pipeline.models import Chunk
from unstructured_mapping.pipeline.segmentation.base import (
    DocumentSegmenter,
)


class NewsSegmenter(DocumentSegmenter):
    """Emit one chunk per news article.

    Exists as a first-class segmenter (rather than "no
    segmenter") so every pipeline caller can dispatch by
    ``DocumentType`` uniformly without special-casing
    news.
    """

    def segment(
        self, document_id: str, text: str
    ) -> list[Chunk]:
        if not text.strip():
            return []
        return [
            Chunk(
                document_id=document_id,
                chunk_index=0,
                text=text,
            )
        ]
