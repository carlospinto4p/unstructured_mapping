"""Tests for the ``cli.run_report`` CLI.

Builds a run end-to-end (save_run → save_provenance /
save_relationship → finish_run → save_run_metrics) against
a real KG so every rendered section has something to
show. Also covers the "no metrics" fallback for pre-
scorecard runs and the failed-run banner.
"""

import pytest

from unstructured_mapping.cli.run_report import main, report_run
from unstructured_mapping.knowledge_graph import (
    IngestionRun,
    KnowledgeStore,
    Provenance,
    Relationship,
    RunStatus,
)
from unstructured_mapping.knowledge_graph.models import (
    RunMetrics,
)

from .conftest import make_entity


def _wire_run(
    store: KnowledgeStore,
    run: IngestionRun,
    entity_ids: list[str],
    relationships: list[Relationship],
) -> None:
    store.save_run(run)
    for eid in entity_ids:
        store.save_provenance(
            Provenance(
                entity_id=eid,
                document_id=f"doc-{eid[:8]}",
                source="t",
                mention_text=eid[:4],
                context_snippet="ctx",
                run_id=run.run_id,
            )
        )
    for rel in relationships:
        store.save_relationship(rel)


@pytest.fixture
def populated_run(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    a = make_entity(canonical_name="A")
    b = make_entity(canonical_name="B")
    rel = Relationship(
        source_id=a.entity_id,
        target_id=b.entity_id,
        relation_type="mentions",
        description="ctx",
        run_id=run.run_id,
    )
    metrics = RunMetrics(
        run_id=run.run_id,
        chunks_processed=4,
        mentions_detected=15,
        mentions_resolved_alias=10,
        mentions_resolved_llm=5,
        llm_resolver_calls=2,
        llm_extractor_calls=3,
        proposals_saved=1,
        relationships_saved=1,
        provider_name="ollama",
        model_name="llama3.1:8b",
        wall_clock_seconds=42.5,
        input_tokens=1200,
        output_tokens=350,
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(a)
        store.save_entity(b)
        _wire_run(
            store,
            run,
            entity_ids=[a.entity_id, b.entity_id],
            relationships=[rel],
        )
        store.finish_run(
            run.run_id,
            status=RunStatus.COMPLETED,
            document_count=2,
            entity_count=2,
            relationship_count=1,
        )
        store.save_run_metrics(metrics)
    return db, run.run_id


def test_report_run_renders_every_section(populated_run):
    db, run_id = populated_run
    with KnowledgeStore(db_path=db) as store:
        report = report_run(store, run_id)

    assert "status:         completed" in report
    assert "documents:      2" in report
    assert "distinct ents:  2" in report
    assert "distinct rels:  1" in report
    assert "provider:       ollama" in report
    assert "tokens:         in=1200" in report
    assert "total=1550" in report
    assert "wall clock:     42.5s" in report


def test_report_run_falls_back_when_no_metrics_saved(tmp_path):
    """Legacy runs without a RunMetrics row still render —
    the scorecard section just says there's no data.
    """
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.finish_run(run.run_id, status=RunStatus.COMPLETED)
        report = report_run(store, run.run_id)

    assert "no RunMetrics row" in report
    # No metrics means we fall back to finished - started
    # for the wall clock readout (tiny number; just ensure
    # the field exists).
    assert "wall clock:" in report


def test_report_run_flags_failed_runs(tmp_path):
    db = tmp_path / "kg.db"
    run = IngestionRun()
    with KnowledgeStore(db_path=db) as store:
        store.save_run(run)
        store.finish_run(
            run.run_id,
            status=RunStatus.FAILED,
            error_message="Boom",
        )
        report = report_run(store, run.run_id)

    assert "THIS RUN FAILED" in report
    assert "error:          Boom" in report


def test_report_run_raises_for_missing_run(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(SystemExit, match="not found"):
            report_run(store, "nope")


def test_main_prints_report_to_stdout(populated_run, capsys):
    db, run_id = populated_run
    main(["--db", str(db), "--run", run_id])
    captured = capsys.readouterr()
    assert "Scorecard" in captured.out
    assert "Counts" in captured.out
