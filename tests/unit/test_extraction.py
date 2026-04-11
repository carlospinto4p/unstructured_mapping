"""Tests for the relationship extraction module.

Covers the `RelationshipExtractor` ABC and the
`LLMRelationshipExtractor` concrete implementation.
LLM calls are mocked via a `_FakeProvider` so tests
don't require a running model.
"""

import json

import pytest

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityStatus,
    EntityType,
)
from unstructured_mapping.pipeline import (
    LLMProviderError,
    LLMRelationshipExtractor,
    RelationshipExtractor,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProvider,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
    ExtractionResult,
    ResolvedMention,
)


# -- Helpers --


class _FakeProvider(LLMProvider):
    """Minimal LLMProvider for extraction tests."""

    provider_name = "fake"
    supports_json_mode = True
    model_name = "fake-1"
    context_window = 4096

    def __init__(
        self, response: str | list[str] = "{}"
    ):
        self._responses = (
            [response]
            if isinstance(response, str)
            else list(response)
        )
        self.calls: list[
            tuple[str, str | None, bool]
        ] = []

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append((prompt, system, json_mode))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _make_chunk(
    text: str = "The Fed raised rates.",
    doc_id: str = "doc1",
) -> Chunk:
    return Chunk(
        document_id=doc_id,
        chunk_index=0,
        text=text,
    )


def _make_entity(
    entity_id: str,
    name: str,
    aliases: tuple[str, ...] = (),
) -> Entity:
    return Entity(
        entity_id=entity_id,
        canonical_name=name,
        entity_type=EntityType.ORGANIZATION,
        description=f"Test entity {name}",
        aliases=aliases,
        status=EntityStatus.ACTIVE,
    )


def _make_resolved(
    entity_id: str,
    surface_form: str,
    snippet: str = "...context...",
) -> ResolvedMention:
    return ResolvedMention(
        entity_id=entity_id,
        surface_form=surface_form,
        context_snippet=snippet,
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
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed",
            "id-powell",
            "chaired_by",
        )
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed, powell)
    names = _name_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source_id == "id-fed"
    assert rel.target_id == "id-powell"
    assert rel.relation_type == "chaired_by"


def test_extractor_name_resolution():
    """Source/target can be canonical names, not IDs."""
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "Federal Reserve",
            "Jerome Powell",
            "appointed",
        )
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed, powell)
    names = _name_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source_id == "id-fed"
    assert rel.target_id == "id-powell"


def test_extractor_self_ref_dropped():
    """Self-referential relationships are dropped."""
    fed = _make_entity("id-fed", "Federal Reserve")

    entities = (
        _make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response(
        _rel_entry("id-fed", "id-fed", "self_ref")
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed)
    names = _name_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 0


def test_extractor_empty_entities():
    """Empty entity list returns empty result."""
    provider = _FakeProvider()

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lambda _: None,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(_make_chunk(), ())

    assert result == ExtractionResult()
    assert len(provider.calls) == 0


def test_extractor_empty_relationships():
    """LLM returns no relationships."""
    fed = _make_entity("id-fed", "Federal Reserve")
    entities = (
        _make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response()
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 0


def test_extractor_calls_provider():
    """Provider is called with system prompt + json_mode."""
    fed = _make_entity("id-fed", "Federal Reserve")
    entities = (
        _make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response()
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    extractor.extract(_make_chunk(), entities)

    assert len(provider.calls) == 1
    _, system, json_mode = provider.calls[0]
    assert system is not None
    assert "relationship" in system.lower()
    assert json_mode is True


def test_extractor_with_dates():
    """Dates are parsed and included in relationships."""
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-powell", "Powell"),
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
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        _make_chunk(), entities
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
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-powell", "Powell"),
    )

    bad_response = '{"bad": "structure"}'
    good_response = _llm_response(
        _rel_entry("id-fed", "id-powell", "appointed")
    )
    provider = _FakeProvider(
        [bad_response, good_response]
    )
    lookup = _entity_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 1
    assert len(provider.calls) == 2


def test_extractor_retry_prompt_contains_error():
    """Retry prompt includes the validation error."""
    fed = _make_entity("id-fed", "Federal Reserve")
    entities = (
        _make_resolved("id-fed", "the Fed"),
    )

    bad_response = '{"bad": "structure"}'
    good_response = _llm_response()
    provider = _FakeProvider(
        [bad_response, good_response]
    )
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    extractor.extract(_make_chunk(), entities)

    retry_prompt = provider.calls[1][0]
    assert "previous response" in retry_prompt
    assert "relationships" in retry_prompt


def test_extractor_raises_after_two_failures():
    """Raises LLMProviderError after 2 validation fails."""
    fed = _make_entity("id-fed", "Federal Reserve")
    entities = (
        _make_resolved("id-fed", "the Fed"),
    )

    bad_response = '{"bad": "structure"}'
    provider = _FakeProvider(bad_response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )

    with pytest.raises(LLMProviderError, match="Pass 2"):
        extractor.extract(_make_chunk(), entities)

    assert len(provider.calls) == 2


# -- LLMRelationshipExtractor: proposals --


def test_extractor_with_proposals():
    """Proposals from pass 1 are available for reference."""
    fed = _make_entity("id-fed", "Federal Reserve")
    cpi = _make_entity("id-cpi", "CPI")

    entities = (
        _make_resolved("id-fed", "the Fed"),
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
    provider = _FakeProvider(response)
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
        _make_chunk(), entities
    )

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source_id == "id-fed"
    assert rel.target_id == "id-cpi"


def test_extractor_unresolvable_ref_dropped():
    """Unresolvable entity references are dropped."""
    fed = _make_entity("id-fed", "Federal Reserve")
    entities = (
        _make_resolved("id-fed", "the Fed"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed",
            "nonexistent-id",
            "related_to",
        )
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 0


def test_extractor_multiple_relationships():
    """Multiple relationships are extracted."""
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")
    rates = _make_entity("id-rates", "Interest Rates")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-powell", "Powell"),
        _make_resolved("id-rates", "rates"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed", "id-rates", "raised"
        ),
        _rel_entry(
            "id-powell", "id-fed", "chairs"
        ),
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed, powell, rates)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 2
    types = {
        r.relation_type for r in result.relationships
    }
    assert types == {"raised", "chairs"}


def test_extractor_deduplicates_entity_ids():
    """Duplicate entity IDs in resolved list are handled."""
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-fed", "Federal Reserve"),
        _make_resolved("id-powell", "Powell"),
    )

    response = _llm_response(
        _rel_entry(
            "id-fed", "id-powell", "appointed"
        )
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed, powell)
    names = _name_lookup(fed, powell)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=names.get,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 1


def test_extractor_qualifier_resolved():
    """Qualifier entity reference is resolved to ID."""
    fed = _make_entity("id-fed", "Federal Reserve")
    powell = _make_entity("id-powell", "Jerome Powell")
    chair = _make_entity("id-chair", "Chair")

    entities = (
        _make_resolved("id-fed", "the Fed"),
        _make_resolved("id-powell", "Powell"),
        _make_resolved("id-chair", "Chair"),
    )

    response = _llm_response(
        _rel_entry(
            "id-powell",
            "id-fed",
            "holds_role",
            qualifier="id-chair",
        )
    )
    provider = _FakeProvider(response)
    lookup = _entity_lookup(fed, powell, chair)

    extractor = LLMRelationshipExtractor(
        provider=provider,
        entity_lookup=lookup.get,
        name_lookup=lambda _: None,
    )
    result = extractor.extract(
        _make_chunk(), entities
    )

    assert len(result.relationships) == 1
    assert (
        result.relationships[0].qualifier_id
        == "id-chair"
    )
