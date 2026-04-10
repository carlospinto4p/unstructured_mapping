"""Tests for pipeline.prompts — prompt construction."""

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
)
from unstructured_mapping.pipeline.models import (
    ResolvedMention,
)
from unstructured_mapping.pipeline.prompts import (
    PASS1_SYSTEM_PROMPT,
    build_kg_context_block,
    build_pass1_user_prompt,
    _build_running_entity_header,
)


# -- Fixtures ------------------------------------------------


@pytest.fixture()
def fed_entity():
    return Entity(
        entity_id="a1b2c3d4",
        canonical_name="Federal Reserve",
        entity_type=EntityType.ORGANIZATION,
        subtype="central_bank",
        description=(
            "The central banking system of the "
            "United States."
        ),
        aliases=("the Fed", "Federal Reserve", "Fed"),
    )


@pytest.fixture()
def powell_entity():
    return Entity(
        entity_id="e5f6g7h8",
        canonical_name="Jerome Powell",
        entity_type=EntityType.PERSON,
        subtype="policymaker",
        description=(
            "Chair of the Federal Reserve since 2018."
        ),
        aliases=("Powell", "Fed Chair Powell"),
    )


@pytest.fixture()
def no_subtype_entity():
    return Entity(
        entity_id="x9y8z7w6",
        canonical_name="CPI",
        entity_type=EntityType.METRIC,
        description="Consumer Price Index.",
    )


@pytest.fixture()
def fed_resolved():
    return ResolvedMention(
        entity_id="a1b2c3d4",
        surface_form="the Fed",
        context_snippet="...the Fed raised rates...",
    )


@pytest.fixture()
def powell_resolved():
    return ResolvedMention(
        entity_id="e5f6g7h8",
        surface_form="Jerome Powell",
        context_snippet="...Fed Chair Powell announced...",
    )


# -- PASS1_SYSTEM_PROMPT ------------------------------------


def test_system_prompt_is_nonempty_string():
    assert isinstance(PASS1_SYSTEM_PROMPT, str)
    assert len(PASS1_SYSTEM_PROMPT) > 100


def test_system_prompt_mentions_json():
    assert "JSON" in PASS1_SYSTEM_PROMPT


def test_system_prompt_lists_entity_types():
    for et in EntityType:
        assert et.value in PASS1_SYSTEM_PROMPT


def test_system_prompt_mentions_entity_id():
    assert "entity_id" in PASS1_SYSTEM_PROMPT


def test_system_prompt_mentions_new_entity():
    assert "new_entity" in PASS1_SYSTEM_PROMPT


# -- build_kg_context_block ---------------------------------


def test_kg_block_empty_candidates():
    assert build_kg_context_block([]) == ""


def test_kg_block_single_candidate(fed_entity):
    block = build_kg_context_block([fed_entity])

    assert block.startswith("CANDIDATE ENTITIES:")
    assert "[1] entity_id=a1b2c3d4" in block
    assert "name: Federal Reserve" in block
    assert "type: organization / central_bank" in block
    assert "aliases: the Fed, Federal Reserve, Fed" in block
    assert "description: The central banking" in block


def test_kg_block_multiple_candidates(
    fed_entity, powell_entity
):
    block = build_kg_context_block(
        [fed_entity, powell_entity]
    )

    assert "[1] entity_id=a1b2c3d4" in block
    assert "[2] entity_id=e5f6g7h8" in block
    assert "name: Federal Reserve" in block
    assert "name: Jerome Powell" in block


def test_kg_block_numbering_sequential(
    fed_entity, powell_entity, no_subtype_entity
):
    block = build_kg_context_block(
        [fed_entity, powell_entity, no_subtype_entity]
    )

    assert "[1]" in block
    assert "[2]" in block
    assert "[3]" in block


def test_kg_block_no_subtype(no_subtype_entity):
    block = build_kg_context_block([no_subtype_entity])

    assert "type: metric" in block
    assert "/" not in block.split("type: metric")[1].split(
        "\n"
    )[0]


def test_kg_block_no_aliases():
    entity = Entity(
        entity_id="abc123",
        canonical_name="Test",
        entity_type=EntityType.TOPIC,
        description="A test topic.",
        aliases=(),
    )
    block = build_kg_context_block([entity])

    assert "aliases:" not in block


# -- _build_running_entity_header ---------------------------


def test_header_empty():
    assert _build_running_entity_header([]) == ""


def test_header_single(fed_resolved):
    header = _build_running_entity_header([fed_resolved])

    assert header.startswith("PREVIOUSLY RESOLVED")
    assert "- the Fed (id=a1b2c3d4)" in header


def test_header_multiple(fed_resolved, powell_resolved):
    header = _build_running_entity_header(
        [fed_resolved, powell_resolved]
    )

    assert "- the Fed (id=a1b2c3d4)" in header
    assert "- Jerome Powell (id=e5f6g7h8)" in header


def test_header_deduplicates(fed_resolved):
    dup = ResolvedMention(
        entity_id="a1b2c3d4",
        surface_form="Federal Reserve",
        context_snippet="...Federal Reserve...",
    )
    header = _build_running_entity_header(
        [fed_resolved, dup]
    )

    lines = [
        line
        for line in header.splitlines()
        if line.startswith("- ")
    ]
    assert len(lines) == 1


# -- build_pass1_user_prompt --------------------------------


def test_user_prompt_text_only():
    prompt = build_pass1_user_prompt(
        kg_block="", chunk_text="Some article text."
    )

    assert "TEXT:\nSome article text." in prompt
    assert "CANDIDATE" not in prompt
    assert "PREVIOUSLY" not in prompt


def test_user_prompt_with_kg_block(fed_entity):
    block = build_kg_context_block([fed_entity])
    prompt = build_pass1_user_prompt(
        kg_block=block, chunk_text="Article body."
    )

    assert "CANDIDATE ENTITIES:" in prompt
    assert "TEXT:\nArticle body." in prompt


def test_user_prompt_with_prev_entities(fed_resolved):
    prompt = build_pass1_user_prompt(
        kg_block="",
        chunk_text="Second chunk.",
        prev_entities=[fed_resolved],
    )

    assert "PREVIOUSLY RESOLVED" in prompt
    assert "TEXT:\nSecond chunk." in prompt


def test_user_prompt_all_sections(
    fed_entity, fed_resolved
):
    block = build_kg_context_block([fed_entity])
    prompt = build_pass1_user_prompt(
        kg_block=block,
        chunk_text="Full prompt.",
        prev_entities=[fed_resolved],
    )

    parts = prompt.split("\n\n")
    # At least 3 sections: KG block, header, text
    assert len(parts) >= 3

    # KG block comes first
    assert parts[0].startswith("CANDIDATE ENTITIES:")

    # Text comes last
    assert parts[-1].startswith("TEXT:")


def test_user_prompt_sections_separated_by_blank_lines(
    fed_entity, fed_resolved
):
    block = build_kg_context_block([fed_entity])
    prompt = build_pass1_user_prompt(
        kg_block=block,
        chunk_text="Test.",
        prev_entities=[fed_resolved],
    )

    # Double newline separates the major sections
    assert "\n\n" in prompt
