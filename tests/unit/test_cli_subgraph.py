"""Tests for the ``cli.subgraph`` k-hop extraction CLI.

Builds a small graph and exercises the BFS, min-
confidence filter, name-vs-id resolution, ambiguity
handling, and the JSON payload contract.
"""

import json

import pytest

from unstructured_mapping.cli.subgraph import build_subgraph, main
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
    Relationship,
)

from .conftest import make_org


@pytest.fixture
def graph_db(tmp_path):
    """Build a small chain: A — r1 → B — r2 → C, plus an
    isolated D to verify BFS does not reach it."""
    db = tmp_path / "kg.db"
    a = make_org("Apple")
    b = make_org("Banana")
    c = make_org("Cherry")
    d = make_org("Date")
    rel_ab = Relationship(
        source_id=a.entity_id,
        target_id=b.entity_id,
        relation_type="trades_with",
        description="ctx",
        document_id="doc-ab",
        confidence=0.9,
    )
    rel_bc = Relationship(
        source_id=b.entity_id,
        target_id=c.entity_id,
        relation_type="supplies",
        description="ctx",
        document_id="doc-bc",
        confidence=0.3,
    )
    with KnowledgeStore(db_path=db) as store:
        for e in (a, b, c, d):
            store.save_entity(e)
        store.save_relationship(rel_ab)
        store.save_relationship(rel_bc)
    return db, a, b, c, d


def test_hops_zero_returns_root_only(graph_db):
    db, a, *_ = graph_db
    with KnowledgeStore(db_path=db) as store:
        payload = build_subgraph(
            store, entity_id=a.entity_id, name=None, hops=0
        )
    assert payload["root"]["entity_id"] == a.entity_id
    assert len(payload["entities"]) == 1
    assert payload["relationships"] == []
    assert payload["documents"] == []


def test_hops_one_reaches_direct_neighbours(graph_db):
    db, a, b, c, d = graph_db
    with KnowledgeStore(db_path=db) as store:
        payload = build_subgraph(
            store, entity_id=a.entity_id, name=None, hops=1
        )
    ids = {e["entity_id"] for e in payload["entities"]}
    assert ids == {a.entity_id, b.entity_id}
    rel_types = {r["relation_type"] for r in payload["relationships"]}
    assert rel_types == {"trades_with"}
    assert payload["documents"] == ["doc-ab"]
    # Isolated D is never in the payload.
    assert d.entity_id not in ids


def test_hops_two_reaches_two_away(graph_db):
    db, a, b, c, _ = graph_db
    with KnowledgeStore(db_path=db) as store:
        payload = build_subgraph(
            store, entity_id=a.entity_id, name=None, hops=2
        )
    ids = {e["entity_id"] for e in payload["entities"]}
    assert ids == {a.entity_id, b.entity_id, c.entity_id}
    assert {r["relation_type"] for r in payload["relationships"]} == {
        "trades_with",
        "supplies",
    }
    # Both edge documents surfaced.
    assert set(payload["documents"]) == {"doc-ab", "doc-bc"}


def test_min_confidence_drops_weak_edges(graph_db):
    """At --min-confidence 0.5, the B→C edge (0.3) is
    dropped, which also prevents reaching C via the BFS.
    """
    db, a, b, c, _ = graph_db
    with KnowledgeStore(db_path=db) as store:
        payload = build_subgraph(
            store,
            entity_id=a.entity_id,
            name=None,
            hops=2,
            min_confidence=0.5,
        )
    ids = {e["entity_id"] for e in payload["entities"]}
    assert ids == {a.entity_id, b.entity_id}
    assert c.entity_id not in ids


def test_build_subgraph_rejects_both_entity_id_and_name(graph_db):
    db, a, *_ = graph_db
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(ValueError, match="exactly one"):
            build_subgraph(
                store,
                entity_id=a.entity_id,
                name="Apple",
                hops=1,
            )


def test_build_subgraph_rejects_negative_hops(graph_db):
    db, a, *_ = graph_db
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(ValueError, match="hops must be"):
            build_subgraph(store, entity_id=a.entity_id, name=None, hops=-1)


def test_resolve_by_name_success(graph_db):
    db, a, *_ = graph_db
    with KnowledgeStore(db_path=db) as store:
        payload = build_subgraph(store, entity_id=None, name="Apple", hops=1)
    assert payload["root"]["entity_id"] == a.entity_id


def test_resolve_by_name_ambiguous_fails(tmp_path):
    db = tmp_path / "kg.db"
    dup1 = make_org("Acme", entity_id="e1")
    dup2 = make_org("Acme", entity_id="e2")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(dup1)
        store.save_entity(dup2)
        with pytest.raises(SystemExit, match="2 entities match"):
            build_subgraph(store, entity_id=None, name="Acme", hops=1)


def test_resolve_unknown_id_fails(graph_db):
    db, *_ = graph_db
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(SystemExit, match="not found"):
            build_subgraph(store, entity_id="nope", name=None, hops=1)


def test_main_writes_to_stdout(graph_db, capsys):
    db, a, *_ = graph_db
    main(["--db", str(db), "--entity-id", a.entity_id, "--hops", "1"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["root"]["canonical_name"] == "Apple"
    assert payload["hops"] == 1
    assert {e["canonical_name"] for e in payload["entities"]} == {
        "Apple",
        "Banana",
    }


def test_main_writes_to_output_file(graph_db, tmp_path):
    db, a, *_ = graph_db
    out = tmp_path / "subgraph.json"
    main(
        [
            "--db",
            str(db),
            "--entity-id",
            a.entity_id,
            "--hops",
            "2",
            "--output",
            str(out),
        ]
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["entities"]) == 3
    assert set(payload["documents"]) == {"doc-ab", "doc-bc"}


def test_main_rejects_negative_hops(graph_db):
    db, a, *_ = graph_db
    with pytest.raises(SystemExit, match=">= 0"):
        main(
            [
                "--db",
                str(db),
                "--entity-id",
                a.entity_id,
                "--hops",
                "-1",
            ]
        )


def test_payload_is_deterministic(graph_db):
    """Two back-to-back calls produce byte-identical JSON
    so the output can be diffed / snapshotted."""
    db, a, *_ = graph_db
    with KnowledgeStore(db_path=db) as store:
        first = build_subgraph(
            store, entity_id=a.entity_id, name=None, hops=2
        )
        second = build_subgraph(
            store, entity_id=a.entity_id, name=None, hops=2
        )
    assert json.dumps(first) == json.dumps(second)
