"""Ingestion pipeline for entity detection and mapping.

Processes articles through detection, resolution,
extraction, and persistence stages. See
``docs/pipeline/`` for design rationale.
"""

from unstructured_mapping.pipeline.budget import (
    DEFAULT_RESPONSE_HEADROOM,
    PromptBudget,
    compute_budget,
    estimate_tokens,
    fit_candidates,
)
from unstructured_mapping.pipeline.cold_start import (
    ColdStartEntityDiscoverer,
)
from unstructured_mapping.pipeline.detection import (
    EntityDetector,
    NoopDetector,
    RuleBasedDetector,
)
from unstructured_mapping.pipeline.extraction import (
    LLMRelationshipExtractor,
    RelationshipExtractor,
)
from unstructured_mapping.pipeline.llm_claude import (
    ClaudeProvider,
)
from unstructured_mapping.pipeline.llm_ollama import (
    OllamaProvider,
)
from unstructured_mapping.pipeline.llm_parsers import (
    Pass1ValidationError,
    Pass2ValidationError,
    parse_pass1_response,
    parse_pass2_response,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
    TokenUsage,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
    ExtractedRelationship,
    ExtractionResult,
    Mention,
    ResolvedMention,
    ResolutionResult,
)
from unstructured_mapping.pipeline.orchestrator import (
    ArticleResult,
    Pipeline,
    PipelineResult,
)
from unstructured_mapping.pipeline.prompts import (
    PASS1_SYSTEM_PROMPT,
    PASS2_SYSTEM_PROMPT,
    build_entity_list_block,
    build_kg_context_block,
    build_pass1_user_prompt,
    build_pass2_user_prompt,
)
from unstructured_mapping.pipeline.resolution import (
    AliasResolver,
    EntityResolver,
    LLMEntityResolver,
)

__all__ = [
    "AliasResolver",
    "ArticleResult",
    "Chunk",
    "ClaudeProvider",
    "ColdStartEntityDiscoverer",
    "DEFAULT_RESPONSE_HEADROOM",
    "EntityDetector",
    "EntityProposal",
    "EntityResolver",
    "ExtractedRelationship",
    "ExtractionResult",
    "LLMConnectionError",
    "LLMEmptyResponseError",
    "LLMEntityResolver",
    "LLMProvider",
    "LLMProviderError",
    "LLMRelationshipExtractor",
    "LLMTimeoutError",
    "Mention",
    "NoopDetector",
    "OllamaProvider",
    "PASS1_SYSTEM_PROMPT",
    "PASS2_SYSTEM_PROMPT",
    "Pass1ValidationError",
    "Pass2ValidationError",
    "Pipeline",
    "PipelineResult",
    "PromptBudget",
    "RelationshipExtractor",
    "ResolvedMention",
    "ResolutionResult",
    "RuleBasedDetector",
    "TokenUsage",
    "build_entity_list_block",
    "build_kg_context_block",
    "build_pass1_user_prompt",
    "build_pass2_user_prompt",
    "compute_budget",
    "estimate_tokens",
    "fit_candidates",
    "parse_pass1_response",
    "parse_pass2_response",
]
