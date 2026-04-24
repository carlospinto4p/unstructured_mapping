"""Tests for KnowledgeStore ingestion runs and history helpers.

Covers:

- Ingestion run CRUD (``save_run``, ``get_run``,
  ``finish_run``) and the success / failure transitions.
- ``run_id`` linkage on provenance and relationship rows —
  the join key that ties every written row back to the run
  that produced it.
- Schema migration for legacy DBs missing the ``run_id``
  column on provenance and relationships.
- Mention-count helpers (``count_mentions_for_entity`` /
  ``count_mentions_for_entities``) and the entity-joined
  mention fetch used by the preview CLI.

Provenance CRUD, temporal queries, and the co-mention query
live in :mod:`tests.unit.test_kg_provenance`.
"""

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


# -- Article failures / resume-run --


def test_save_and_get_failed_document_ids(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.save_article_failure(run.run_id, "doc-b", "boom")
        store.save_article_failure(run.run_id, "doc-a", "kaboom")
        failed = store.get_failed_document_ids(run.run_id)

    # Alphabetical order for determinism.
    assert failed == ["doc-a", "doc-b"]


def test_save_article_failure_upserts_same_document(tmp_path):
    """Re-failing the same doc in the same run overwrites
    rather than duplicating — the composite PK is
    ``(run_id, document_id)``."""
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.save_article_failure(run.run_id, "doc-1", "first")
        store.save_article_failure(run.run_id, "doc-1", "second")
        failed = store.get_failed_document_ids(run.run_id)
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT error_message FROM article_failures "
            "WHERE run_id = ? AND document_id = ?",
            (run.run_id, "doc-1"),
        ).fetchall()

    assert failed == ["doc-1"]
    assert len(rows) == 1
    assert rows[0]["error_message"] == "second"


def test_get_failed_document_ids_is_run_scoped(tmp_path):
    """Failures from a different run must not leak into
    the resume set — otherwise resuming run A would
    re-queue run B's failures."""
    db = tmp_path / "kg.db"
    run_a = IngestionRun()
    run_b = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run_a)
        store.save_run(run_b)
        store.save_article_failure(run_a.run_id, "doc-a", "a")
        store.save_article_failure(run_b.run_id, "doc-b", "b")
        assert store.get_failed_document_ids(run_a.run_id) == ["doc-a"]
        assert store.get_failed_document_ids(run_b.run_id) == ["doc-b"]


def test_get_failed_document_ids_empty_for_clean_run(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        assert store.get_failed_document_ids(run.run_id) == []


def test_get_entities_touched_by_run_collects_distinct_ids(tmp_path):
    """Every entity with at least one provenance row tagged
    with the run is returned; duplicates collapse.
    """
    db = tmp_path / "kg.db"
    run = IngestionRun()
    a = make_entity(canonical_name="A")
    b = make_entity(canonical_name="B")
    c = make_entity(canonical_name="C")
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        for e in (a, b, c):
            store.save_entity(e)
        # a + b in this run; c in a different run.
        store.save_provenances(
            [
                Provenance(
                    entity_id=a.entity_id,
                    document_id="doc1",
                    source="t",
                    mention_text="A",
                    context_snippet="ctx",
                    run_id=run.run_id,
                ),
                Provenance(
                    entity_id=a.entity_id,
                    document_id="doc2",
                    source="t",
                    mention_text="A",
                    context_snippet="ctx",
                    run_id=run.run_id,
                ),
                Provenance(
                    entity_id=b.entity_id,
                    document_id="doc3",
                    source="t",
                    mention_text="B",
                    context_snippet="ctx",
                    run_id=run.run_id,
                ),
                Provenance(
                    entity_id=c.entity_id,
                    document_id="doc4",
                    source="t",
                    mention_text="C",
                    context_snippet="ctx",
                    run_id="other-run",
                ),
            ]
        )
        touched = store.get_entities_touched_by_run(run.run_id)

    assert touched == {a.entity_id, b.entity_id}


def test_get_relationship_keys_for_run_drops_valid_from(tmp_path):
    """Keys are the ``(src, tgt, type)`` identity without
    ``valid_from`` so the same edge under a new bound
    still matches across runs.
    """
    db = tmp_path / "kg.db"
    run = IngestionRun()
    e1 = make_entity(canonical_name="E1")
    e2 = make_entity(
        canonical_name="E2",
        entity_type=EntityType.ORGANIZATION,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.save_entity(e1)
        store.save_entity(e2)
        store.save_relationship(
            Relationship(
                source_id=e1.entity_id,
                target_id=e2.entity_id,
                relation_type="acquires",
                description="e1 acquires e2",
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                run_id=run.run_id,
            )
        )
        store.save_relationship(
            Relationship(
                source_id=e1.entity_id,
                target_id=e2.entity_id,
                relation_type="acquires",
                description="e1 acquires e2 (revised)",
                valid_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
                run_id=run.run_id,
            )
        )
        # Unrelated run — must not appear.
        store.save_relationship(
            Relationship(
                source_id=e2.entity_id,
                target_id=e1.entity_id,
                relation_type="owned_by",
                description="other",
                valid_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
                run_id="other-run",
            )
        )
        keys = store.get_relationship_keys_for_run(run.run_id)

    assert keys == {(e1.entity_id, e2.entity_id, "acquires")}


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


# -- get_*/find_* naming convention -----------------------


def test_back_compat_aliases_resolve_to_find_methods():
    """Old ``get_*`` names that returned filtered lists are
    now aliases for the canonical ``find_*`` methods.
    Compared at the class level because instance attribute
    access creates fresh bound-method objects, so two
    bound methods of the same underlying function still
    fail an ``is`` check.
    """
    pairs = (
        ("get_relationships", "find_relationships_for_entity"),
        ("get_relationships_between", "find_relationships_between"),
        ("get_relationship_history", "find_relationship_history"),
        ("get_provenance", "find_provenance_for_entity"),
        ("get_entity_history", "find_entity_history"),
        ("get_entities_touched_by_run", "find_entities_touched_by_run"),
        ("get_failed_document_ids", "find_failed_document_ids"),
        (
            "get_relationship_keys_for_run",
            "find_relationship_keys_for_run",
        ),
    )
    for legacy, canonical in pairs:
        assert getattr(KnowledgeStore, legacy) is getattr(
            KnowledgeStore, canonical
        ), f"{legacy} should alias {canonical}"
