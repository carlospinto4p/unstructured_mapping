"""Per-run ingestion report — one scorecard per ``run_id``.

Reads :class:`IngestionRun` and :class:`RunMetrics` for a
single run and renders a readable summary: run lifecycle
(status, started / finished, wall time, error), aggregate
counters (documents, provenance rows, relationships), the
LLM scorecard (calls, tokens, provider / model), and the
distinct entity / relationship footprints derived from the
``run_id`` foreign keys on provenance and relationships.

Pairs with :mod:`cli.run_diff`: use this to audit one run
end-to-end, then the diff CLI to compare it against a
baseline.

Usage::

    uv run python -m unstructured_mapping.cli.run_report \\
        --db data/knowledge.db --run <run_id>
"""

import argparse
import logging
import sys

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
)
from unstructured_mapping.cli._db_helpers import open_kg_store
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.models import (
    IngestionRun,
    RunMetrics,
    RunStatus,
)

logger = logging.getLogger(__name__)


def _fmt_duration(run: IngestionRun, metrics: RunMetrics | None) -> str:
    """Render the wall time for the run.

    ``RunMetrics.wall_clock_seconds`` is authoritative when
    available; otherwise we fall back to ``finished_at -
    started_at`` so legacy runs without metrics still render
    a duration. Runs still ``RUNNING`` report ``(in progress)``.
    """
    if metrics is not None and metrics.wall_clock_seconds:
        return f"{metrics.wall_clock_seconds:.1f}s"
    if run.finished_at is None:
        return "(in progress)"
    delta = run.finished_at - run.started_at
    return f"{delta.total_seconds():.1f}s"


def _fmt_lifecycle(run: IngestionRun, metrics: RunMetrics | None) -> str:
    lines = [f"Run {run.run_id}"]
    lines.append(f"  status:         {run.status.value}")
    lines.append(f"  started_at:     {run.started_at.isoformat()}")
    if run.finished_at is not None:
        lines.append(f"  finished_at:    {run.finished_at.isoformat()}")
    lines.append(f"  wall clock:     {_fmt_duration(run, metrics)}")
    if run.error_message:
        lines.append(f"  error:          {run.error_message}")
    return "\n".join(lines)


def _fmt_aggregates(
    run: IngestionRun,
    distinct_entities: int,
    distinct_rels: int,
) -> str:
    lines = ["Counts"]
    lines.append(f"  documents:      {run.document_count}")
    lines.append(f"  provenance rows: {run.entity_count}")
    lines.append(f"  relationships:  {run.relationship_count}")
    lines.append(f"  distinct ents:  {distinct_entities}")
    lines.append(f"  distinct rels:  {distinct_rels}")
    return "\n".join(lines)


def _fmt_scorecard(metrics: RunMetrics | None) -> str:
    if metrics is None:
        return (
            "Scorecard\n"
            "  (no RunMetrics row for this run — possibly "
            "an older pre-scorecard run)"
        )
    lines = ["Scorecard"]
    lines.append(f"  provider:       {metrics.provider_name or '(none)'}")
    lines.append(f"  model:          {metrics.model_name or '(none)'}")
    lines.append(f"  chunks:         {metrics.chunks_processed}")
    lines.append(
        f"  mentions:       detected={metrics.mentions_detected}"
        f"  alias={metrics.mentions_resolved_alias}"
        f"  llm={metrics.mentions_resolved_llm}"
    )
    lines.append(
        f"  LLM calls:      resolver={metrics.llm_resolver_calls}"
        f"  extractor={metrics.llm_extractor_calls}"
    )
    lines.append(
        f"  tokens:         in={metrics.input_tokens}"
        f"  out={metrics.output_tokens}"
        f"  total={metrics.total_tokens}"
    )
    lines.append(f"  proposals saved:    {metrics.proposals_saved}")
    lines.append(f"  relationships saved: {metrics.relationships_saved}")
    return "\n".join(lines)


def report_run(store: KnowledgeStore, run_id: str) -> str:
    """Render the full per-run report as one string.

    :raises SystemExit: If the run does not exist. Mirrors
        the ``run_diff`` CLI's "fail fast" behaviour rather
        than returning a partial report.
    """
    run = store.get_run(run_id)
    if run is None:
        raise SystemExit(f"error: run {run_id!r} not found")
    metrics = store.get_run_metrics(run_id)
    distinct_entities = len(store.find_entities_touched_by_run(run_id))
    distinct_rels = len(store.find_relationship_keys_for_run(run_id))
    sections = [
        _fmt_lifecycle(run, metrics),
        _fmt_aggregates(run, distinct_entities, distinct_rels),
        _fmt_scorecard(metrics),
    ]
    # Surface a warning banner up top when the run failed
    # so operators don't miss the failure while reading
    # counts that look fine on their own.
    if run.status is RunStatus.FAILED:
        sections.insert(0, "!!! THIS RUN FAILED — see error below !!!")
    return "\n\n".join(sections)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Per-run ingestion scorecard: lifecycle, "
            "aggregate counts, and the LLM metrics "
            "captured during the run."
        ),
    )
    add_db_argument(p, required=True)
    p.add_argument(
        "--run",
        required=True,
        help="Ingestion run_id to report on.",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _build_parser().parse_args(argv)
    with open_kg_store(args.db) as store:
        report = report_run(store, args.run)
    sys.stdout.write(report + "\n")


if __name__ == "__main__":
    main()


__all__ = [
    "main",
    "report_run",
]
