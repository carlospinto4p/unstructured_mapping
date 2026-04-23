"""Tests for KnowledgeStore provenance CRUD and queries.

Covers save/get/dedup, the temporal ``find_recent_mentions``
helper, and the co-mention query. Ingestion-run, migration,
and mention-count helpers live in
:mod:`tests.unit.test_kg_runs_and_history`.
"""

from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph import (
    EntityType,
    KnowledgeStore,
    Provenance,
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
