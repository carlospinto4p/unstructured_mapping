"""Tests for the relationship extraction module.

Covers the `RelationshipExtractor` ABC and the
`LLMRelationshipExtractor` concrete implementation.
LLM calls are mocked via a `FakeProvider` so tests
don't require a running model.
"""

import json

import pytest

from tests.unit.conftest import (
    FakeProvider,
    make_chunk,
    make_org,
    make_resolved,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityType,
)
from unstructured_mapping.pipeline import (
    LLMProviderError,
    LLMRelationshipExtractor,
    RelationshipExtractor,
)
from unstructured_mapping.pipeline.models import (
    EntityProposal,
    ExtractionResult,
)


def _rel_entry(
    source: str,
    target: str,
    relation_type: str = "related_to",
    snippet: str = "...the Fed raised rates...",
    **kwargs: object,
) -> dict:
    entry: dict = {
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "context_snippet": snippet,
    }
    entry.update(kwargs)
    return entry


def _llm_response(
    *relationships: dict,
) -> str:
    return json.dumps(
        {"relationships": list(relationships)}
    )


def _entity_lookup(
    *entities: Entity,
) -> dict[str, Entity]:
    return {e.entity_id: e for e in entities}


def _name_lookup(
    *entities: Entity,
) -> dict[str, Entity]:
    return {e.canonical_name: e for e in entities}


# -- ABC contract --


def test_relationship_extractor_is_abstract():
    """RelationshipExtractor cannot be instantiated."""
    with pytest.raises(TypeError):
        RelationshipExtractor()  # type: ignore[abstract]


# -- LLMRelationshipExtractor: happy path --


def test_extractor_happy_path():
    """Extracts relationships between resolved entities."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed",
            "id-powell",
            "chaired_by",
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed, powell)
    names = _name_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source_id == "id-fed"
    assert rel.target_id == "id-powell"
    assert rel.relation_type == "chaired_by"


def test_extractor_name_resolution():
    """Source/target can be canonical names, not IDs."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "Federal Reserve",
            "Jerome Powell",
            "appointed",
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed, powell)
    names = _name_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source_id == "id-fed"
    assert rel.target_id == "id-powell"


def test_extractor_self_ref_dropped():
    """Self-referential relationships are dropped."""
    fed = make_org("Federal Reserve", entity_id="id-fed")

    entities = (
        make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response(
        _rel_entry("id-fed", "id-fed", "self_ref")
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed)
    names = _name_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 0


def test_extractor_empty_entities():
    """Empty entity list returns empty result."""
    provider = FakeProvider()

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lambda _: None,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(make_chunk(), ())

    assert result == ExtractionResult()
    assert len(provider.calls) == 0


def test_extractor_empty_relationships():
    """LLM returns no relationships."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    entities = (
        make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response()
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 0


def test_extractor_calls_provider():
    """Provider is called with system prompt + json_mode."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    entities = (
        make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response()
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    extractor.extract(make_chunk(), entities)

    assert len(provider.calls) == 1
    _, system, json_mode = provider.calls[0]
    assert system is not None
    assert "relationship" in system.lower()
    assert json_mode is True


def test_extractor_with_dates():
    """Dates are parsed and included in relationships."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed",
            "id-powell",
            "appointed",
            valid_from="2018-02-05",
            valid_until=None,
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.valid_from is not None
    assert rel.valid_from.year == 2018
    assert rel.valid_from.month == 2
    assert rel.valid_from.day == 5
    assert rel.valid_until is None


# -- LLMRelationshipExtractor: retry logic --


def test_extractor_retry_on_validation_failure():
    """Retries once on structural validation failure."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-powell", "Powell"),
    )

    bad_response = '{"bad": "structure"}'
    good_response = _llm_response(
        _rel_entry("id-fed", "id-powell", "appointed")
    )
    provider = FakeProvider(
        [bad_response, good_response]
    )
    lookup = _entity_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1
    assert len(provider.calls) == 2


def test_extractor_retry_prompt_contains_error():
    """Retry prompt includes the validation error."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    entities = (
        make_resolved("id-fed", "the Fed"),
    )

    bad_response = '{"bad": "structure"}'
    good_response = _llm_response()
    provider = FakeProvider(
        [bad_response, good_response]
    )
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    extractor.extract(make_chunk(), entities)

    retry_prompt = provider.calls[1][0]
    assert "previous response" in retry_prompt
    assert "relationships" in retry_prompt


def test_extractor_raises_after_two_failures():
    """Raises LLMProviderError after 2 validation fails."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    entities = (
        make_resolved("id-fed", "the Fed"),
    )

    bad_response = '{"bad": "structure"}'
    provider = FakeProvider(bad_response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )

    with pytest.raises(LLMProviderError, match="Pass 2"):
        extractor.extract(make_chunk(), entities)

    assert len(provider.calls) == 2


# -- LLMRelationshipExtractor: proposals --


def test_extractor_with_proposals():
    """Proposals from pass 1 are available for reference."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    cpi = make_org("CPI", entity_id="id-cpi")

    entities = (
        make_resolved("id-fed", "the Fed"),
    )
    proposals = [
        EntityProposal(
            canonical_name="CPI",
            entity_type=EntityType.METRIC,
            description="Consumer Price Index",
        ),
    ]

    response = _llm_response(
        _rel_entry(
            "id-fed",
            "CPI",
            "publishes",
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda name: cpi
        if name == "CPI"
        else None,
        proposals=proposals,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source_id == "id-fed"
    assert rel.target_id == "id-cpi"


def test_extractor_unresolvable_ref_dropped():
    """Unresolvable entity references are dropped."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    entities = (
        make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed",
            "nonexistent-id",
            "related_to",
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 0


def test_extractor_multiple_relationships():
    """Multiple relationships are extracted."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")
    rates = make_org("Interest Rates", entity_id="id-rates")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-powell", "Powell"),
        make_resolved("id-rates", "rates"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed", "id-rates", "raised"
        ),
        _rel_entry(
            "id-powell", "id-fed", "chairs"
        ),
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed, powell, rates)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 2
    types = {
        r.relation_type for r in result.relationships
    }
    assert types == {"raised", "chairs"}


def test_extractor_deduplicates_entity_ids():
    """Duplicate entity IDs in resolved list are handled."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-fed", "Federal Reserve"),
        make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed", "id-powell", "appointed"
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed, powell)
    names = _name_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1


def test_extractor_qualifier_resolved():
    """Qualifier entity reference is resolved to ID."""
    fed = make_org("Federal Reserve", entity_id="id-fed")
    powell = make_org("Jerome Powell", entity_id="id-powell")
    chair = make_org("Chair", entity_id="id-chair")

    entities = (
        make_resolved("id-fed", "the Fed"),
        make_resolved("id-powell", "Powell"),
        make_resolved("id-chair", "Chair"),
    )

    response = _llm_response(
        _rel_entry(
            "id-powell",
            "id-fed",
            "holds_role",
            qualifier="id-chair",
        )
    )
    provider = FakeProvider(response)
    lookup = _entity_lookup(fed, powell, chair)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        make_chunk(), entities
    )

    assert len(result.relationships) == 1
    assert (
        result.relationships[0].qualifier_id
        == "id-chair"
    )
