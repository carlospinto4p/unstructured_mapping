"""Tests for the alias-collision audit CLI.

Exercises the scoring, ranking, merge-target selection,
and the merge-application path with monkeypatched input
so the test does not block on stdin.
"""

from datetime import datetime, timezone

import pytest

from tests.unit.conftest import make_org
from unstructured_mapping.cli import audit_aliases
from unstructured_mapping.cli.audit_aliases import (
    ScoredCollision,
    ScoredEntity,
    _apply_merges,
    score_collisions,
)
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
    Provenance,
)
from unstructured_mapping.knowledge_graph.validation import (
    find_alias_collisions,
)


def _add_mentions(
    store: KnowledgeStore,
    entity_id: str,
    n: int,
) -> None:
    detected = datetime.now(timezone.utc)
    store.save_provenances(
        [
            Provenance(
                entity_id=entity_id,
                document_id=f"doc-{entity_id}-{i}",
                source="test",
                mention_text="x",
                context_snippet="x",
                detected_at=detected,
            )
            for i in range(n)
        ]
    )


# -- score_collisions ------------------------------------


def test_score_collisions_ranks_by_total_mentions(
    tmp_path,
):
    """Scored collisions come back ordered by total
    mention prevalence — highest-signal duplicates first.
    """
    db = tmp_path / "kg.db"
    hot_a = make_org(
        "Alpha Corp",
        aliases=("Alpha",),
        entity_id="hot_a",
    )
    hot_b = make_org(
        "Alpha Holdings",
        aliases=("Alpha",),
        entity_id="hot_b",
    )
    cold_a = make_org(
        "Beta Inc",
        aliases=("Beta",),
        entity_id="cold_a",
    )
    cold_b = make_org(
        "Beta LLC",
        aliases=("Beta",),
        entity_id="cold_b",
    )
    with KnowledgeStore(db_path=db) as store:
        for e in (hot_a, hot_b, cold_a, cold_b):
            store.save_entity(e)
        _add_mentions(store, "hot_a", 5)
        _add_mentions(store, "hot_b", 3)
        _add_mentions(store, "cold_a", 1)
        raw = find_alias_collisions(store._conn)
        ranked = score_collisions(store, raw)
    assert [c.alias.lower() for c in ranked] == [
        "alpha",
        "beta",
    ]
    top = ranked[0]
    assert top.total_mentions == 8
    # Entities within a collision are sorted by mentions
    # desc, so the merge target is first.
    assert top.entities[0].entity_id == "hot_a"


def test_merge_target_only_for_same_type():
    same = ScoredCollision(
        alias="Apple",
        entities=(
            ScoredEntity(
                entity_id="a",
                canonical_name="Apple Inc",
                entity_type="organization",
                mention_count=10,
            ),
            ScoredEntity(
                entity_id="b",
                canonical_name="Apple Corps",
                entity_type="organization",
                mention_count=3,
            ),
        ),
    )
    cross = ScoredCollision(
        alias="Apple",
        entities=(
            ScoredEntity(
                entity_id="a",
                canonical_name="Apple Inc",
                entity_type="organization",
                mention_count=10,
            ),
            ScoredEntity(
                entity_id="b",
                canonical_name="Apple (product)",
                entity_type="product",
                mention_count=3,
            ),
        ),
    )
    assert same.same_type is True
    assert same.merge_target is not None
    assert same.merge_target.entity_id == "a"
    assert cross.same_type is False
    assert cross.merge_target is None


# -- _apply_merges ---------------------------------------


def test_apply_merges_same_type_with_auto_confirm(
    tmp_path,
):
    """Same-type collisions merge losers into the
    highest-mention entity; cross-type rows are skipped
    entirely."""
    db = tmp_path / "kg.db"
    keep = make_org(
        "Alpha Corp",
        aliases=("Alpha",),
        entity_id="keep",
    )
    drop = make_org(
        "Alpha Holdings",
        aliases=("Alpha",),
        entity_id="drop",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(keep)
        store.save_entity(drop)
        _add_mentions(store, "keep", 5)
        _add_mentions(store, "drop", 2)
        raw = find_alias_collisions(store._conn)
        scored = score_collisions(store, raw)
        merged = _apply_merges(store, scored, auto_confirm=True)
        assert merged == 1
        dropped = store.get_entity("drop")
        assert dropped is not None
        assert dropped.status.value == "merged"
        assert dropped.merged_into == "keep"


def test_apply_merges_prompts_without_auto_confirm(tmp_path, monkeypatch):
    """Without --auto-confirm the CLI asks the operator;
    answering anything other than 'y' skips the merge."""
    db = tmp_path / "kg.db"
    keep = make_org(
        "Alpha Corp",
        aliases=("Alpha",),
        entity_id="keep",
    )
    drop = make_org(
        "Alpha Holdings",
        aliases=("Alpha",),
        entity_id="drop",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(keep)
        store.save_entity(drop)
        _add_mentions(store, "keep", 5)
        _add_mentions(store, "drop", 2)
        raw = find_alias_collisions(store._conn)
        scored = score_collisions(store, raw)

        # Say "no" — nothing should merge.
        monkeypatch.setattr(
            audit_aliases,
            "_confirm",
            lambda prompt: False,
        )
        assert _apply_merges(store, scored, auto_confirm=False) == 0
        still = store.get_entity("drop")
        assert still is not None
        assert still.status.value == "active"


def test_apply_merges_skips_cross_type_collisions(
    tmp_path,
):
    """Cross-type collisions are never merged
    automatically — those are real duplicates only if a
    human confirms, and the CLI refuses to propose them.
    """
    db = tmp_path / "kg.db"
    from unstructured_mapping.knowledge_graph import (
        Entity,
        EntityType,
    )

    org = Entity(
        canonical_name="Apple Inc",
        entity_type=EntityType.ORGANIZATION,
        description="x",
        aliases=("Apple",),
        entity_id="org",
    )
    product = Entity(
        canonical_name="Apple (iPhone)",
        entity_type=EntityType.PRODUCT,
        description="x",
        aliases=("Apple",),
        entity_id="product",
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(org)
        store.save_entity(product)
        raw = find_alias_collisions(store._conn)
        scored = score_collisions(store, raw)
        merged = _apply_merges(store, scored, auto_confirm=True)
        assert merged == 0
        for eid in ("org", "product"):
            entity = store.get_entity(eid)
            assert entity is not None
            assert entity.status.value == "active"


def test_main_auto_confirm_requires_apply(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db):
        pass
    with pytest.raises(SystemExit):
        audit_aliases.main(
            [
                "--db",
                str(db),
                "--auto-confirm",
            ]
        )
