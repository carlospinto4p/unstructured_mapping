"""Tests for the cross-chunk aggregator."""

from unstructured_mapping.knowledge_graph.models import (
    EntityType,
    Provenance,
)
from unstructured_mapping.pipeline.aggregation import (
    ChunkAggregator,
    ChunkOutcome,
)
from unstructured_mapping.pipeline.models import (
    EntityProposal,
    ExtractedRelationship,
    ResolutionResult,
    ResolvedMention,
)


def _resolved(entity_id: str, text: str) -> ResolvedMention:
    return ResolvedMention(
        entity_id=entity_id,
        surface_form=text,
        context_snippet=text,
    )


def _proposal(
    name: str,
    description: str = "",
    entity_type: EntityType = EntityType.ORGANIZATION,
) -> EntityProposal:
    return EntityProposal(
        canonical_name=name,
        entity_type=entity_type,
        description=description or f"{name} description.",
    )


def _rel(
    src: str,
    tgt: str,
    relation_type: str = "acquired",
    context: str = "",
) -> ExtractedRelationship:
    return ExtractedRelationship(
        source_id=src,
        target_id=tgt,
        relation_type=relation_type,
        context_snippet=context or f"{src} {relation_type} {tgt}",
    )


def _prov(entity_id: str, mention: str) -> Provenance:
    return Provenance(
        entity_id=entity_id,
        document_id="doc1",
        source="test",
        mention_text=mention,
        context_snippet=mention,
    )


# -- Resolution + provenance concatenation ----------------------


def test_aggregator_concatenates_resolutions():
    a = ChunkOutcome(
        resolution=ResolutionResult(
            resolved=(_resolved("e1", "Apple"),),
        ),
    )
    b = ChunkOutcome(
        resolution=ResolutionResult(
            resolved=(_resolved("e2", "MSFT"),),
        ),
    )
    result = ChunkAggregator().aggregate([a, b])
    assert len(result.resolution.resolved) == 2
    assert {
        r.entity_id for r in result.resolution.resolved
    } == {"e1", "e2"}


def test_aggregator_passes_provenance_through():
    # Provenance PK (entity_id, document_id, mention_text)
    # handles dedup in SQLite; the aggregator just
    # concatenates so every chunk detection survives.
    a = ChunkOutcome(
        provenances=(
            _prov("e1", "Apple"),
            _prov("e1", "the company"),
        ),
    )
    b = ChunkOutcome(
        provenances=(_prov("e1", "Apple"),),
    )
    result = ChunkAggregator().aggregate([a, b])
    assert len(result.provenances) == 3


# -- Proposal dedup + conflict flagging -------------------------


def test_aggregator_dedupes_proposals_by_name_and_type():
    a = ChunkOutcome(
        proposals=(
            _proposal("NewCo", description="short"),
        ),
    )
    b = ChunkOutcome(
        proposals=(
            _proposal(
                "NewCo",
                description="much longer description",
            ),
        ),
    )
    result = ChunkAggregator().aggregate([a, b])
    assert len(result.proposals) == 1
    assert (
        result.proposals[0].description
        == "much longer description"
    )
    assert result.conflicts == ()


def test_aggregator_proposal_dedup_is_case_insensitive():
    a = ChunkOutcome(
        proposals=(_proposal("newco"),),
    )
    b = ChunkOutcome(
        proposals=(_proposal("NEWCO"),),
    )
    result = ChunkAggregator().aggregate([a, b])
    assert len(result.proposals) == 1


def test_aggregator_flags_type_conflict_and_drops_both():
    a = ChunkOutcome(
        proposals=(
            _proposal(
                "NewCo",
                entity_type=EntityType.ORGANIZATION,
            ),
        ),
    )
    b = ChunkOutcome(
        proposals=(
            _proposal(
                "NewCo", entity_type=EntityType.ASSET
            ),
        ),
    )
    result = ChunkAggregator().aggregate([a, b])
    # Neither survives — the aggregator refuses to pick a
    # winner when the types disagree.
    assert result.proposals == ()
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.canonical_name == "NewCo"
    assert set(conflict.entity_types) == {
        EntityType.ORGANIZATION,
        EntityType.ASSET,
    }


def test_aggregator_keeps_same_name_different_types_when_separate():
    # Subtle: if type-sets is len==1 for a name, no
    # conflict. Two chunks each propose "NewCo" as
    # ORGANIZATION → deduped, survives.
    a = ChunkOutcome(
        proposals=(_proposal("NewCo"),),
    )
    b = ChunkOutcome(
        proposals=(_proposal("NewCo"),),
    )
    result = ChunkAggregator().aggregate([a, b])
    assert len(result.proposals) == 1
    assert result.conflicts == ()


# -- Relationship dedup -----------------------------------------


def test_aggregator_dedupes_relationships():
    a = ChunkOutcome(
        relationships=(
            _rel("e1", "e2", context="short"),
        ),
    )
    b = ChunkOutcome(
        relationships=(
            _rel(
                "e1",
                "e2",
                context="longer evidence snippet",
            ),
        ),
    )
    result = ChunkAggregator().aggregate([a, b])
    assert len(result.relationships) == 1
    assert (
        result.relationships[0].context_snippet
        == "longer evidence snippet"
    )


def test_aggregator_keeps_different_relation_types():
    a = ChunkOutcome(
        relationships=(
            _rel("e1", "e2", relation_type="acquired"),
        ),
    )
    b = ChunkOutcome(
        relationships=(
            _rel(
                "e1",
                "e2",
                relation_type="competes_with",
            ),
        ),
    )
    result = ChunkAggregator().aggregate([a, b])
    # Same pair + different facet = two rows.
    assert len(result.relationships) == 2


# -- Degenerate cases -------------------------------------------


def test_aggregator_handles_empty_input():
    result = ChunkAggregator().aggregate([])
    assert result.resolution.resolved == ()
    assert result.provenances == ()
    assert result.proposals == ()
    assert result.relationships == ()
    assert result.conflicts == ()


def test_aggregator_single_outcome_passes_through():
    outcome = ChunkOutcome(
        resolution=ResolutionResult(
            resolved=(_resolved("e1", "Apple"),),
        ),
        provenances=(_prov("e1", "Apple"),),
        proposals=(_proposal("NewCo"),),
        relationships=(_rel("e1", "e2"),),
    )
    result = ChunkAggregator().aggregate([outcome])
    assert result.resolution.resolved[0].entity_id == "e1"
    assert len(result.provenances) == 1
    assert len(result.proposals) == 1
    assert len(result.relationships) == 1
    assert result.conflicts == ()
