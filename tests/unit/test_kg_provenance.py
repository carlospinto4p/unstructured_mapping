"""Tests for KnowledgeStore provenance and ingestion run operations."""

import sqlite3
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph import (
    EntityType,
    IngestionRun,
    KnowledgeStore,
    Provenance,
    Relationship,
    RunStatus,
)

from .conftest import make_entity


# -- KnowledgeStore: provenance operations --


def test_store_save_and_get_provenance(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
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
    assert records[0].context_snippet == ("...about Test Entity today...")


def test_has_document_provenance(tmp_path):
    """has_document_provenance reports exact matches."""
    db = tmp_path / "kg.db"
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        assert store.has_document_provenance("doc1") is False
        store.save_provenance(
            Provenance(
                entity_id=e.entity_id,
                document_id="doc1",
                source="bbc",
                mention_text="Test",
                context_snippet="ctx",
            )
        )
        assert store.has_document_provenance("doc1") is True
        assert store.has_document_provenance("other") is False


def test_store_provenance_deduplication(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
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
    e = make_entity()
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
    e = make_entity()
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
    e = make_entity()
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2024, 6, 1, tzinfo=timezone.utc)
    cutoff = datetime(2024, 3, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(
            Provenance(
                entity_id=e.entity_id,
                document_id="old_doc",
                source="bbc",
                mention_text="Test",
                context_snippet="old ctx",
                detected_at=old,
            )
        )
        store.save_provenance(
            Provenance(
                entity_id=e.entity_id,
                document_id="new_doc",
                source="ap",
                mention_text="Test",
                context_snippet="new ctx",
                detected_at=recent,
            )
        )
        results = store.find_recent_mentions(e.entity_id, since=cutoff)

    assert len(results) == 1
    assert results[0].document_id == "new_doc"


def test_find_recent_mentions_ordered_desc(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
    t1 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 6, 1, tzinfo=timezone.utc)
    t3 = datetime(2024, 9, 1, tzinfo=timezone.utc)
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        for i, t in enumerate([t1, t2, t3]):
            store.save_provenance(
                Provenance(
                    entity_id=e.entity_id,
                    document_id=f"doc{i}",
                    source="bbc",
                    mention_text="Test",
                    context_snippet="ctx",
                    detected_at=t,
                )
            )
        results = store.find_recent_mentions(e.entity_id, since=since)

    assert len(results) == 3
    assert results[0].document_id == "doc2"
    assert results[2].document_id == "doc0"


def test_find_recent_mentions_empty(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(
            Provenance(
                entity_id=e.entity_id,
                document_id="doc1",
                source="bbc",
                mention_text="Test",
                context_snippet="ctx",
                detected_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )
        results = store.find_recent_mentions(e.entity_id, since=future)

    assert len(results) == 0


# -- Co-mention query --


def test_find_co_mentioned_basic(tmp_path):
    db = tmp_path / "kg.db"
    cpi = make_entity(
        canonical_name="CPI",
        entity_type=EntityType.METRIC,
        description="Consumer Price Index.",
    )
    apple = make_entity(
        canonical_name="Apple Inc.",
        entity_type=EntityType.ORGANIZATION,
        description="Tech company.",
    )
    gold = make_entity(
        canonical_name="Gold",
        entity_type=EntityType.ASSET,
        description="Commodity.",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(cpi)
        store.save_entity(apple)
        store.save_entity(gold)
        # CPI and Apple in doc1
        store.save_provenance(
            Provenance(
                entity_id=cpi.entity_id,
                document_id="doc1",
                source="bbc",
                mention_text="CPI",
                context_snippet="CPI rose 3.2%",
            )
        )
        store.save_provenance(
            Provenance(
                entity_id=apple.entity_id,
                document_id="doc1",
                source="bbc",
                mention_text="Apple",
                context_snippet="Apple stock fell",
            )
        )
        # CPI and Gold in doc2
        store.save_provenance(
            Provenance(
                entity_id=cpi.entity_id,
                document_id="doc2",
                source="bbc",
                mention_text="CPI",
                context_snippet="CPI data released",
            )
        )
        store.save_provenance(
            Provenance(
                entity_id=gold.entity_id,
                document_id="doc2",
                source="bbc",
                mention_text="Gold",
                context_snippet="Gold surged",
            )
        )
        # CPI and Apple again in doc3
        store.save_provenance(
            Provenance(
                entity_id=cpi.entity_id,
                document_id="doc3",
                source="ap",
                mention_text="CPI",
                context_snippet="CPI beat expectations",
            )
        )
        store.save_provenance(
            Provenance(
                entity_id=apple.entity_id,
                document_id="doc3",
                source="ap",
                mention_text="Apple",
                context_snippet="Apple earnings",
            )
        )
        results = store.find_co_mentioned(cpi.entity_id)

    assert len(results) == 2
    # Apple co-mentioned in 2 docs, Gold in 1
    assert results[0][0].entity_id == apple.entity_id
    assert results[0][1] == 2
    assert results[1][0].entity_id == gold.entity_id
    assert results[1][1] == 1


def test_find_co_mentioned_with_since(tmp_path):
    db = tmp_path / "kg.db"
    e1 = make_entity(canonical_name="E1")
    e2 = make_entity(
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
        store.save_provenance(
            Provenance(
                entity_id=e1.entity_id,
                document_id="old_doc",
                source="bbc",
                mention_text="E1",
                context_snippet="ctx",
                detected_at=old,
            )
        )
        store.save_provenance(
            Provenance(
                entity_id=e2.entity_id,
                document_id="old_doc",
                source="bbc",
                mention_text="E2",
                context_snippet="ctx",
                detected_at=old,
            )
        )
        # Recent co-mention
        store.save_provenance(
            Provenance(
                entity_id=e1.entity_id,
                document_id="new_doc",
                source="ap",
                mention_text="E1",
                context_snippet="ctx",
                detected_at=recent,
            )
        )
        store.save_provenance(
            Provenance(
                entity_id=e2.entity_id,
                document_id="new_doc",
                source="ap",
                mention_text="E2",
                context_snippet="ctx",
                detected_at=recent,
            )
        )
        all_results = store.find_co_mentioned(e1.entity_id)
        recent_results = store.find_co_mentioned(e1.entity_id, since=cutoff)

    assert len(all_results) == 1
    assert all_results[0][1] == 2  # 2 docs total
    assert len(recent_results) == 1
    assert recent_results[0][1] == 1  # 1 doc since cutoff


def test_find_co_mentioned_no_self_match(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_provenance(
            Provenance(
                entity_id=e.entity_id,
                document_id="doc1",
                source="bbc",
                mention_text="Test",
                context_snippet="ctx",
            )
        )
        results = store.find_co_mentioned(e.entity_id)

    assert len(results) == 0


def test_find_co_mentioned_empty(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        results = store.find_co_mentioned(e.entity_id)

    assert len(results) == 0


def test_find_co_mentioned_limit(tmp_path):
    """limit= caps the number of co-mentioned entities."""
    db = tmp_path / "kg.db"
    hub = make_entity(canonical_name="Hub")
    others = [make_entity(canonical_name=f"Other {i}") for i in range(4)]
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(hub)
        for o in others:
            store.save_entity(o)
        for i, o in enumerate(others):
            doc = f"doc{i}"
            store.save_provenance(
                Provenance(
                    entity_id=hub.entity_id,
                    document_id=doc,
                    source="bbc",
                    mention_text="Hub",
                    context_snippet="ctx",
                )
            )
            store.save_provenance(
                Provenance(
                    entity_id=o.entity_id,
                    document_id=doc,
                    source="bbc",
                    mention_text=f"Other {i}",
                    context_snippet="ctx",
                )
            )
        all_results = store.find_co_mentioned(hub.entity_id)
        limited = store.find_co_mentioned(hub.entity_id, limit=2)

    assert len(all_results) == 4
    assert len(limited) == 2


# -- KnowledgeStore: ingestion run operations --


def test_store_save_and_get_run(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        loaded = store.get_run(run.run_id)

    assert loaded is not None
    assert loaded.run_id == run.run_id
    assert loaded.status == RunStatus.RUNNING
    assert loaded.document_count == 0


def test_store_finish_run(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.finish_run(
            run.run_id,
            status=RunStatus.COMPLETED,
            document_count=10,
            entity_count=42,
            relationship_count=7,
        )
        loaded = store.get_run(run.run_id)

    assert loaded is not None
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.finished_at is not None
    assert loaded.document_count == 10
    assert loaded.entity_count == 42
    assert loaded.relationship_count == 7


def test_store_finish_run_failed(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.finish_run(
            run.run_id,
            status=RunStatus.FAILED,
            error_message="Timeout",
        )
        loaded = store.get_run(run.run_id)

    assert loaded is not None
    assert loaded.status == RunStatus.FAILED
    assert loaded.error_message == "Timeout"


def test_store_get_run_not_found(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        loaded = store.get_run("nonexistent")

    assert loaded is None


# -- run_id on provenance and relationships --


def test_provenance_run_id_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
    run = IngestionRun()
    p = Provenance(
        entity_id=e.entity_id,
        document_id="doc1",
        source="bbc",
        mention_text="Test",
        context_snippet="ctx",
        run_id=run.run_id,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        store.save_run(run)
        store.save_provenance(p)
        records = store.get_provenance(e.entity_id)

    assert len(records) == 1
    assert records[0].run_id == run.run_id


def test_provenance_run_id_none_by_default(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
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
        records = store.get_provenance(e.entity_id)

    assert records[0].run_id is None


def test_relationship_run_id_round_trip(tmp_path):
    db = tmp_path / "kg.db"
    e1 = make_entity()
    e2 = make_entity(
        canonical_name="Entity 2",
        entity_type=EntityType.ORGANIZATION,
    )
    run = IngestionRun()
    rel = Relationship(
        source_id=e1.entity_id,
        target_id=e2.entity_id,
        relation_type="acquired",
        description="E1 acquired E2.",
        run_id=run.run_id,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_run(run)
        store.save_relationship(rel)
        rels = store.get_relationships(e1.entity_id)

    assert len(rels) == 1
    assert rels[0].run_id == run.run_id


def test_migration_adds_run_id(tmp_path):
    """Existing DBs without run_id get it via migration."""
    db = tmp_path / "kg.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE entities ("
        "entity_id TEXT PRIMARY KEY, "
        "canonical_name TEXT NOT NULL, "
        "entity_type TEXT NOT NULL, "
        "description TEXT NOT NULL, "
        "valid_from TEXT, valid_until TEXT, "
        "status TEXT NOT NULL DEFAULT 'active', "
        "merged_into TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE provenance ("
        "entity_id TEXT NOT NULL, "
        "document_id TEXT NOT NULL, "
        "source TEXT NOT NULL, "
        "mention_text TEXT NOT NULL, "
        "context_snippet TEXT NOT NULL, "
        "detected_at TEXT, "
        "PRIMARY KEY (entity_id, document_id, "
        "mention_text))"
    )
    conn.execute(
        "CREATE TABLE relationships ("
        "source_id TEXT NOT NULL, "
        "target_id TEXT NOT NULL, "
        "relation_type TEXT NOT NULL, "
        "description TEXT NOT NULL, "
        "valid_from TEXT, valid_until TEXT, "
        "document_id TEXT, discovered_at TEXT, "
        "PRIMARY KEY (source_id, target_id, "
        "relation_type, valid_from))"
    )
    conn.execute(
        "CREATE TABLE entity_aliases ("
        "entity_id TEXT NOT NULL, "
        "alias TEXT NOT NULL, "
        "PRIMARY KEY (entity_id, alias))"
    )
    conn.execute(
        "CREATE TABLE entity_history ("
        "history_id INTEGER PRIMARY KEY "
        "AUTOINCREMENT, "
        "entity_id TEXT NOT NULL, "
        "operation TEXT NOT NULL, "
        "changed_at TEXT NOT NULL, "
        "canonical_name TEXT NOT NULL, "
        "entity_type TEXT NOT NULL, "
        "subtype TEXT, description TEXT NOT NULL, "
        "aliases TEXT, valid_from TEXT, "
        "valid_until TEXT, status TEXT NOT NULL, "
        "merged_into TEXT, reason TEXT)"
    )
    conn.execute(
        "CREATE TABLE relationship_history ("
        "history_id INTEGER PRIMARY KEY "
        "AUTOINCREMENT, "
        "operation TEXT NOT NULL, "
        "changed_at TEXT NOT NULL, "
        "source_id TEXT NOT NULL, "
        "target_id TEXT NOT NULL, "
        "relation_type TEXT NOT NULL, "
        "description TEXT NOT NULL, "
        "qualifier_id TEXT, "
        "relation_kind_id TEXT, "
        "valid_from TEXT, valid_until TEXT, "
        "document_id TEXT, reason TEXT)"
    )
    conn.commit()
    conn.close()

    with KnowledgeStore(db_path=db) as store:
        cols_prov = {
            r[1]
            for r in store._conn.execute(
                "PRAGMA table_info(provenance)"
            ).fetchall()
        }
        cols_rel = {
            r[1]
            for r in store._conn.execute(
                "PRAGMA table_info(relationships)"
            ).fetchall()
        }

    assert "run_id" in cols_prov
    assert "run_id" in cols_rel


# -- count_mentions_for_entity + find_mentions_with_entities --


def test_count_mentions_for_entity(tmp_path):
    db = tmp_path / "kg.db"
    e = make_entity()
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(e)
        assert store.count_mentions_for_entity(e.entity_id) == 0
        store.save_provenances(
            [
                Provenance(
                    entity_id=e.entity_id,
                    document_id=f"doc-{i}",
                    source="test",
                    mention_text=f"m{i}",
                    context_snippet="ctx",
                )
                for i in range(3)
            ]
        )
        assert store.count_mentions_for_entity(e.entity_id) == 3


def test_count_mentions_for_entities_batches_and_zero_fills(tmp_path):
    """Grouped query returns one row per id, zeros for unseen ids."""
    db = tmp_path / "kg.db"
    a = make_entity(canonical_name="A")
    b = make_entity(canonical_name="B")
    c = make_entity(canonical_name="C")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(a)
        store.save_entity(b)
        store.save_entity(c)
        store.save_provenances(
            [
                Provenance(
                    entity_id=a.entity_id,
                    document_id=f"doc-a-{i}",
                    source="test",
                    mention_text=f"m{i}",
                    context_snippet="ctx",
                )
                for i in range(3)
            ]
        )
        store.save_provenances(
            [
                Provenance(
                    entity_id=b.entity_id,
                    document_id="doc-b-0",
                    source="test",
                    mention_text="m",
                    context_snippet="ctx",
                )
            ]
        )
        # c has no mentions — must still appear as 0.
        counts = store.count_mentions_for_entities(
            [a.entity_id, b.entity_id, c.entity_id]
        )
    assert counts == {
        a.entity_id: 3,
        b.entity_id: 1,
        c.entity_id: 0,
    }


def test_count_mentions_for_entities_empty_input(tmp_path):
    """Empty list short-circuits to an empty dict (no SQL)."""
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        assert store.count_mentions_for_entities([]) == {}


def test_find_mentions_with_entities_returns_pairs(
    tmp_path,
):
    """Rows come back as ``(Entity, Provenance)`` pairs
    ordered by detected_at so the first pair is the first
    mention."""
    db = tmp_path / "kg.db"
    apple = make_entity(
        canonical_name="Apple",
        entity_type=EntityType.ORGANIZATION,
    )
    msft = make_entity(
        canonical_name="Microsoft",
        entity_type=EntityType.ORGANIZATION,
    )
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        store.save_provenances(
            [
                Provenance(
                    entity_id=apple.entity_id,
                    document_id="doc-1",
                    source="test",
                    mention_text="Apple",
                    context_snippet="ctx1",
                    detected_at=t0,
                ),
                Provenance(
                    entity_id=msft.entity_id,
                    document_id="doc-1",
                    source="test",
                    mention_text="Microsoft",
                    context_snippet="ctx2",
                    detected_at=t0.replace(second=30),
                ),
                Provenance(
                    entity_id=apple.entity_id,
                    document_id="doc-2",
                    source="test",
                    mention_text="Apple",
                    context_snippet="ctx3",
                    detected_at=t0,
                ),
            ]
        )
        pairs = store.find_mentions_with_entities("doc-1")
    assert [(e.canonical_name, p.mention_text) for e, p in pairs] == [
        ("Apple", "Apple"),
        ("Microsoft", "Microsoft"),
    ]


def test_find_mentions_with_entities_empty_doc(
    tmp_path,
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        assert store.find_mentions_with_entities("missing") == []
