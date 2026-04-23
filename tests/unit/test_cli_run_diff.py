"""Tests for the ``cli.run_diff`` CLI.

Builds two real runs against an in-process KG so the diff
renders against realistic data, then asserts the headline
numbers and set-delta summaries are correct. The formatter
itself is exercised via :func:`diff_runs` — the ``main``
entry point is covered by one golden-path smoke test.
"""

import pytest

from unstructured_mapping.cli.run_diff import diff_runs, main
from unstructured_mapping.knowledge_graph import (
    IngestionRun,
    KnowledgeStore,
    Provenance,
    Relationship,
    RunStatus,
)

from .conftest import make_entity


def _populate(
    store: KnowledgeStore,
    run: IngestionRun,
    *,
    entity_ids: list[str],
    relationships: list[Relationship],
) -> None:
    """Persist a run and tag ``entity_ids`` / rels to it."""
    store.save_run(run)
    for eid in entity_ids:
        store.save_provenance(
            Provenance(
                entity_id=eid,
                document_id=f"doc-{run.run_id[:6]}-{eid[:6]}",
                source="t",
                mention_text=eid[:4],
                context_snippet="ctx",
                run_id=run.run_id,
            )
        )
    for rel in relationships:
        store.save_relationship(rel)
    store.finish_run(
        run.run_id,
        status=RunStatus.COMPLETED,
        document_count=len(entity_ids),
        entity_count=len(entity_ids),
        relationship_count=len(relationships),
    )


def _make_relationship(
    src: str, tgt: str, rel_type: str, run_id: str
) -> Relationship:
    return Relationship(
        source_id=src,
        target_id=tgt,
        relation_type=rel_type,
        description="ctx",
        run_id=run_id,
    )


@pytest.fixture
def two_runs(tmp_path):
    """Populate a KG with two runs whose entity / rel
    footprints partially overlap so every branch of the
    diff report has something to render.
    """
    db = tmp_path / "kg.db"
    shared_a = make_entity(canonical_name="Shared A")
    shared_b = make_entity(canonical_name="Shared B")
    only_base = make_entity(canonical_name="Only Base")
    only_head = make_entity(canonical_name="Only Head")
    base_run = IngestionRun()
    head_run = IngestionRun()

    with KnowledgeStore(db_path=db) as store:
        for e in (shared_a, shared_b, only_base, only_head):
            store.save_entity(e)
        _populate(
            store,
            base_run,
            entity_ids=[
                shared_a.entity_id,
                shared_b.entity_id,
                only_base.entity_id,
            ],
            relationships=[
                _make_relationship(
                    shared_a.entity_id,
                    shared_b.entity_id,
                    "mentions_with",
                    base_run.run_id,
                ),
                _make_relationship(
                    shared_a.entity_id,
                    only_base.entity_id,
                    "cites",
                    base_run.run_id,
                ),
            ],
        )
        _populate(
            store,
            head_run,
            entity_ids=[
                shared_a.entity_id,
                shared_b.entity_id,
                only_head.entity_id,
            ],
            relationships=[
                _make_relationship(
                    shared_a.entity_id,
                    shared_b.entity_id,
                    "mentions_with",
                    head_run.run_id,
                ),
                _make_relationship(
                    shared_a.entity_id,
                    only_head.entity_id,
                    "links",
                    head_run.run_id,
                ),
            ],
        )
    return (
        db,
        base_run.run_id,
        head_run.run_id,
        {
            "shared_a": shared_a,
            "shared_b": shared_b,
            "only_base": only_base,
            "only_head": only_head,
        },
    )


def test_diff_runs_reports_entity_and_relationship_deltas(two_runs):
    db, base_id, head_id, ents = two_runs
    with KnowledgeStore(db_path=db) as store:
        report = diff_runs(store, base_run_id=base_id, head_run_id=head_id)

    assert "BASE" in report
    assert "HEAD" in report
    assert "only in base:  1" in report  # only_base
    assert "only in head:  1" in report  # only_head
    assert "in both:       2" in report  # shared_a + shared_b
    # Relationship delta: one shared, one unique to each run.
    assert "Relationships" in report
    assert ents["only_base"].canonical_name in report
    assert ents["only_head"].canonical_name in report


def test_diff_runs_deltas_only_hides_headlines(two_runs):
    db, base_id, head_id, _ = two_runs
    with KnowledgeStore(db_path=db) as store:
        report = diff_runs(
            store,
            base_run_id=base_id,
            head_run_id=head_id,
            deltas_only=True,
        )

    assert "BASE" not in report
    assert "HEAD" not in report
    assert "Entities" in report
    assert "Relationships" in report


def test_diff_runs_raises_when_run_missing(two_runs):
    db, base_id, _, _ = two_runs
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(SystemExit, match="not found"):
            diff_runs(store, base_run_id=base_id, head_run_id="nope")


def test_main_prints_report_to_stdout(two_runs, capsys):
    db, base_id, head_id, _ = two_runs
    main(
        [
            "--db",
            str(db),
            "--base",
            base_id,
            "--head",
            head_id,
        ]
    )
    captured = capsys.readouterr()
    assert "Entities" in captured.out
    assert "Relationships" in captured.out
