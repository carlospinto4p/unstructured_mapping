"""Diff two ingestion runs — what changed between A and B.

Every provenance row and every relationship already carries
its originating ``run_id``; this CLI joins those foreign
keys against :class:`IngestionRun` / :class:`RunMetrics` so
a reviewer can tell at a glance what the newer run
contributed over the older one.

Two kinds of comparison are produced:

1. **Per-run headline numbers** — status, wall time, token
   usage, distinct entities touched, relationships
   created. Pulled directly from ``ingestion_runs`` +
   ``run_metrics``.
2. **Set deltas** — entities and relationships present in
   only one run vs. both. Uses
   :meth:`KnowledgeStore.get_entities_touched_by_run` and
   :meth:`KnowledgeStore.get_relationship_keys_for_run`.

The CLI is read-only — it never mutates the KG. Useful for
iterating on seed data, LLM prompts, or provider swaps
because a rerun's outcomes can be diffed against a known-
good baseline without hand-rolled SQL.

Usage::

    uv run python -m unstructured_mapping.cli.run_diff \\
        --db data/knowledge.db \\
        --base <run_a_id> --head <run_b_id>

    # Print only the set deltas (skip the headlines):
    uv run python -m unstructured_mapping.cli.run_diff \\
        --db data/knowledge.db \\
        --base <run_a_id> --head <run_b_id> \\
        --deltas-only
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
)

logger = logging.getLogger(__name__)

#: Upper bound on sample rows per section. Diffs between
#: noisy runs can drop thousands of ids; printing them all
#: is noise, not signal.
_SAMPLE_LIMIT = 15


def _load_run(
    store: KnowledgeStore, run_id: str
) -> tuple[IngestionRun, RunMetrics | None]:
    """Fetch a run + metrics, raising if the run is missing.

    :param store: Target knowledge store.
    :param run_id: Run identifier.
    :return: Tuple of the run record and its metrics
        scorecard (``None`` when no metrics were saved —
        typical for older runs before :class:`RunMetrics`
        landed).
    :raises SystemExit: If the run is not present.
    """
    run = store.get_run(run_id)
    if run is None:
        raise SystemExit(f"error: run {run_id!r} not found in {store!r}")
    metrics = store.get_run_metrics(run_id)
    return run, metrics


def _format_run_headline(
    label: str,
    run: IngestionRun,
    metrics: RunMetrics | None,
    entities_touched: int,
    relationships_created: int,
) -> str:
    """Render a readable summary block for one run."""
    lines: list[str] = [f"{label}  {run.run_id[:12]}"]
    lines.append(f"  status:           {run.status.value}")
    lines.append(f"  started_at:       {run.started_at.isoformat()}")
    if run.finished_at is not None:
        lines.append(f"  finished_at:      {run.finished_at.isoformat()}")
    lines.append(f"  documents:        {run.document_count}")
    lines.append(f"  provenance rows:  {run.entity_count}")
    lines.append(f"  relationships:    {run.relationship_count}")
    lines.append(f"  distinct ents:    {entities_touched}")
    lines.append(f"  distinct rels:    {relationships_created}")
    if metrics is not None:
        lines.append(
            f"  LLM calls:        resolver={metrics.llm_resolver_calls}"
            f"  extractor={metrics.llm_extractor_calls}"
        )
        lines.append(
            f"  tokens:           in={metrics.input_tokens}"
            f"  out={metrics.output_tokens}"
        )
        if metrics.wall_clock_seconds:
            lines.append(
                f"  wall clock:       {metrics.wall_clock_seconds:.1f}s"
            )
    if run.error_message:
        lines.append(f"  error:            {run.error_message}")
    return "\n".join(lines)


def _format_sample(label: str, items: list[str]) -> str:
    """Render a bounded sample list, skipping when empty."""
    if not items:
        return f"  {label}: (none)"
    shown = items[:_SAMPLE_LIMIT]
    suffix = (
        f" (+{len(items) - _SAMPLE_LIMIT} more)"
        if len(items) > _SAMPLE_LIMIT
        else ""
    )
    body = ", ".join(shown)
    return f"  {label}:\n    {body}{suffix}"


def _format_entity_deltas(
    store: KnowledgeStore,
    only_base: set[str],
    only_head: set[str],
    both: set[str],
) -> str:
    """Summarise the entity set-diff plus canonical-name
    samples for the two "only" buckets."""
    lines = [
        "Entities (distinct entity_ids with provenance):",
        f"  only in base:  {len(only_base)}",
        f"  only in head:  {len(only_head)}",
        f"  in both:       {len(both)}",
    ]
    # Hydrate canonical names for the samples so the
    # output is readable; fetch in one batch per bucket.
    for label, bucket in (
        ("only-in-base names", sorted(only_base)[:_SAMPLE_LIMIT]),
        ("only-in-head names", sorted(only_head)[:_SAMPLE_LIMIT]),
    ):
        if not bucket:
            continue
        lookups = store.get_entities(bucket)
        names = [
            lookups[eid].canonical_name for eid in bucket if eid in lookups
        ]
        lines.append(_format_sample(label, names))
    return "\n".join(lines)


def _format_relationship_deltas(
    only_base: set[tuple[str, str, str]],
    only_head: set[tuple[str, str, str]],
    both: set[tuple[str, str, str]],
) -> str:
    """Summarise the relationship set-diff + key samples."""
    lines = [
        "Relationships (source, target, type):",
        f"  only in base:  {len(only_base)}",
        f"  only in head:  {len(only_head)}",
        f"  in both:       {len(both)}",
    ]
    for label, bucket in (
        ("only-in-base keys", sorted(only_base)[:_SAMPLE_LIMIT]),
        ("only-in-head keys", sorted(only_head)[:_SAMPLE_LIMIT]),
    ):
        if not bucket:
            continue
        rendered = [f"{src[:8]}->{tgt[:8]} {rel}" for src, tgt, rel in bucket]
        lines.append(_format_sample(label, rendered))
    return "\n".join(lines)


def diff_runs(
    store: KnowledgeStore,
    *,
    base_run_id: str,
    head_run_id: str,
    deltas_only: bool = False,
) -> str:
    """Produce the full diff report as a single string.

    :param store: KG store containing both runs.
    :param base_run_id: Baseline (older) run identifier.
    :param head_run_id: Comparison (newer) run identifier.
    :param deltas_only: Skip the per-run headline blocks
        and print only the set deltas.
    :return: Multi-line textual report.
    """
    base_run, base_metrics = _load_run(store, base_run_id)
    head_run, head_metrics = _load_run(store, head_run_id)

    base_entities = store.get_entities_touched_by_run(base_run_id)
    head_entities = store.get_entities_touched_by_run(head_run_id)
    only_base_e = base_entities - head_entities
    only_head_e = head_entities - base_entities
    both_e = base_entities & head_entities

    base_rels = store.get_relationship_keys_for_run(base_run_id)
    head_rels = store.get_relationship_keys_for_run(head_run_id)
    only_base_r = base_rels - head_rels
    only_head_r = head_rels - base_rels
    both_r = base_rels & head_rels

    sections: list[str] = []
    if not deltas_only:
        sections.append(
            _format_run_headline(
                "BASE",
                base_run,
                base_metrics,
                len(base_entities),
                len(base_rels),
            )
        )
        sections.append(
            _format_run_headline(
                "HEAD",
                head_run,
                head_metrics,
                len(head_entities),
                len(head_rels),
            )
        )
    sections.append(
        _format_entity_deltas(store, only_base_e, only_head_e, both_e)
    )
    sections.append(
        _format_relationship_deltas(only_base_r, only_head_r, both_r)
    )
    return "\n\n".join(sections)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Diff two ingestion runs: per-run summaries "
            "plus the entity / relationship set deltas."
        ),
    )
    add_db_argument(p, required=True)
    p.add_argument(
        "--base",
        required=True,
        help="Baseline (older) run_id.",
    )
    p.add_argument(
        "--head",
        required=True,
        help="Comparison (newer) run_id.",
    )
    p.add_argument(
        "--deltas-only",
        action="store_true",
        help=("Skip the per-run headline blocks; print only the set deltas."),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _build_parser().parse_args(argv)
    with open_kg_store(args.db) as store:
        report = diff_runs(
            store,
            base_run_id=args.base,
            head_run_id=args.head,
            deltas_only=args.deltas_only,
        )
    sys.stdout.write(report + "\n")


if __name__ == "__main__":
    main()


__all__ = [
    "diff_runs",
    "main",
]
