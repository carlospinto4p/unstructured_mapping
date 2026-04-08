"""Tests for knowledge_graph data models and enums."""

import pytest

from unstructured_mapping.knowledge_graph import (
    EntityStatus,
    EntityType,
    IngestionRun,
    Provenance,
    Relationship,
    RunStatus,
)

from .conftest import _make_entity


# -- EntityType enum --


def test_entity_type_values():
    assert EntityType.PERSON == "person"
    assert EntityType.ORGANIZATION == "organization"
    assert EntityType.PLACE == "place"
    assert EntityType.TOPIC == "topic"
    assert EntityType.PRODUCT == "product"
    assert EntityType.LEGISLATION == "legislation"
    assert EntityType.ASSET == "asset"
    assert EntityType.METRIC == "metric"
    assert EntityType.ROLE == "role"
    assert EntityType.RELATION_KIND == "relation_kind"


def test_entity_type_from_string():
    assert EntityType("person") is EntityType.PERSON


# -- EntityStatus enum --


def test_entity_status_values():
    assert EntityStatus.ACTIVE == "active"
    assert EntityStatus.MERGED == "merged"
    assert EntityStatus.DEPRECATED == "deprecated"


# -- Entity model --


def test_entity_auto_id():
    e1 = _make_entity()
    e2 = _make_entity()
    assert len(e1.entity_id) == 32
    assert e1.entity_id != e2.entity_id


def test_entity_defaults():
    e = _make_entity()
    assert e.aliases == ()
    assert e.subtype is None
    assert e.status == EntityStatus.ACTIVE
    assert e.merged_into is None
    assert e.valid_from is None
    assert e.valid_until is None


def test_entity_with_subtype():
    e = _make_entity(
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
    )
    assert e.subtype == "company"


def test_entity_is_frozen():
    e = _make_entity()
    with pytest.raises(AttributeError):
        e.canonical_name = "X"  # type: ignore[misc]


def test_entity_with_aliases():
    e = _make_entity(aliases=("Alias A", "Alias B"))
    assert e.aliases == ("Alias A", "Alias B")


# -- Provenance model --


def test_provenance_fields():
    p = Provenance(
        entity_id="abc",
        document_id="doc1",
        source="bbc",
        mention_text="Test",
        context_snippet="...Test mentioned here...",
    )
    assert p.entity_id == "abc"
    assert p.document_id == "doc1"
    assert p.detected_at is None


# -- Relationship model --


def test_relationship_fields():
    r = Relationship(
        source_id="e1",
        target_id="e2",
        relation_type="acquired",
        description="E1 acquired E2 in 2024.",
    )
    assert r.source_id == "e1"
    assert r.relation_type == "acquired"
    assert r.valid_from is None
    assert r.document_id is None


def test_relationship_qualifier_defaults():
    r = Relationship(
        source_id="e1",
        target_id="e2",
        relation_type="works_at",
        description="E1 works at E2.",
    )
    assert r.qualifier_id is None
    assert r.relation_kind_id is None


def test_relationship_with_qualifier():
    r = Relationship(
        source_id="e1",
        target_id="e2",
        relation_type="works_at",
        description="E1 is CTO at E2.",
        qualifier_id="role_cto",
        relation_kind_id="kind_employment",
    )
    assert r.qualifier_id == "role_cto"
    assert r.relation_kind_id == "kind_employment"


# -- IngestionRun model --


def test_ingestion_run_defaults():
    run = IngestionRun()
    assert run.status == RunStatus.RUNNING
    assert run.run_id
    assert run.started_at is not None
    assert run.finished_at is None
    assert run.document_count == 0
    assert run.entity_count == 0
    assert run.relationship_count == 0
    assert run.error_message is None


def test_run_status_values():
    assert RunStatus.RUNNING == "running"
    assert RunStatus.COMPLETED == "completed"
    assert RunStatus.FAILED == "failed"
