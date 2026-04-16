"""Populate the knowledge graph from all committed seed files.

Runs the curated seed first, then replays every Wikidata
snapshot under ``<seed-dir>/wikidata/`` in sorted order.
The curated seed wins on ``canonical_name`` + ``entity_type``
conflicts because it loads first; Wikidata rows that clash
with a curated entry are skipped by
:func:`cli.seed.load_seed`'s idempotent dedup.

This is the reproducibility entry point documented in
``docs/seed/reproducibility.md``: a fresh clone can rebuild
the populated KG offline in one command, without touching
Wikidata.

Usage::

    uv run python -m unstructured_mapping.cli.populate
    uv run python -m unstructured_mapping.cli.populate \\
        --seed-dir data/seed --db data/knowledge.db
    uv run python -m unstructured_mapping.cli.populate --dry-run

A per-stage summary is logged at the end:

* Stage name (``curated`` or the snapshot filename stem).
* Rows created, rows skipped, top entity-type counts.
* Total across all stages.
"""

import argparse
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
    add_dry_run_argument,
)
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.cli._seed_helpers import log_import_summary
from unstructured_mapping.cli.seed import load_seed
from unstructured_mapping.knowledge_graph import KnowledgeStore

logger = logging.getLogger(__name__)

_DEFAULT_SEED_DIR = Path("data/seed")
_CURATED_FILENAME = "financial_entities.json"
_WIKIDATA_SUBDIR = "wikidata"


@dataclass(frozen=True)
class StageReport:
    """One stage in the populate pipeline.

    :param name: Human-readable identifier (``curated`` for
        the curated seed, otherwise the snapshot filename
        stem — e.g. ``currency``).
    :param source: Path to the JSON file replayed.
    :param created: Rows written (or that would be written
        in dry-run mode).
    :param skipped: Rows dropped by the dedup check.
    :param counts: Counter keyed by ``entity_type.value``.
    """

    name: str
    source: Path
    created: int
    skipped: int
    counts: Counter


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Populate the KG from curated + Wikidata snapshot seed files."
        ),
    )
    p.add_argument(
        "--seed-dir",
        type=Path,
        default=_DEFAULT_SEED_DIR,
        help=(
            "Directory containing the curated seed file "
            f"and the ``{_WIKIDATA_SUBDIR}/`` snapshot "
            f"subdirectory (default: {_DEFAULT_SEED_DIR})."
        ),
    )
    add_db_argument(p)
    add_dry_run_argument(
        p,
        help_text=(
            "Parse and validate every seed file without "
            "writing to the database."
        ),
    )
    return p


def _stage_sources(seed_dir: Path) -> list[tuple[str, Path]]:
    """Return the ordered list of ``(stage_name, path)``
    to replay.

    Curated seed comes first so its hand-tuned descriptions
    and canonical names define entities before any
    Wikidata-sourced row can claim the same name+type.
    """
    stages: list[tuple[str, Path]] = []
    curated = seed_dir / _CURATED_FILENAME
    if curated.exists():
        stages.append(("curated", curated))

    wikidata_dir = seed_dir / _WIKIDATA_SUBDIR
    if wikidata_dir.is_dir():
        for path in sorted(wikidata_dir.glob("*.json")):
            stages.append((path.stem, path))
    return stages


def populate(
    seed_dir: Path,
    store: KnowledgeStore,
    *,
    dry_run: bool = False,
) -> list[StageReport]:
    """Replay every seed file in ``seed_dir`` into ``store``.

    :param seed_dir: Directory containing the curated seed
        and the ``wikidata/`` snapshot subdirectory.
    :param store: Target knowledge store.
    :param dry_run: When True, validate every file and
        report counts without writing.
    :return: One :class:`StageReport` per file replayed,
        in the order they ran.
    :raises FileNotFoundError: If no seed files are found
        under ``seed_dir`` — a clean checkout should always
        have at least the curated file, so an empty result
        points at a misconfigured path.
    """
    stages = _stage_sources(seed_dir)
    if not stages:
        raise FileNotFoundError(f"No seed files found under {seed_dir}")
    reports: list[StageReport] = []
    for name, path in stages:
        created, skipped, counts = load_seed(path, store, dry_run=dry_run)
        reports.append(
            StageReport(
                name=name,
                source=path,
                created=created,
                skipped=skipped,
                counts=counts,
            )
        )
    return reports


def _log_report(reports: list[StageReport], dry_run: bool) -> None:
    """Emit a per-stage and aggregate summary."""
    total_created = 0
    total_skipped = 0
    total_counts: Counter = Counter()
    suffix = " (dry run)" if dry_run else ""

    for r in reports:
        logger.info(
            "Stage %-14s %4d created, %4d skipped%s",
            r.name,
            r.created,
            r.skipped,
            suffix,
        )
        total_created += r.created
        total_skipped += r.skipped
        total_counts.update(r.counts)

    log_import_summary(
        logger,
        total_created,
        total_skipped,
        total_counts,
        header=f"Total across {len(reports)} stages",
        suffix=suffix,
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point for the populate CLI."""
    setup_logging()
    args = _build_parser().parse_args(argv)

    logger.info(
        "Populating %s from %s%s",
        args.db,
        args.seed_dir,
        " (dry run)" if args.dry_run else "",
    )
    with KnowledgeStore(db_path=args.db) as store:
        reports = populate(args.seed_dir, store, dry_run=args.dry_run)
    _log_report(reports, args.dry_run)


if __name__ == "__main__":
    main()


__all__ = ["StageReport", "main", "populate"]
