"""Tests for pipeline.budget — token budget management."""

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
)
from unstructured_mapping.pipeline.llm.budget import (
    DEFAULT_RESPONSE_HEADROOM,
    PromptBudget,
    _count_alias_matches,
    _truncate_to_paragraphs,
    compute_budget,
    estimate_tokens,
    fit_candidates,
)


# -- Fixtures ------------------------------------------------


@pytest.fixture()
def fed_entity():
    return Entity(
        entity_id="a1b2c3d4",
        canonical_name="Federal Reserve",
        entity_type=EntityType.ORGANIZATION,
        subtype="central_bank",
        description="The central banking system.",
        aliases=("the Fed", "Federal Reserve", "Fed"),
    )


@pytest.fixture()
def powell_entity():
    return Entity(
        entity_id="e5f6g7h8",
        canonical_name="Jerome Powell",
        entity_type=EntityType.PERSON,
        subtype="policymaker",
        description="Chair of the Federal Reserve.",
        aliases=("Powell", "Fed Chair Powell"),
    )


@pytest.fixture()
def cpi_entity():
    return Entity(
        entity_id="x9y8z7w6",
        canonical_name="CPI",
        entity_type=EntityType.METRIC,
        description="Consumer Price Index.",
        aliases=("CPI", "consumer price index"),
    )


# -- estimate_tokens ----------------------------------------


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_short():
    # 4 chars -> 1 token
    assert estimate_tokens("abcd") == 1


def test_estimate_tokens_rounds_up():
    # 5 chars -> ceil(5/4) = 2
    assert estimate_tokens("abcde") == 2


def test_estimate_tokens_longer():
    text = "a" * 100
    assert estimate_tokens(text) == 25


def test_estimate_tokens_one_char():
    assert estimate_tokens("x") == 1


# -- compute_budget -----------------------------------------


def test_compute_budget_basic():
    budget = compute_budget(
        context_window=4096,
        system_prompt="x" * 400,
        response_headroom=600,
    )

    assert budget.context_window == 4096
    assert budget.system_tokens == 100  # 400 chars / 4
    assert budget.response_headroom == 600
    assert budget.flexible == 4096 - 100 - 600


def test_compute_budget_default_headroom():
    budget = compute_budget(
        context_window=8192,
        system_prompt="short",
    )

    assert budget.response_headroom == DEFAULT_RESPONSE_HEADROOM


def test_compute_budget_flexible_floor_at_zero():
    budget = compute_budget(
        context_window=100,
        system_prompt="x" * 1000,
        response_headroom=600,
    )

    assert budget.flexible == 0


def test_compute_budget_custom_tokenizer():
    # Custom tokenizer that counts words
    def word_count(text: str) -> int:
        return len(text.split())

    budget = compute_budget(
        context_window=1000,
        system_prompt="one two three",
        response_headroom=100,
        tokenizer=word_count,
    )

    assert budget.system_tokens == 3
    assert budget.flexible == 1000 - 3 - 100


def test_compute_budget_returns_prompt_budget():
    budget = compute_budget(
        context_window=4096,
        system_prompt="test",
    )

    assert isinstance(budget, PromptBudget)


# -- _count_alias_matches -----------------------------------


def test_alias_matches_single(fed_entity):
    text = "the Fed raised rates"
    count = _count_alias_matches(fed_entity, text)

    # "the Fed" matches, "Fed" matches (substring of
    # "the Fed" found twice)
    assert count >= 1


def test_alias_matches_case_insensitive(fed_entity):
    text = "THE FED raised rates"
    count = _count_alias_matches(fed_entity, text)

    assert count >= 1


def test_alias_matches_canonical_name(fed_entity):
    text = "Federal Reserve raised rates"
    count = _count_alias_matches(fed_entity, text)

    # "Federal Reserve" appears as both alias and
    # canonical name
    assert count >= 1


def test_alias_matches_none():
    entity = Entity(
        entity_id="abc",
        canonical_name="Unknown Corp",
        entity_type=EntityType.ORGANIZATION,
        description="No matches.",
        aliases=("UnknownCorp",),
    )
    text = "The Fed raised rates"
    count = _count_alias_matches(entity, text)

    assert count == 0


def test_alias_matches_multiple_occurrences(
    powell_entity,
):
    text = "Powell spoke. Then Powell added."
    count = _count_alias_matches(powell_entity, text)

    # "Powell" appears twice as alias, plus canonical
    # "Jerome Powell" doesn't appear
    assert count >= 2


# -- fit_candidates -----------------------------------------


def test_fit_all_candidates(fed_entity, powell_entity):
    fitted, text = fit_candidates(
        candidates=[fed_entity, powell_entity],
        chunk_text="Short article.",
        flexible_budget=5000,
    )

    assert len(fitted) == 2
    assert text == "Short article."


def test_fit_empty_candidates():
    fitted, text = fit_candidates(
        candidates=[],
        chunk_text="Some text.",
        flexible_budget=1000,
    )

    assert fitted == []
    assert text == "Some text."


def test_fit_truncates_candidates(fed_entity, powell_entity, cpi_entity):
    chunk = "The Fed raised rates according to Powell."
    # Give a very tight budget
    fitted, text = fit_candidates(
        candidates=[fed_entity, powell_entity, cpi_entity],
        chunk_text=chunk,
        flexible_budget=estimate_tokens(chunk) + 40,
    )

    # Should keep fewer candidates than provided
    assert len(fitted) < 3
    assert text == chunk


def test_fit_ranks_by_alias_match(fed_entity, powell_entity, cpi_entity):
    chunk = "The Fed raised rates. CPI data came in."
    # Budget allows chunk + some candidates but not all
    chunk_tokens = estimate_tokens(chunk)
    # One candidate block is ~30-50 tokens
    fitted, text = fit_candidates(
        candidates=[fed_entity, powell_entity, cpi_entity],
        chunk_text=chunk,
        flexible_budget=chunk_tokens + 60,
    )

    # Fed and CPI are mentioned, Powell is not — if only
    # one fits, it should be fed_entity (most matches)
    if len(fitted) >= 1:
        ids = [e.entity_id for e in fitted]
        # Powell (no mention) should be dropped first
        assert "e5f6g7h8" not in ids or len(fitted) == 3


def test_fit_truncates_chunk_when_over_budget():
    long_text = "First paragraph.\n\n" + "x" * 4000
    fitted, text = fit_candidates(
        candidates=[],
        chunk_text=long_text,
        flexible_budget=50,
    )

    assert fitted == []
    assert len(text) < len(long_text)


def test_fit_returns_original_text_when_fits():
    text = "Short article text."
    fitted, result = fit_candidates(
        candidates=[],
        chunk_text=text,
        flexible_budget=1000,
    )

    assert result == text


def test_fit_custom_tokenizer(fed_entity):
    # Tokenizer that says everything is 1 token
    def always_one(text: str) -> int:
        return 1

    fitted, text = fit_candidates(
        candidates=[fed_entity],
        chunk_text="Article.",
        flexible_budget=10,
        tokenizer=always_one,
    )

    assert len(fitted) == 1
    assert text == "Article."


# -- _truncate_to_paragraphs --------------------------------


def test_truncate_keeps_leading_paragraphs():
    text = "Para one.\n\nPara two.\n\nPara three."
    result = _truncate_to_paragraphs(
        text, max_tokens=20, tokenizer=estimate_tokens
    )

    assert "Para one." in result
    assert "Para two." in result


def test_truncate_drops_trailing_paragraphs():
    text = "Short.\n\n" + "x" * 4000
    result = _truncate_to_paragraphs(
        text, max_tokens=10, tokenizer=estimate_tokens
    )

    assert result == "Short."


def test_truncate_hard_truncates_single_paragraph():
    text = "x" * 4000
    result = _truncate_to_paragraphs(
        text, max_tokens=10, tokenizer=estimate_tokens
    )

    # 10 tokens * 4 chars = 40 chars
    assert len(result) == 40


def test_truncate_empty_text():
    result = _truncate_to_paragraphs(
        "", max_tokens=100, tokenizer=estimate_tokens
    )

    assert result == ""


def test_truncate_fits_entirely():
    text = "Short text."
    result = _truncate_to_paragraphs(
        text, max_tokens=100, tokenizer=estimate_tokens
    )

    assert result == text
