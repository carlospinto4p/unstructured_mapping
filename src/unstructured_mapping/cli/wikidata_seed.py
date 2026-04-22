"""Seed the knowledge graph with entities from Wikidata.

Queries the Wikidata SPARQL endpoint, maps each row to an
:class:`Entity`, and persists new entries to the KG.
Deduplication is two-tier:

1. By ``wikidata:Qxxx`` alias — catches prior Wikidata
   imports cheaply regardless of name drift.
2. By ``canonical_name`` + ``entity_type`` (case-insensitive)
   — catches overlap with the curated seed file so a company
   already present as "Apple Inc." is not reinserted as
   "Apple Inc.".

Every imported entity is tagged with
``reason="wikidata-seed"`` in the entity-history audit log.

Usage::

    uv run python -m unstructured_mapping.cli.wikidata_seed \\
        --type company --limit 500

    uv run python -m unstructured_mapping.cli.wikidata_seed \\
        --type company --limit 10 --dry-run

    uv run python -m unstructured_mapping.cli.wikidata_seed \\
        --type company --limit 100 \\
        --snapshot data/seed/wikidata_companies.json

The ``--snapshot`` option writes the mapped entities to a
JSON file compatible with ``cli.seed``, giving a reproducible
offline artifact of the import.
"""

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
    add_dry_run_argument,
)
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.cli._seed_helpers import (
    import_with_dedup,
    log_import_summary,
)
from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
)
from unstructured_mapping.wikidata import (
    TYPE_REGISTRY,
    MappedEntity,
    SparqlClient,
    build_query,
    dedupe_mapped_by_qid,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=("Seed the KG with entities from Wikidata."),
    )
    p.add_argument(
        "--type",
        choices=sorted(TYPE_REGISTRY),
        default="company",
        help="Entity category to import (default: company).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=100,
        help=(
            "Max number of rows to request from Wikidata "
            "(default: 100). Results are ordered by market "
            "cap DESC so the most impactful entities come "
            "first."
        ),
    )
    add_db_argument(p)
    add_dry_run_argument(
        p,
        help_text=("Fetch and map entities without writing to the database."),
    )
    p.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help=(
            "Optional path to write mapped entities as a "
            "seed-compatible JSON file for reproducibility."
        ),
    )
    return p


def _fetch_mapped(kind: str, limit: int) -> list[MappedEntity]:
    """Fetch rows from Wikidata and map them to entities.

    :param kind: One of the keys of
        :data:`unstructured_mapping.wikidata.TYPE_REGISTRY`.
    :param limit: Row cap passed to the SPARQL query.
    :return: The mapped entities with ``None`` results
        (unlabelled rows etc.) filtered out.
    """
    handler = TYPE_REGISTRY[kind]
    query = build_query(handler.query, limit=limit)
    with SparqlClient() as client:
        rows = client.query(query)
    mapped: list[MappedEntity] = []
    for row in rows:
        result = handler.mapper(row)
        if result is not None:
            mapped.append(result)
    # Wikidata OPTIONAL joins fan each QID out into several
    # rows; collapse them before snapshot writing or dedup.
    return dedupe_mapped_by_qid(mapped)


def _build_dedup_check(store: KnowledgeStore):
    """Build an ``is_duplicate`` closure with prefetched state.

    Replaces per-candidate ``alias_exists`` + ``exists_by_name_and_type``
    queries (2 × N DB round-trips) with two bulk lookups up front
    and O(1) Python ``in`` checks inside the loop.

    :param store: The knowledge store to prefetch from.
    :return: Callable matching ``is_duplicate(store, mapped)`` — the
        ``store`` parameter is ignored since the prefetched sets
        are captured in the closure; kept for signature compatibility
        with :func:`import_with_dedup`.
    """
    qids = store.wikidata_qids()
    name_types = store.name_type_pairs()

    def check(_store: KnowledgeStore, mapped: MappedEntity) -> bool:
        if mapped.qid in qids:
            return True
        key = (
            mapped.entity.canonical_name.lower(),
            mapped.entity.entity_type.value,
        )
        return key in name_types

    return check


def import_entities(
    mapped: list[MappedEntity],
    store: KnowledgeStore,
    *,
    dry_run: bool = False,
) -> tuple[int, int, Counter]:
    """Persist mapped entities, skipping duplicates.

    :param mapped: Entities returned by :func:`_fetch_mapped`.
    :param store: Target knowledge store.
    :param dry_run: When True, only run dedup; do not write.
    :return: ``(created, skipped, counts_by_subtype)``.
    """
    return import_with_dedup(
        mapped,
        store,
        get_entity=lambda m: m.entity,
        is_duplicate=_build_dedup_check(store),
        counter_key=lambda e: e.subtype or "unknown",
        reason="wikidata-seed",
        dry_run=dry_run,
    )


def _entity_to_seed_json(entity: Entity) -> dict:
    """Serialise an entity to a seed-file-compatible dict."""
    return {
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type.value,
        "subtype": entity.subtype,
        "description": entity.description,
        "aliases": list(entity.aliases),
    }


def _write_snapshot(mapped: list[MappedEntity], path: Path) -> None:
    """Write mapped entities as a seed-compatible JSON file.

    The ``"reason"`` field tells :func:`cli.seed.load_seed`
    how to tag ``entity_history`` entries on replay, so a
    rebuild from snapshots preserves the
    ``reason="wikidata-seed"`` origin signal.
    """
    payload = {
        "version": 1,
        "reason": "wikidata-seed",
        "description": (
            "Wikidata seed snapshot. Re-loadable via "
            "cli.seed for reproducibility."
        ),
        "entities": [_entity_to_seed_json(m.entity) for m in mapped],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point for the Wikidata seed CLI."""
    setup_logging()
    args = _build_parser().parse_args(argv)

    logger.info(
        "Fetching up to %d %s entities from Wikidata",
        args.limit,
        args.type,
    )
    mapped = _fetch_mapped(args.type, args.limit)
    logger.info("Mapped %d entities", len(mapped))

    if args.snapshot is not None:
        _write_snapshot(mapped, args.snapshot)
        logger.info("Wrote snapshot %s", args.snapshot)

    with KnowledgeStore(db_path=args.db) as store:
        created, skipped, counts = import_entities(
            mapped, store, dry_run=args.dry_run
        )

    log_import_summary(
        logger,
        created,
        skipped,
        counts,
        header="Import complete",
        suffix=" (dry run)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()


# Re-exports for tests; kept at module bottom so the public
# CLI surface (``main``) stays first in the file.
__all__ = [
    "EntityType",
    "import_entities",
    "main",
]
