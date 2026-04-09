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
    ResolvedMention,
    ResolutionResult,
)
from unstructured_mapping.pipeline.orchestrator import (
    ArticleResult,
    Pipeline,
    PipelineResult,
)
from unstructured_mapping.pipeline.resolution import (
    AliasResolver,
    EntityResolver,
)

__all__ = [
    "AliasResolver",
    "ArticleResult",
    "Chunk",
    "EntityDetector",
    "EntityResolver",
    "Mention",
    "Pipeline",
    "PipelineResult",
    "ResolvedMention",
    "ResolutionResult",
    "RuleBasedDetector",
]
