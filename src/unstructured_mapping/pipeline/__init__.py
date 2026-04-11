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
from unstructured_mapping.pipeline.detection import (
    EntityDetector,
    RuleBasedDetector,
)
from unstructured_mapping.pipeline.llm_parsers import (
    Pass1ValidationError,
    parse_pass1_response,
)
from unstructured_mapping.pipeline.llm_claude import (
    ClaudeProvider,
)
from unstructured_mapping.pipeline.llm_ollama import (
    OllamaProvider,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
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
    build_kg_context_block,
    build_pass1_user_prompt,
)
from unstructured_mapping.pipeline.resolution import (
    AliasResolver,
    EntityResolver,
    LLMEntityResolver,
)

__all__ = [
    "AliasResolver",
    "ClaudeProvider",
    "DEFAULT_RESPONSE_HEADROOM",
    "ArticleResult",
    "Chunk",
    "EntityDetector",
    "EntityProposal",
    "EntityResolver",
    "LLMEntityResolver",
    "LLMConnectionError",
    "LLMEmptyResponseError",
    "LLMProvider",
    "LLMProviderError",
    "LLMTimeoutError",
    "Mention",
    "OllamaProvider",
    "PASS1_SYSTEM_PROMPT",
    "Pass1ValidationError",
    "Pipeline",
    "PipelineResult",
    "PromptBudget",
    "ResolvedMention",
    "ResolutionResult",
    "RuleBasedDetector",
    "build_kg_context_block",
    "parse_pass1_response",
    "build_pass1_user_prompt",
    "compute_budget",
    "estimate_tokens",
    "fit_candidates",
]
