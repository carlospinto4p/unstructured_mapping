"""Tests for KnowledgeStore relationship operations."""

from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
    Relationship,
)

from .conftest import _make_entity


# -- KnowledgeStore: relationship CRUD --


def test_store_save_and_get_relationships(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Entity A")
    e2 = _make_entity(canonical_name="Entity B")
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="acquired",
        description="A acquired B.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(rel)
        from_source = store.get_relationships(
            e1.entity_id, as_target=False
        )
        from_target = store.get_relationships(
            e2.entity_id, as_source=False
        )

    assert len(from_source) == 1
    assert from_source[0].relation_type == "acquired"
    assert len(from_target) == 1
    assert from_target[0].source_id == e1.entity_id


# -- KnowledgeStore: NULL valid_from dedup --


def test_relationship_null_valid_from_dedup(tmp_path):
    """Duplicate unbounded relationships are rejected."""
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Entity A")
    e2 = _make_entity(canonical_name="Entity B")
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="supplies",
        description="A supplies B.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(rel)
        store.save_relationship(rel)  # duplicate
        rels = store.get_relationships(
            e1.entity_id, as_target=False
        )

    assert len(rels) == 1


def test_relationship_null_valid_from_round_trip(
    tmp_path,
):
    """valid_from=None survives save/load round trip."""
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Entity A")
    e2 = _make_entity(canonical_name="Entity B")
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="supplies",
        description="A supplies B.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(rel)
        loaded = store.get_relationships(
            e1.entity_id, as_target=False
        )

    assert loaded[0].valid_from is None


# -- KnowledgeStore: get_relationships_between --


def test_get_relationships_between(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Apple")
    e2 = _make_entity(canonical_name="Foxconn")
    e3 = _make_entity(canonical_name="TSMC")
    rel1 = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="supplies",
        description="Foxconn supplies Apple.",
    )
    rel2 = Relationship(
        source_id=e1.entity_id,
        target_id=e3.entity_id,
        relation_type="supplies",
        description="TSMC supplies Apple.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        store.save_relationship(rel1)
        store.save_relationship(rel2)
        between = store.get_relationships_between(
            e1.entity_id, e2.entity_id
        )
        reverse = store.get_relationships_between(
            e2.entity_id, e1.entity_id
        )
        none = store.get_relationships_between(
            e2.entity_id, e3.entity_id
        )

    assert len(between) == 1
    assert between[0].target_id == e2.entity_id
    assert reverse == []
    assert none == []


# -- KnowledgeStore: find_relationships_by_type --


def test_find_relationships_by_type(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Entity A")
    e2 = _make_entity(canonical_name="Entity B")
    e3 = _make_entity(canonical_name="Entity C")
    rel_acq = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="acquired",
        description="A acquired B.",
    )
    rel_comp = Relationship(
        source_id=e1.entity_id,
        target_id=e3.entity_id,
        relation_type="competes_with",
        description="A competes with C.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        store.save_relationship(rel_acq)
        store.save_relationship(rel_comp)
        found = store.find_relationships_by_type(
            "acquired"
        )
        none = store.find_relationships_by_type(
            "nonexistent"
        )

    assert len(found) == 1
    assert found[0].relation_type == "acquired"
    assert found[0].source_id == e1.entity_id
    assert found[0].target_id == e2.entity_id
    assert none == []


# -- KnowledgeStore: find_active_relationships --


def test_find_active_relationships(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Company A")
    e2 = _make_entity(canonical_name="Company B")
    e3 = _make_entity(canonical_name="Person X")
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    future = datetime(2099, 12, 31, tzinfo=timezone.utc)
    rel_active = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="supplies",
        description="A supplies B.",
    )
    rel_ended = Relationship(
        source_id=e3.entity_id,
        target_id=e1.entity_id,
        relation_type="works_at",
        description="X worked at A.",
        valid_from=past,
        valid_until=past,
    )
    rel_future = Relationship(
        source_id=e3.entity_id,
        target_id=e2.entity_id,
        relation_type="works_at",
        description="X works at B.",
        valid_from=past,
        valid_until=future,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        store.save_relationship(rel_active)
        store.save_relationship(rel_ended)
        store.save_relationship(rel_future)
        active = store.find_active_relationships(
            e3.entity_id
        )
        active_src = store.find_active_relationships(
            e3.entity_id, as_target=False
        )
        active_tgt = store.find_active_relationships(
            e3.entity_id, as_source=False
        )

    types = {r.relation_type for r in active}
    assert len(active) == 1
    assert active[0].target_id == e2.entity_id
    assert "works_at" in types
    assert len(active_src) == 1
    assert active_tgt == []


def test_find_active_relationships_unbounded(tmp_path):
    """Relationships with no valid_until are active."""
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="A")
    e2 = _make_entity(canonical_name="B")
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="competes_with",
        description="A competes with B.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(rel)
        active = store.find_active_relationships(
            e1.entity_id
        )

    assert len(active) == 1
    assert active[0].relation_type == "competes_with"


# -- KnowledgeStore: find_by_qualifier --


def test_store_find_by_qualifier(tmp_path):
    db = tmp_path / "kg.db"
    person = _make_entity(canonical_name="Jane Doe")
    company = _make_entity(
        canonical_name="Acme Corp",
        entity_type=EntityType.ORGANIZATION,
        description="A tech company.",
    )
    cto = Entity(
        canonical_name="Chief Technology Officer",
        entity_type=EntityType.ROLE,
        description="Senior tech executive.",
        aliases=("CTO",),
    )
    rel = Relationship(
        source_id=person.entity_id,
        target_id=company.entity_id,
        relation_type="works_at",
        description="Jane is CTO at Acme.",
        qualifier_id=cto.entity_id,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(person)
        store.save_entity(company)
        store.save_entity(cto)
        store.save_relationship(rel)
        results = store.find_by_qualifier(
            cto.entity_id
        )

    assert len(results) == 1
    assert results[0].source_id == person.entity_id
    assert results[0].qualifier_id == cto.entity_id


# -- KnowledgeStore: find_by_relation_kind --


def test_store_find_by_relation_kind(tmp_path):
    db = tmp_path / "kg.db"
    person = _make_entity(canonical_name="John")
    company = _make_entity(
        canonical_name="Beta Inc",
        entity_type=EntityType.ORGANIZATION,
        description="A company.",
    )
    kind = Entity(
        canonical_name="employment",
        entity_type=EntityType.RELATION_KIND,
        description="Employment relationship.",
        aliases=("works_at", "employed_by"),
    )
    rel = Relationship(
        source_id=person.entity_id,
        target_id=company.entity_id,
        relation_type="employed_by",
        description="John works at Beta.",
        relation_kind_id=kind.entity_id,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(person)
        store.save_entity(company)
        store.save_entity(kind)
        store.save_relationship(rel)
        results = store.find_by_relation_kind(
            kind.entity_id
        )

    assert len(results) == 1
    assert results[0].relation_kind_id == (
        kind.entity_id
    )


# -- KnowledgeStore: qualifier round-trip --


def test_store_relationship_qualifier_round_trip(
    tmp_path,
):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="A")
    e2 = _make_entity(
        canonical_name="B",
        entity_type=EntityType.ORGANIZATION,
        description="Org B.",
    )
    role = Entity(
        canonical_name="CEO",
        entity_type=EntityType.ROLE,
        description="Chief Executive Officer.",
    )
    kind = Entity(
        canonical_name="employment",
        entity_type=EntityType.RELATION_KIND,
        description="Employment.",
    )
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="works_at",
        description="A is CEO at B.",
        qualifier_id=role.entity_id,
        relation_kind_id=kind.entity_id,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(role)
        store.save_entity(kind)
        store.save_relationship(rel)
        loaded = store.get_relationships(
            e1.entity_id, as_target=False
        )

    assert len(loaded) == 1
    assert loaded[0].qualifier_id == role.entity_id
    assert loaded[0].relation_kind_id == kind.entity_id


# -- KnowledgeStore: merge updates qualifier refs --


def test_store_merge_updates_qualifier(tmp_path):
    db = tmp_path / "kg.db"
    person = _make_entity(canonical_name="X")
    company = _make_entity(
        canonical_name="Y",
        entity_type=EntityType.ORGANIZATION,
        description="Org.",
    )
    old_role = Entity(
        canonical_name="Chief Tech Officer",
        entity_type=EntityType.ROLE,
        description="Same as CTO.",
    )
    new_role = Entity(
        canonical_name="CTO",
        entity_type=EntityType.ROLE,
        description="Chief Technology Officer.",
    )
    rel = Relationship(
        source_id=person.entity_id,
        target_id=company.entity_id,
        relation_type="works_at",
        description="X is CTO at Y.",
        qualifier_id=old_role.entity_id,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(person)
        store.save_entity(company)
        store.save_entity(old_role)
        store.save_entity(new_role)
        store.save_relationship(rel)
        store.merge_entities(
            old_role.entity_id, new_role.entity_id
        )
        rels = store.get_relationships(
            person.entity_id, as_target=False
        )

    assert len(rels) == 1
    assert rels[0].qualifier_id == new_role.entity_id


# -- Audit log: relationship history --


def test_relationship_create_logs_history(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="A")
    e2 = _make_entity(
        canonical_name="B",
        entity_type=EntityType.ORGANIZATION,
        description="Org B.",
    )
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="works_at",
        description="A works at B.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(rel)
        history = store.get_relationship_history(
            e1.entity_id
        )

    assert len(history) == 1
    assert history[0].operation == "create"
    assert history[0].relation_type == "works_at"


def test_relationship_save_reason(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="X")
    e2 = _make_entity(
        canonical_name="Y",
        entity_type=EntityType.ORGANIZATION,
        description="Org.",
    )
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="joined",
        description="X joined Y.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(
            rel, reason="extracted from article"
        )
        history = store.get_relationship_history(
            e1.entity_id
        )

    assert history[0].reason == "extracted from article"
