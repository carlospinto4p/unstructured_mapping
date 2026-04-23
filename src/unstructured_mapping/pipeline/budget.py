"""Token budget management for LLM prompts.

The pipeline must fit system instructions, KG context,
chunk text, and response headroom into the model's
context window. This module estimates token counts and
truncates content when the budget is exceeded.

Budget strategy (from ``docs/pipeline/03_llm_interface.md``):

1. **Fixed regions** — system prompt and response headroom
   are measured/configured once at pipeline startup.
2. **Flexible regions** — KG context and chunk text share
   the remainder. Chunk text gets priority (it is the
   source material); KG context fills whatever is left.
3. **Overflow** — if KG context is too large, candidates
   are ranked by alias match count and the least-matched
   are dropped. If the chunk text alone exceeds the
   flexible budget, it is truncated to leading paragraphs.

Why character-based estimation?
    Exact token counts require a model-specific tokenizer
    that varies across providers. The ``ceil(chars / 4)``
    approximation is sufficient for budget checks — the
    response headroom absorbs the estimation error. An
    optional ``tokenizer`` callback allows callers to
    plug in a precise counter when available.
"""

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from unstructured_mapping.knowledge_graph.models import (
    Entity,
)
from unstructured_mapping.pipeline.prompts import (
    build_kg_context_block,
)
from unstructured_mapping.tokens import _CHARS_PER_TOKEN

log = logging.getLogger(__name__)

#: Default response headroom in tokens.
DEFAULT_RESPONSE_HEADROOM: int = 800


def estimate_tokens(text: str) -> int:
    """Estimate the token count of a text string.

    Uses the ``ceil(char_count / 4)`` approximation from
    ``03_llm_interface.md`` § "Token counting". Slightly
    overestimates for structured text, slightly
    underestimates for non-Latin scripts — acceptable
    given the 10-20% margin built into response headroom.

    :param text: The text to estimate.
    :return: Estimated token count (always >= 0).
    """
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class PromptBudget:
    """Token budget breakdown for a single LLM call.

    Computed from the provider's context window, the
    fixed system prompt, and the configured response
    headroom. The ``flexible`` region is what remains
    for KG context + chunk text.

    :param context_window: Total model token capacity.
    :param system_tokens: Tokens used by the system
        prompt.
    :param response_headroom: Tokens reserved for the
        LLM response.
    :param flexible: Tokens available for KG context
        and chunk text. Always ``>= 0``.
    """

    context_window: int
    system_tokens: int
    response_headroom: int
    flexible: int


def compute_budget(
    context_window: int,
    system_prompt: str,
    *,
    response_headroom: int = DEFAULT_RESPONSE_HEADROOM,
    tokenizer: Callable[[str], int] | None = None,
) -> PromptBudget:
    """Compute the token budget for an LLM call.

    Subtracts the system prompt and response headroom
    from the total context window to determine the
    flexible budget available for KG context + chunk text.

    :param context_window: Total token capacity from
        :attr:`LLMProvider.context_window`.
    :param system_prompt: The system prompt text.
    :param response_headroom: Tokens to reserve for the
        model's response. Defaults to
        :data:`DEFAULT_RESPONSE_HEADROOM`.
    :param tokenizer: Optional precise token counter.
        Falls back to :func:`estimate_tokens`.
    :return: A :class:`PromptBudget` with the breakdown.
    """
    count = tokenizer or estimate_tokens
    sys_tokens = count(system_prompt)
    flexible = max(0, context_window - sys_tokens - response_headroom)
    return PromptBudget(
        context_window=context_window,
        system_tokens=sys_tokens,
        response_headroom=response_headroom,
        flexible=flexible,
    )


def _count_occurrences(text: str, substring: str) -> int:
    """Count overlapping occurrences of *substring* in *text*.

    Both arguments must already be normalised (e.g.
    lowercased) by the caller.
    """
    count = 0
    start = 0
    while True:
        pos = text.find(substring, start)
        if pos == -1:
            break
        count += 1
        start = pos + 1
    return count


def _count_alias_matches(
    entity: Entity,
    chunk_text: str,
) -> int:
    """Count how many alias matches an entity has in text.

    Uses case-insensitive substring search. This is a
    rough relevance signal for ranking — not a precise
    detection pass. The actual detection stage uses the
    trie-based scanner with word-boundary checks; this
    is intentionally simpler because it only needs to
    rank candidates for truncation, not produce exact
    mention spans.

    :param entity: The candidate entity.
    :param chunk_text: The chunk text to search.
    :return: Total number of alias occurrences.
    """
    lower_text = chunk_text.lower()
    count = 0
    for alias in entity.aliases:
        count += _count_occurrences(lower_text, alias.lower())
    count += _count_occurrences(lower_text, entity.canonical_name.lower())
    return count


def fit_candidates(
    candidates: Sequence[Entity],
    chunk_text: str,
    flexible_budget: int,
    *,
    tokenizer: Callable[[str], int] | None = None,
) -> tuple[list[Entity], str]:
    """Fit candidates and chunk text into the budget.

    Chunk text gets priority. KG context fills whatever
    remains. When the KG context is too large, candidates
    are ranked by alias match count in the chunk and the
    least-matched are dropped. When the chunk text alone
    exceeds the budget, it is truncated to leading
    paragraphs.

    :param candidates: KG entities to include as context.
    :param chunk_text: The article or chunk text.
    :param flexible_budget: Available tokens for KG
        context + chunk text (from
        :attr:`PromptBudget.flexible`).
    :param tokenizer: Optional precise token counter.
        Falls back to :func:`estimate_tokens`.
    :return: A tuple of (fitted candidates, possibly
        truncated chunk text).
    """
    count = tokenizer or estimate_tokens

    chunk_tokens = count(chunk_text)

    # -- Chunk text exceeds entire flexible budget -------
    if chunk_tokens >= flexible_budget:
        log.warning(
            "Chunk text (%d tokens) exceeds flexible "
            "budget (%d tokens) — truncating to leading "
            "paragraphs.",
            chunk_tokens,
            flexible_budget,
        )
        chunk_text = _truncate_to_paragraphs(
            chunk_text, flexible_budget, count
        )
        return [], chunk_text

    kg_budget = flexible_budget - chunk_tokens

    if not candidates:
        return [], chunk_text

    # -- All candidates fit ------------------------------
    full_block = build_kg_context_block(candidates)
    if count(full_block) <= kg_budget:
        return list(candidates), chunk_text

    # -- Rank by alias matches, keep what fits -----------
    ranked = sorted(
        candidates,
        key=lambda e: _count_alias_matches(e, chunk_text),
        reverse=True,
    )

    fitted: list[Entity] = []
    for entity in ranked:
        trial = build_kg_context_block([*fitted, entity])
        if count(trial) <= kg_budget:
            fitted.append(entity)
        else:
            break

    if len(fitted) < len(candidates):
        log.info(
            "KG context truncated: kept %d of %d "
            "candidates (budget: %d tokens).",
            len(fitted),
            len(candidates),
            kg_budget,
        )

    return fitted, chunk_text


def _truncate_to_paragraphs(
    text: str,
    max_tokens: int,
    tokenizer: Callable[[str], int],
) -> str:
    """Truncate text to leading paragraphs within budget.

    Splits on double newlines (paragraph boundaries) and
    keeps as many leading paragraphs as fit. If even the
    first paragraph exceeds the budget, it is hard-
    truncated at the character level.

    :param text: The text to truncate.
    :param max_tokens: Maximum token count.
    :param tokenizer: Token counting function.
    :return: Truncated text.
    """
    paragraphs = text.split("\n\n")
    result: list[str] = []

    for para in paragraphs:
        candidate = "\n\n".join([*result, para])
        if tokenizer(candidate) <= max_tokens:
            result.append(para)
        else:
            break

    if result:
        return "\n\n".join(result)

    # First paragraph alone exceeds budget — hard truncate.
    max_chars = max_tokens * _CHARS_PER_TOKEN
    return text[:max_chars]
