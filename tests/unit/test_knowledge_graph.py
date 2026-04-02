"""Tests for the knowledge_graph module."""

from datetime import datetime, timezone

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityStatus,
    EntityType,
    KnowledgeStore,
    Provenance,
    Relationship,
)


# -- EntityType enum --


def test_entity_type_values():
    assert EntityType.PERSON == "person"
    assert EntityType.ORGANIZATION == "organization"
    assert EntityType.PLACE == "place"
    assert EntityType.TOPIC == "topic"
    assert EntityType.PRODUCT == "product"
    assert EntityType.LEGISLATION == "legislation"
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


def _make_entity(**kwargs):
    defaults = {
        "canonical_name": "Test Entity",
        "entity_type": EntityType.PERSON,
        "description": "A test entity.",
    }
    defaults.update(kwargs)
    return Entity(**defaults)


def test_entity_auto_id():
    e1 = _make_entity()
    e2 = _make_entity()
    assert len(e1.entity_id) == 32
    assert e1.entity_id != e2.entity_id


def test_entity_defaults():
    e = _make_entity()
    assert e.aliases == ()
    assert e.status == EntityStatus.ACTIVE
    assert e.merged_into is None
    assert e.valid_from is None
    assert e.valid_until is None


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


# -- KnowledgeStore: entity operations --


def test_store_save_and_get_entity(tmp_path):
    db = tmp_path / "kg.db"
    entity = _make_entity(
        aliases=("Alias1", "Alias2")
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(entity)
        loaded = store.get_entity(entity.entity_id)

    assert loaded is not None
    assert loaded.canonical_name == "Test Entity"
    assert loaded.entity_type == EntityType.PERSON
    assert loaded.aliases == ("Alias1", "Alias2")


def test_store_get_entity_not_found(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        assert store.get_entity("nonexistent") is None


def test_store_find_by_name(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(canonical_name="John Doe")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        results = store.find_by_name("john doe")

    assert len(results) == 1
    assert results[0].canonical_name == "John Doe"


def test_store_find_by_alias(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(aliases=("JD", "Johnny"))
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        results = store.find_by_alias("jd")

    assert len(results) == 1
    assert results[0].entity_id == e.entity_id


def test_store_update_entity_aliases(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(aliases=("Old",))
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        updated = Entity(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            description=e.description,
            aliases=("New1", "New2"),
        )
        store.save_entity(updated)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert "Old" not in loaded.aliases
    assert loaded.aliases == ("New1", "New2")


# -- KnowledgeStore: provenance operations --


def test_store_save_and_get_provenance(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    p = Provenance(
        entity_id=e.entity_id,
        document_id="doc123",
        source="bbc",
        mention_text="Test Entity",
        context_snippet="...about Test Entity today...",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(p)
        records = store.get_provenance(e.entity_id)

    assert len(records) == 1
    assert records[0].document_id == "doc123"
    assert records[0].context_snippet == (
        "...about Test Entity today..."
    )


def test_store_provenance_deduplication(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    p = Provenance(
        entity_id=e.entity_id,
        document_id="doc1",
        source="bbc",
        mention_text="Test",
        context_snippet="ctx",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(p)
        store.save_provenance(p)
        records = store.get_provenance(e.entity_id)

    assert len(records) == 1


# -- KnowledgeStore: relationship operations --


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


# -- KnowledgeStore: merge operation --


def test_store_merge_entities(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Apple Computer")
    e2 = _make_entity(canonical_name="Apple Inc.")
    e3 = _make_entity(canonical_name="Microsoft")
    p = Provenance(
        entity_id=e1.entity_id,
        document_id="doc1",
        source="bbc",
        mention_text="Apple Computer",
        context_snippet="ctx",
    )
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e3.entity_id,
        relation_type="competed_with",
        description="Competed in the PC market.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        store.save_provenance(p)
        store.save_relationship(rel)
        store.merge_entities(
            e1.entity_id, e2.entity_id
        )
        deprecated = store.get_entity(e1.entity_id)
        prov = store.get_provenance(e2.entity_id)
        rels = store.get_relationships(
            e2.entity_id, as_target=False
        )

    assert deprecated is not None
    assert deprecated.status == EntityStatus.MERGED
    assert deprecated.merged_into == e2.entity_id
    assert len(prov) == 1
    assert prov[0].document_id == "doc1"
    assert len(rels) == 1
    assert rels[0].relation_type == "competed_with"


def test_store_merge_nonexistent_raises(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        with pytest.raises(ValueError):
            store.merge_entities("fake", e.entity_id)


# -- KnowledgeStore: temporal fields --


def test_entity_temporal_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    now = datetime(2024, 1, 15, tzinfo=timezone.utc)
    e = _make_entity(
        valid_from=now,
        created_at=now,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert loaded.valid_from == now
    assert loaded.created_at == now
    assert loaded.valid_until is None


# -- Relationship: qualifier_id and relation_kind_id --


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


# -- KnowledgeStore: ROLE and RELATION_KIND entities --


def test_store_role_entity(tmp_path):
    db = tmp_path / "kg.db"
    role = Entity(
        canonical_name="Chief Technology Officer",
        entity_type=EntityType.ROLE,
        description="Senior executive responsible for "
        "technology strategy.",
        aliases=("CTO", "head of technology"),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(role)
        by_alias = store.find_by_alias("cto")
        by_type = store.find_entities_by_type(
            EntityType.ROLE
        )

    assert len(by_alias) == 1
    assert by_alias[0].entity_id == role.entity_id
    assert len(by_type) == 1
    assert by_type[0].canonical_name == (
        "Chief Technology Officer"
    )


def test_store_relation_kind_entity(tmp_path):
    db = tmp_path / "kg.db"
    kind = Entity(
        canonical_name="employment",
        entity_type=EntityType.RELATION_KIND,
        description="Employment relationship between "
        "a person and an organization.",
        aliases=(
            "works_at",
            "employed_by",
            "serves_as",
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(kind)
        results = store.find_by_alias("employed_by")

    assert len(results) == 1
    assert results[0].canonical_name == "employment"


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
