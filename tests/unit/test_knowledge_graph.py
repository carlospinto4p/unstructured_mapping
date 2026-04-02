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


def test_store_save_provenances_bulk(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    provenances = [
        Provenance(
            entity_id=e.entity_id,
            document_id=f"doc{i}",
            source="bbc",
            mention_text="Test",
            context_snippet=f"ctx {i}",
        )
        for i in range(5)
    ]
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        inserted = store.save_provenances(provenances)
        records = store.get_provenance(e.entity_id)

    assert inserted == 5
    assert len(records) == 5


def test_store_save_provenances_deduplication(tmp_path):
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
        inserted = store.save_provenances([p, p])
        records = store.get_provenance(e.entity_id)

    assert inserted == 0
    assert len(records) == 1


def test_store_save_provenances_empty(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        inserted = store.save_provenances([])

    assert inserted == 0


# -- KnowledgeStore: temporal provenance --


def test_find_recent_mentions(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2024, 6, 1, tzinfo=timezone.utc)
    cutoff = datetime(2024, 3, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(Provenance(
            entity_id=e.entity_id,
            document_id="old_doc", source="bbc",
            mention_text="Test",
            context_snippet="old ctx",
            detected_at=old,
        ))
        store.save_provenance(Provenance(
            entity_id=e.entity_id,
            document_id="new_doc", source="ap",
            mention_text="Test",
            context_snippet="new ctx",
            detected_at=recent,
        ))
        results = store.find_recent_mentions(
            e.entity_id, since=cutoff
        )

    assert len(results) == 1
    assert results[0].document_id == "new_doc"


def test_find_recent_mentions_ordered_desc(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    t1 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 6, 1, tzinfo=timezone.utc)
    t3 = datetime(2024, 9, 1, tzinfo=timezone.utc)
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        for i, t in enumerate([t1, t2, t3]):
            store.save_provenance(Provenance(
                entity_id=e.entity_id,
                document_id=f"doc{i}",
                source="bbc",
                mention_text="Test",
                context_snippet="ctx",
                detected_at=t,
            ))
        results = store.find_recent_mentions(
            e.entity_id, since=since
        )

    assert len(results) == 3
    assert results[0].document_id == "doc2"
    assert results[2].document_id == "doc0"


def test_find_recent_mentions_empty(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(Provenance(
            entity_id=e.entity_id,
            document_id="doc1", source="bbc",
            mention_text="Test",
            context_snippet="ctx",
            detected_at=datetime(
                2024, 1, 1, tzinfo=timezone.utc
            ),
        ))
        results = store.find_recent_mentions(
            e.entity_id, since=future
        )

    assert len(results) == 0


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
    assert loaded.updated_at is None


def test_entity_updated_at_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    created = datetime(2024, 1, 15, tzinfo=timezone.utc)
    updated = datetime(2024, 6, 1, tzinfo=timezone.utc)
    e = _make_entity(
        created_at=created,
        updated_at=updated,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert loaded.created_at == created
    assert loaded.updated_at == updated


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


# -- Entity subtype --


def test_entity_subtype_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(
        canonical_name="Apple Inc.",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert loaded.subtype == "company"


def test_entity_subtype_none_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert loaded.subtype is None


def test_store_find_entities_by_subtype(tmp_path):
    db = tmp_path / "kg.db"
    company = _make_entity(
        canonical_name="Apple Inc.",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
        description="Tech company.",
    )
    bank = _make_entity(
        canonical_name="Federal Reserve",
        entity_type=EntityType.ORGANIZATION,
        subtype="central_bank",
        description="US central bank.",
    )
    other = _make_entity(
        canonical_name="UN",
        entity_type=EntityType.ORGANIZATION,
        description="International org.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(company)
        store.save_entity(bank)
        store.save_entity(other)
        companies = store.find_entities_by_subtype(
            EntityType.ORGANIZATION, "company"
        )
        banks = store.find_entities_by_subtype(
            EntityType.ORGANIZATION, "central_bank"
        )

    assert len(companies) == 1
    assert companies[0].canonical_name == "Apple Inc."
    assert len(banks) == 1
    assert banks[0].canonical_name == "Federal Reserve"


# -- ASSET and METRIC entity types --


def test_asset_entity(tmp_path):
    db = tmp_path / "kg.db"
    asset = Entity(
        canonical_name="Bitcoin",
        entity_type=EntityType.ASSET,
        subtype="crypto",
        description="Decentralized cryptocurrency.",
        aliases=("BTC", "XBT"),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(asset)
        by_type = store.find_entities_by_type(
            EntityType.ASSET
        )
        by_sub = store.find_entities_by_subtype(
            EntityType.ASSET, "crypto"
        )

    assert len(by_type) == 1
    assert by_type[0].canonical_name == "Bitcoin"
    assert len(by_sub) == 1


def test_metric_entity(tmp_path):
    db = tmp_path / "kg.db"
    metric = Entity(
        canonical_name="Consumer Price Index",
        entity_type=EntityType.METRIC,
        subtype="inflation",
        description="Measures average change in prices "
        "paid by urban consumers.",
        aliases=("CPI",),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(metric)
        by_type = store.find_entities_by_type(
            EntityType.METRIC
        )
        by_alias = store.find_by_alias("CPI")

    assert len(by_type) == 1
    assert by_type[0].subtype == "inflation"
    assert len(by_alias) == 1


# -- Audit log: entity history --


def test_entity_create_logs_history(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(aliases=("A1",))
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        history = store.get_entity_history(e.entity_id)

    assert len(history) == 1
    rev = history[0]
    assert rev.operation == "create"
    assert rev.canonical_name == "Test Entity"
    assert rev.aliases == ("A1",)
    assert rev.reason is None


def test_entity_update_logs_history(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(description="Original.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        updated = Entity(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            description="Updated.",
        )
        store.save_entity(
            updated, reason="corrected description"
        )
        history = store.get_entity_history(e.entity_id)

    assert len(history) == 2
    assert history[0].operation == "create"
    assert history[0].description == "Original."
    assert history[1].operation == "update"
    assert history[1].description == "Updated."
    assert history[1].reason == "corrected description"


def test_entity_merge_logs_both_entities(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="Apple Computer")
    e2 = _make_entity(canonical_name="Apple Inc.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.merge_entities(
            e1.entity_id, e2.entity_id
        )
        h1 = store.get_entity_history(e1.entity_id)
        h2 = store.get_entity_history(e2.entity_id)

    merge_revs_1 = [
        r for r in h1 if r.operation == "merge"
    ]
    merge_revs_2 = [
        r for r in h2 if r.operation == "merge"
    ]
    assert len(merge_revs_1) == 1
    assert merge_revs_1[0].status == EntityStatus.MERGED
    assert len(merge_revs_2) == 1


def test_entity_at_point_in_time(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(description="V1.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        history = store.get_entity_history(e.entity_id)
        t1 = history[0].changed_at
        updated = Entity(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            description="V2.",
        )
        store.save_entity(updated)
        snap = store.get_entity_at(e.entity_id, t1)

    assert snap is not None
    assert snap.description == "V1."


def test_entity_at_before_creation(tmp_path):
    db = tmp_path / "kg.db"
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    e = _make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        snap = store.get_entity_at(e.entity_id, past)

    assert snap is None


def test_revert_entity(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity(
        description="Original.",
        aliases=("OG",),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        history = store.get_entity_history(e.entity_id)
        rev_id = history[0].revision_id
        updated = Entity(
            entity_id=e.entity_id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            description="Wrong update.",
        )
        store.save_entity(updated)
        restored = store.revert_entity(
            e.entity_id, rev_id
        )
        current = store.get_entity(e.entity_id)
        full_history = store.get_entity_history(
            e.entity_id
        )

    assert restored.description == "Original."
    assert restored.aliases == ("OG",)
    assert current is not None
    assert current.description == "Original."
    assert len(full_history) == 3
    assert full_history[2].operation == "revert"


def test_revert_entity_bad_revision(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        with pytest.raises(ValueError):
            store.revert_entity(e.entity_id, 9999)


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


# -- Co-mention query --


def test_find_co_mentioned_basic(tmp_path):
    db = tmp_path / "kg.db"
    cpi = _make_entity(
        canonical_name="CPI",
        entity_type=EntityType.METRIC,
        description="Consumer Price Index.",
    )
    apple = _make_entity(
        canonical_name="Apple Inc.",
        entity_type=EntityType.ORGANIZATION,
        description="Tech company.",
    )
    gold = _make_entity(
        canonical_name="Gold",
        entity_type=EntityType.ASSET,
        description="Commodity.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(cpi)
        store.save_entity(apple)
        store.save_entity(gold)
        # CPI and Apple in doc1
        store.save_provenance(Provenance(
            entity_id=cpi.entity_id,
            document_id="doc1", source="bbc",
            mention_text="CPI",
            context_snippet="CPI rose 3.2%",
        ))
        store.save_provenance(Provenance(
            entity_id=apple.entity_id,
            document_id="doc1", source="bbc",
            mention_text="Apple",
            context_snippet="Apple stock fell",
        ))
        # CPI and Gold in doc2
        store.save_provenance(Provenance(
            entity_id=cpi.entity_id,
            document_id="doc2", source="bbc",
            mention_text="CPI",
            context_snippet="CPI data released",
        ))
        store.save_provenance(Provenance(
            entity_id=gold.entity_id,
            document_id="doc2", source="bbc",
            mention_text="Gold",
            context_snippet="Gold surged",
        ))
        # CPI and Apple again in doc3
        store.save_provenance(Provenance(
            entity_id=cpi.entity_id,
            document_id="doc3", source="ap",
            mention_text="CPI",
            context_snippet="CPI beat expectations",
        ))
        store.save_provenance(Provenance(
            entity_id=apple.entity_id,
            document_id="doc3", source="ap",
            mention_text="Apple",
            context_snippet="Apple earnings",
        ))
        results = store.find_co_mentioned(
            cpi.entity_id
        )

    assert len(results) == 2
    # Apple co-mentioned in 2 docs, Gold in 1
    assert results[0][0].entity_id == apple.entity_id
    assert results[0][1] == 2
    assert results[1][0].entity_id == gold.entity_id
    assert results[1][1] == 1


def test_find_co_mentioned_with_since(tmp_path):
    db = tmp_path / "kg.db"
    e1 = _make_entity(canonical_name="E1")
    e2 = _make_entity(
        canonical_name="E2",
        entity_type=EntityType.ORGANIZATION,
        description="Org.",
    )
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2024, 6, 1, tzinfo=timezone.utc)
    cutoff = datetime(2024, 3, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        # Old co-mention
        store.save_provenance(Provenance(
            entity_id=e1.entity_id,
            document_id="old_doc", source="bbc",
            mention_text="E1",
            context_snippet="ctx",
            detected_at=old,
        ))
        store.save_provenance(Provenance(
            entity_id=e2.entity_id,
            document_id="old_doc", source="bbc",
            mention_text="E2",
            context_snippet="ctx",
            detected_at=old,
        ))
        # Recent co-mention
        store.save_provenance(Provenance(
            entity_id=e1.entity_id,
            document_id="new_doc", source="ap",
            mention_text="E1",
            context_snippet="ctx",
            detected_at=recent,
        ))
        store.save_provenance(Provenance(
            entity_id=e2.entity_id,
            document_id="new_doc", source="ap",
            mention_text="E2",
            context_snippet="ctx",
            detected_at=recent,
        ))
        all_results = store.find_co_mentioned(
            e1.entity_id
        )
        recent_results = store.find_co_mentioned(
            e1.entity_id, since=cutoff
        )

    assert len(all_results) == 1
    assert all_results[0][1] == 2  # 2 docs total
    assert len(recent_results) == 1
    assert recent_results[0][1] == 1  # 1 doc since cutoff


def test_find_co_mentioned_no_self_match(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(Provenance(
            entity_id=e.entity_id,
            document_id="doc1", source="bbc",
            mention_text="Test",
            context_snippet="ctx",
        ))
        results = store.find_co_mentioned(e.entity_id)

    assert len(results) == 0


def test_find_co_mentioned_empty(tmp_path):
    db = tmp_path / "kg.db"
    e = _make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        results = store.find_co_mentioned(e.entity_id)

    assert len(results) == 0
