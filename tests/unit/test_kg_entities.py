"""Tests for KnowledgeStore entity operations."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityNotFound,
    EntityStatus,
    EntityType,
    KnowledgeStore,
    Provenance,
    Relationship,
    RevisionNotFound,
)

from .conftest import make_entity


# -- KnowledgeStore: entity CRUD --


def test_store_save_and_get_entity(tmp_path):
    db = tmp_path / "kg.db"
    entity = make_entity(
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
    e = make_entity(canonical_name="John Doe")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        results = store.find_by_name("john doe")

    assert len(results) == 1
    assert results[0].canonical_name == "John Doe"


def test_store_find_by_alias(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity(aliases=("JD", "Johnny"))
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        results = store.find_by_alias("jd")

    assert len(results) == 1
    assert results[0].entity_id == e.entity_id


def test_store_update_entity_aliases(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity(aliases=("Old",))
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


# -- KnowledgeStore: find_entities_by_status --


def test_find_entities_by_status(tmp_path):
    db = tmp_path / "kg.db"
    e1 = make_entity(canonical_name="Active Entity")
    e2 = make_entity(canonical_name="To Merge")
    e3 = make_entity(canonical_name="Surviving")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        store.merge_entities(
            e2.entity_id, e3.entity_id
        )
        active = store.find_entities_by_status(
            EntityStatus.ACTIVE
        )
        merged = store.find_entities_by_status(
            EntityStatus.MERGED
        )

    active_names = {e.canonical_name for e in active}
    assert "Active Entity" in active_names
    assert "Surviving" in active_names
    assert len(merged) == 1
    assert merged[0].canonical_name == "To Merge"


def test_find_entities_by_status_empty(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        result = store.find_entities_by_status(
            EntityStatus.DEPRECATED
        )
    assert result == []


# -- KnowledgeStore: find_by_name_prefix --


def test_find_by_name_prefix(tmp_path):
    db = tmp_path / "kg.db"
    e1 = make_entity(canonical_name="Apple Inc.")
    e2 = make_entity(canonical_name="Applied Materials")
    e3 = make_entity(canonical_name="Google")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        found = store.find_by_name_prefix("App")
        found_ci = store.find_by_name_prefix("app")
        none = store.find_by_name_prefix("Xyz")

    names = {e.canonical_name for e in found}
    assert len(found) == 2
    assert "Apple Inc." in names
    assert "Applied Materials" in names
    assert len(found_ci) == 2
    assert none == []


# -- KnowledgeStore: count_entities_by_type --


def test_count_entities_by_type(tmp_path):
    db = tmp_path / "kg.db"
    e1 = make_entity(
        canonical_name="A",
        entity_type=EntityType.PERSON,
    )
    e2 = make_entity(
        canonical_name="B",
        entity_type=EntityType.PERSON,
    )
    e3 = make_entity(
        canonical_name="C",
        entity_type=EntityType.ORGANIZATION,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_entity(e3)
        counts = store.count_entities_by_type()

    assert counts["person"] == 2
    assert counts["organization"] == 1
    assert "place" not in counts


def test_count_entities_by_type_empty(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        counts = store.count_entities_by_type()
    assert counts == {}


# -- KnowledgeStore: find_entities_since --


def test_find_entities_since(tmp_path):
    db = tmp_path / "kg.db"
    t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2025, 6, 1, tzinfo=timezone.utc)
    e_old = make_entity(
        canonical_name="Old",
        created_at=t1,
    )
    e_new = make_entity(
        canonical_name="New",
        created_at=t2,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e_old)
        store.save_entity(e_new)
        cutoff = datetime(
            2025, 3, 1, tzinfo=timezone.utc
        )
        found = store.find_entities_since(cutoff)
        all_found = store.find_entities_since(t1)

    assert len(found) == 1
    assert found[0].canonical_name == "New"
    assert len(all_found) == 2


def test_find_entities_since_empty(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        found = store.find_entities_since(
            datetime(2025, 1, 1, tzinfo=timezone.utc)
        )
    assert found == []


# -- KnowledgeStore: limit parameter on find methods --


def test_entity_search_limit(tmp_path):
    """limit= caps result size on entity search methods."""
    db = tmp_path / "kg.db"
    t_base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    persons = [
        make_entity(
            canonical_name=f"Person {i}",
            entity_type=EntityType.PERSON,
            subtype="executive",
            created_at=t_base,
        )
        for i in range(5)
    ]
    with KnowledgeStore(db_path=db) as store:
        for p in persons:
            store.save_entity(p)
        by_type = store.find_entities_by_type(
            EntityType.PERSON, limit=2
        )
        by_subtype = store.find_entities_by_subtype(
            EntityType.PERSON,
            "executive",
            limit=3,
        )
        by_status = store.find_entities_by_status(
            EntityStatus.ACTIVE, limit=1
        )
        by_prefix = store.find_by_name_prefix(
            "Person", limit=2
        )
        since_limited = store.find_entities_since(
            t_base, limit=4
        )
        # limit=None returns everything.
        all_persons = store.find_entities_by_type(
            EntityType.PERSON
        )

    assert len(by_type) == 2
    assert len(by_subtype) == 3
    assert len(by_status) == 1
    assert len(by_prefix) == 2
    assert len(since_limited) == 4
    assert len(all_persons) == 5


# -- KnowledgeStore: merge operation --


def test_store_merge_entities(tmp_path):
    db = tmp_path / "kg.db"
    e1 = make_entity(canonical_name="Apple Computer")
    e2 = make_entity(canonical_name="Apple Inc.")
    e3 = make_entity(canonical_name="Microsoft")
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
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        with pytest.raises(EntityNotFound):
            store.merge_entities("fake", e.entity_id)


# -- KnowledgeStore: temporal fields --


def test_entity_temporal_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    now = datetime(2024, 1, 15, tzinfo=timezone.utc)
    e = make_entity(
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
    # updated_at is always stamped by save_entity,
    # even on create, so we can track freshness.
    assert loaded.updated_at is not None


def test_save_entity_stamps_timestamps_on_create(tmp_path):
    """On create, both timestamps are auto-stamped."""
    db = tmp_path / "kg.db"
    e = make_entity()
    before = datetime.now(timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)
    after = datetime.now(timezone.utc)

    assert loaded is not None
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
    assert before <= loaded.created_at <= after
    assert loaded.created_at == loaded.updated_at


def test_save_entity_respects_explicit_created_at(tmp_path):
    """A caller-provided created_at is honoured on create.

    Useful for backfills or history-preserving imports.
    """
    db = tmp_path / "kg.db"
    created = datetime(2024, 1, 15, tzinfo=timezone.utc)
    e = make_entity(created_at=created)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert loaded.created_at == created
    # updated_at is still stamped by the storage layer.
    assert loaded.updated_at is not None
    assert loaded.updated_at >= created


def test_save_entity_advances_updated_at_on_update(
    tmp_path,
):
    """A subsequent save preserves created_at and bumps
    updated_at."""
    db = tmp_path / "kg.db"
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        first = store.get_entity(e.entity_id)
        # Re-save with a changed field.
        store.save_entity(
            replace(first, description="v2")
        )
        second = store.get_entity(e.entity_id)

    assert first is not None and second is not None
    assert second.created_at == first.created_at
    assert second.updated_at > first.updated_at


def test_backfill_entity_timestamps_populates_nulls(
    tmp_path,
):
    """The backfill helper fills NULL timestamps from the
    history audit log without touching rows that already
    have values."""
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        e = make_entity()
        store.save_entity(e)
        # Simulate a legacy row: null out its timestamps.
        store._conn.execute(
            "UPDATE entities "
            "SET created_at = NULL, updated_at = NULL "
            "WHERE entity_id = ?",
            (e.entity_id,),
        )
        store._conn.commit()

        updated = store.backfill_entity_timestamps()
        loaded = store.get_entity(e.entity_id)

        # Re-running is a no-op.
        again = store.backfill_entity_timestamps()

    assert updated == 1
    assert again == 0
    assert loaded is not None
    assert loaded.created_at is not None
    assert loaded.updated_at == loaded.created_at


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


# -- Entity subtype --


def test_entity_subtype_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity(
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
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        loaded = store.get_entity(e.entity_id)

    assert loaded is not None
    assert loaded.subtype is None


def test_store_find_entities_by_subtype(tmp_path):
    db = tmp_path / "kg.db"
    company = make_entity(
        canonical_name="Apple Inc.",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
        description="Tech company.",
    )
    bank = make_entity(
        canonical_name="Federal Reserve",
        entity_type=EntityType.ORGANIZATION,
        subtype="central_bank",
        description="US central bank.",
    )
    other = make_entity(
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
    e = make_entity(aliases=("A1",))
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
    e = make_entity(description="Original.")
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
    e1 = make_entity(canonical_name="Apple Computer")
    e2 = make_entity(canonical_name="Apple Inc.")
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
    e = make_entity(description="V1.")
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
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        snap = store.get_entity_at(e.entity_id, past)

    assert snap is None


def test_revert_entity(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity(
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
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        with pytest.raises(RevisionNotFound):
            store.revert_entity(e.entity_id, 9999)
