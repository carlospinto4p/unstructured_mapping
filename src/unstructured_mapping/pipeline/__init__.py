"""Ingestion pipeline for entity detection and mapping.

Processes articles through detection, resolution,
extraction, and persistence stages. See
``docs/pipeline/`` for design rationale.
"""

from unstructured_mapping.pipeline.detection import (
    EntityDetector,
    RuleBasedDetector,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
)

__all__ = [
    "Chunk",
    "EntityDetector",
    "Mention",
    "RuleBasedDetector",
]
