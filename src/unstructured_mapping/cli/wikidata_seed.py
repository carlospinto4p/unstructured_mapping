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

from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.cli._seed_helpers import (
    exists_by_name_and_type,
    import_with_dedup,
)
from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
)
from unstructured_mapping.wikidata import (
    CENTRAL_BANKS_QUERY,
    CRYPTO_QUERY,
    CURRENCIES_QUERY,
    EXCHANGES_QUERY,
    INDICES_QUERY,
    LISTED_COMPANIES_QUERY,
    MappedEntity,
    REGULATORS_QUERY,
    SparqlClient,
    build_query,
    map_central_bank_row,
    map_company_row,
    map_crypto_row,
    map_currency_row,
    map_exchange_row,
    map_index_row,
    map_regulator_row,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path("data/knowledge.db")

#: Registry of supported ``--type`` values. Each entry maps
#: to the SPARQL template and the row mapper that handle it.
#: New phases (central_bank, regulator, index, currency) add
#: entries here without touching the CLI plumbing.
_TYPE_HANDLERS = {
    "company": (LISTED_COMPANIES_QUERY, map_company_row),
    "central_bank": (
        CENTRAL_BANKS_QUERY,
        map_central_bank_row,
    ),
    "regulator": (REGULATORS_QUERY, map_regulator_row),
    "exchange": (EXCHANGES_QUERY, map_exchange_row),
    "currency": (CURRENCIES_QUERY, map_currency_row),
    "index": (INDICES_QUERY, map_index_row),
    "crypto": (CRYPTO_QUERY, map_crypto_row),
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Seed the KG with entities from Wikidata."
        ),
    )
    p.add_argument(
        "--type",
        choices=sorted(_TYPE_HANDLERS),
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
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=(
            "Path to the KG SQLite database "
            f"(default: {_DEFAULT_DB})."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch and map entities without writing to the "
            "database."
        ),
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


def _fetch_mapped(
    kind: str, limit: int
) -> list[MappedEntity]:
    """Fetch rows from Wikidata and map them to entities.

    :param kind: One of the keys of :data:`_TYPE_HANDLERS`.
    :param limit: Row cap passed to the SPARQL query.
    :return: The mapped entities with ``None`` results
        (unlabelled rows etc.) filtered out.
    """
    template, mapper = _TYPE_HANDLERS[kind]
    query = build_query(template, limit=limit)
    with SparqlClient() as client:
        rows = client.query(query)
    mapped: list[MappedEntity] = []
    for row in rows:
        result = mapper(row)
        if result is not None:
            mapped.append(result)
    return mapped


def _already_imported(
    store: KnowledgeStore, mapped: MappedEntity
) -> bool:
    """Return True if this Wikidata entity is already in KG.

    Checks the ``wikidata:Qxxx`` alias first, then falls
    back to a canonical-name + type match so hand-curated
    seed entries are not duplicated by a Wikidata import.
    """
    qid_alias = f"wikidata:{mapped.qid}"
    if store.find_by_alias(qid_alias):
        return True
    return exists_by_name_and_type(
        store,
        mapped.entity.canonical_name,
        mapped.entity.entity_type,
    )


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
        is_duplicate=_already_imported,
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


def _write_snapshot(
    mapped: list[MappedEntity], path: Path
) -> None:
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
        "entities": [
            _entity_to_seed_json(m.entity) for m in mapped
        ],
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

    logger.info(
        "Import complete: %d created, %d skipped%s",
        created,
        skipped,
        " (dry run)" if args.dry_run else "",
    )
    for subtype, count in sorted(counts.items()):
        logger.info("  %-14s %d", subtype, count)


if __name__ == "__main__":
    main()


# Re-exports for tests; kept at module bottom so the public
# CLI surface (``main``) stays first in the file.
__all__ = [
    "EntityType",
    "import_entities",
    "main",
]
