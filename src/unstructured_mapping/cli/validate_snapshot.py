"""Record and check KG quality snapshots for CI gating.

Thin CLI wrapper over :mod:`knowledge_graph.snapshot` —
the data model, capture, comparison, and on-disk
serialisation all live there so future tooling (drift
checks between two live KGs, dashboards, LLM context
blocks) can reuse the same primitives without importing
from a CLI module.

Two modes:

- ``--record <path>``: capture a structured summary of
  the current KG (counts by type / subtype, top-K alias
  collisions, provenance density) and write it to a JSON
  file. The file is committable — it serves as the
  golden baseline for future runs.
- ``--check <baseline>``: capture the current KG, load
  the baseline, and emit a textual report of every
  metric that moved. Exits non-zero when a threshold
  is breached; zero otherwise.

Thresholds are kept small on purpose so CI wiring is
trivial. Two knobs cover the common failure modes:

- ``--max-entity-drop-pct``: maximum allowed drop in
  total entity count, expressed as a percentage of the
  baseline. Defaults to 10, i.e. "fail if the KG lost
  more than 10% of its entities".
- ``--max-collision-increase``: maximum allowed
  *increase* in alias collisions (absolute count).
  Defaults to 0, i.e. "any new collision is a
  regression worth inspecting".

Both modes print a human-readable report so the same
tool works as a CI gate and as an interactive "did my
change blow up quality?" check.

Usage::

    # Record a baseline after a known-good run:
    uv run python -m unstructured_mapping.cli.validate_snapshot \\
        --db data/knowledge.db \\
        --record snapshots/baseline.json

    # Check a live KG against it (CI):
    uv run python -m unstructured_mapping.cli.validate_snapshot \\
        --db data/knowledge.db \\
        --check snapshots/baseline.json \\
        --max-entity-drop-pct 5
"""

import argparse
import logging
import sys
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
)
from unstructured_mapping.cli._runner import run_cli_with_kg
from unstructured_mapping.knowledge_graph import KnowledgeStore
from unstructured_mapping.knowledge_graph.snapshot import (
    DEFAULT_TOP_K_COLLISIONS,
    SCHEMA_VERSION,
    CheckResult,
    CollisionSummary,
    Snapshot,
    capture_snapshot,
    compare_snapshots,
    load_snapshot,
    write_snapshot,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Record and compare KG quality snapshots. "
            "Useful as a CI gate against accidental "
            "regressions (entity loss, new alias "
            "collisions)."
        ),
    )
    add_db_argument(p, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--record",
        type=Path,
        metavar="PATH",
        help="Capture a snapshot and write it to PATH.",
    )
    mode.add_argument(
        "--check",
        type=Path,
        metavar="BASELINE",
        help=(
            "Capture the current KG and compare it to "
            "the baseline JSON at BASELINE. Non-zero "
            "exit on threshold breach."
        ),
    )
    p.add_argument(
        "--max-entity-drop-pct",
        type=float,
        default=10.0,
        help=(
            "Fail --check when entity count drops by "
            "more than this percentage (default: 10)."
        ),
    )
    p.add_argument(
        "--max-collision-increase",
        type=int,
        default=0,
        help=(
            "Fail --check when alias collisions grow by "
            "more than this absolute count "
            "(default: 0)."
        ),
    )
    p.add_argument(
        "--top-k-collisions",
        type=int,
        default=DEFAULT_TOP_K_COLLISIONS,
        help=(
            "Number of alias collisions to record in "
            "the snapshot (default: "
            f"{DEFAULT_TOP_K_COLLISIONS})."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    def _body(store: KnowledgeStore, args: argparse.Namespace) -> None:
        snapshot = capture_snapshot(
            store, top_k_collisions=args.top_k_collisions
        )
        if args.record is not None:
            write_snapshot(snapshot, args.record)
            sys.stdout.write(
                f"Recorded snapshot to {args.record}: "
                f"entities={snapshot.total_entities} "
                f"relationships={snapshot.total_relationships} "
                f"collisions={snapshot.alias_collision_count}\n"
            )
            return
        baseline = load_snapshot(args.check)
        result = compare_snapshots(
            baseline,
            snapshot,
            max_entity_drop_pct=args.max_entity_drop_pct,
            max_collision_increase=args.max_collision_increase,
        )
        sys.stdout.write(result.report + "\n")
        if not result.passed:
            raise SystemExit(1)

    run_cli_with_kg(_build_parser, _body, argv)


if __name__ == "__main__":
    main()


# Re-exports for back-compat. Tests and external callers
# importing from ``cli.validate_snapshot`` keep working
# without churn; new code should import from
# :mod:`unstructured_mapping.knowledge_graph.snapshot`.
__all__ = [
    "CheckResult",
    "CollisionSummary",
    "DEFAULT_TOP_K_COLLISIONS",
    "SCHEMA_VERSION",
    "Snapshot",
    "capture_snapshot",
    "compare_snapshots",
    "load_snapshot",
    "main",
    "write_snapshot",
]
