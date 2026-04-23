"""Tests for ``cli.validate_snapshot``.

Covers the two modes (``--record`` / ``--check``), the
snapshot schema roundtrip, and the two threshold gates
(entity drop + collision increase).
"""

import json

import pytest

from unstructured_mapping.cli.validate_snapshot import (
    SCHEMA_VERSION,
    CollisionSummary,
    Snapshot,
    capture_snapshot,
    compare_snapshots,
    load_snapshot,
    main,
    write_snapshot,
)
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
    Provenance,
    Relationship,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityType,
)

from .conftest import make_entity


@pytest.fixture
def kg_with_shape(tmp_path):
    """Three entities (two orgs sharing an alias, one
    person), one relationship, four provenance rows.

    The shared alias gives us a guaranteed collision to
    assert on; the per-type/subtype split exercises the
    nested count dict."""
    db = tmp_path / "kg.db"
    apple = make_entity(
        canonical_name="Apple",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
        aliases=("Orchard",),
    )
    apple_fruit = make_entity(
        canonical_name="Apple Inc Fruit Div",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
        aliases=("Orchard",),
    )
    powell = make_entity(
        canonical_name="Powell",
        entity_type=EntityType.PERSON,
        subtype="policymaker",
    )
    with KnowledgeStore(db_path=db) as store:
        for e in (apple, apple_fruit, powell):
            store.save_entity(e)
        store.save_relationship(
            Relationship(
                source_id=apple.entity_id,
                target_id=powell.entity_id,
                relation_type="met_with",
                description="ctx",
            )
        )
        for entity, doc_count in (
            (apple, 2),
            (apple_fruit, 1),
            (powell, 1),
        ):
            for i in range(doc_count):
                store.save_provenance(
                    Provenance(
                        entity_id=entity.entity_id,
                        document_id=f"doc-{entity.entity_id[:6]}-{i}",
                        source="t",
                        mention_text=entity.canonical_name,
                        context_snippet="ctx",
                    )
                )
    return db


def test_capture_snapshot_totals(kg_with_shape):
    with KnowledgeStore(db_path=kg_with_shape) as store:
        snap = capture_snapshot(store)
    assert snap.total_entities == 3
    assert snap.total_relationships == 1
    assert snap.total_provenance == 4
    assert snap.provenance_density == pytest.approx(4 / 3)


def test_capture_snapshot_counts_by_type(kg_with_shape):
    with KnowledgeStore(db_path=kg_with_shape) as store:
        snap = capture_snapshot(store)
    assert snap.counts_by_type["organization"] == 2
    assert snap.counts_by_type["person"] == 1


def test_capture_snapshot_counts_by_type_subtype(kg_with_shape):
    with KnowledgeStore(db_path=kg_with_shape) as store:
        snap = capture_snapshot(store)
    assert snap.counts_by_type_subtype["organization"]["company"] == 2
    assert snap.counts_by_type_subtype["person"]["policymaker"] == 1


def test_capture_snapshot_records_top_collision(kg_with_shape):
    with KnowledgeStore(db_path=kg_with_shape) as store:
        snap = capture_snapshot(store)
    assert snap.alias_collision_count == 1
    assert len(snap.top_collisions) == 1
    top = snap.top_collisions[0]
    # Aliases are stored case-folded by the KG layer.
    assert top.alias.lower() == "orchard"
    assert top.entity_count == 2
    assert top.entity_types == ("organization",)


def test_snapshot_roundtrip_via_disk(tmp_path, kg_with_shape):
    path = tmp_path / "snap.json"
    with KnowledgeStore(db_path=kg_with_shape) as store:
        snap = capture_snapshot(store)
    write_snapshot(snap, path)
    loaded = load_snapshot(path)
    assert loaded.total_entities == snap.total_entities
    assert loaded.counts_by_type == snap.counts_by_type
    assert loaded.counts_by_type_subtype == snap.counts_by_type_subtype
    assert loaded.top_collisions == snap.top_collisions
    assert loaded.alias_collision_count == snap.alias_collision_count


def test_snapshot_wrong_schema_version_raises(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(
        json.dumps(
            {
                "recorded_at": "2026-04-24T00:00:00+00:00",
                "schema_version": 99,
                "total_entities": 0,
                "total_relationships": 0,
                "total_provenance": 0,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema_version"):
        load_snapshot(path)


def _make_snapshot(
    *,
    total_entities: int = 100,
    total_relationships: int = 50,
    total_provenance: int = 200,
    counts_by_type: dict[str, int] | None = None,
    collisions: int = 0,
) -> Snapshot:
    return Snapshot(
        recorded_at="2026-04-24T00:00:00+00:00",
        schema_version=SCHEMA_VERSION,
        total_entities=total_entities,
        total_relationships=total_relationships,
        total_provenance=total_provenance,
        counts_by_type=counts_by_type or {"organization": total_entities},
        counts_by_type_subtype={},
        alias_collision_count=collisions,
        top_collisions=(),
    )


def test_compare_passes_when_unchanged():
    snap = _make_snapshot()
    result = compare_snapshots(snap, snap)
    assert result.passed
    assert result.breaches == ()


def test_compare_passes_on_growth():
    baseline = _make_snapshot(total_entities=100)
    current = _make_snapshot(total_entities=120)
    result = compare_snapshots(baseline, current)
    assert result.passed


def test_compare_fails_on_entity_drop_beyond_threshold():
    baseline = _make_snapshot(total_entities=100)
    current = _make_snapshot(total_entities=80)  # 20% drop
    result = compare_snapshots(baseline, current, max_entity_drop_pct=10.0)
    assert not result.passed
    assert any("entity drop" in b for b in result.breaches)


def test_compare_passes_when_drop_within_threshold():
    baseline = _make_snapshot(total_entities=100)
    current = _make_snapshot(total_entities=95)  # 5% drop
    result = compare_snapshots(baseline, current, max_entity_drop_pct=10.0)
    assert result.passed


def test_compare_fails_on_new_alias_collisions():
    baseline = _make_snapshot(collisions=2)
    current = _make_snapshot(collisions=5)
    result = compare_snapshots(baseline, current, max_collision_increase=0)
    assert not result.passed
    assert any("alias collisions" in b for b in result.breaches)


def test_compare_passes_when_collisions_decrease():
    baseline = _make_snapshot(collisions=5)
    current = _make_snapshot(collisions=2)
    result = compare_snapshots(baseline, current)
    assert result.passed


def test_main_record_writes_file_and_prints_summary(
    kg_with_shape, tmp_path, capsys
):
    out = tmp_path / "baseline.json"
    main(
        [
            "--db",
            str(kg_with_shape),
            "--record",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert "entities=3" in captured.out
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION


def test_main_check_passes_on_identical_kg(kg_with_shape, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    main(
        [
            "--db",
            str(kg_with_shape),
            "--record",
            str(baseline),
        ]
    )
    capsys.readouterr()  # drain record output
    main(
        [
            "--db",
            str(kg_with_shape),
            "--check",
            str(baseline),
        ]
    )
    captured = capsys.readouterr()
    assert "All thresholds satisfied" in captured.out


def test_main_check_exits_nonzero_on_breach(tmp_path, kg_with_shape, capsys):
    """Record against a KG, then check against a baseline
    synthesised to have a much larger entity count so the
    current KG looks like it has collapsed."""
    baseline_path = tmp_path / "baseline.json"
    # Hand-author a baseline with inflated counts so the
    # fixture KG (3 entities) looks like a 97% drop.
    fake_baseline = _make_snapshot(total_entities=100, collisions=0)
    write_snapshot(fake_baseline, baseline_path)

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--db",
                str(kg_with_shape),
                "--check",
                str(baseline_path),
                "--max-entity-drop-pct",
                "5",
            ]
        )
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "BREACHES" in captured.out
    assert "entity drop" in captured.out


def test_main_requires_record_or_check(kg_with_shape):
    """The mutually exclusive group is marked required,
    so argparse should raise when neither is supplied."""
    with pytest.raises(SystemExit):
        main(["--db", str(kg_with_shape)])


def test_collision_summary_roundtrip_via_dict():
    """JSON round-trip must preserve the tuple-of-str
    ``entity_types`` even though JSON serialises it as
    a list."""
    snap = Snapshot(
        recorded_at="2026-04-24T00:00:00+00:00",
        schema_version=SCHEMA_VERSION,
        total_entities=1,
        total_relationships=0,
        total_provenance=0,
        counts_by_type={"organization": 1},
        counts_by_type_subtype={"organization": {"company": 1}},
        alias_collision_count=1,
        top_collisions=(
            CollisionSummary(
                alias="X",
                entity_count=2,
                entity_types=("organization", "product"),
            ),
        ),
    )
    restored = Snapshot.from_dict(snap.to_dict())
    assert restored.top_collisions[0].entity_types == (
        "organization",
        "product",
    )
