"""Bootstrap the knowledge graph from a curated seed file.

Usage::

    uv run python -m unstructured_mapping.cli.seed
    uv run python -m unstructured_mapping.cli.seed \\
        --seed data/seed/financial_entities.json \\
        --db data/knowledge.db

The seed file is a JSON document with an ``entities`` array.
Each entry must have ``canonical_name``, ``entity_type``
(matching :class:`EntityType`), and ``description``; plus
optional ``subtype`` and ``aliases``.

Entities that already exist in the KG (matched by
``canonical_name`` + ``entity_type``, case-insensitive) are
skipped, so the loader is idempotent — re-running after a
seed file update only persists new entries. All newly
created entities are tagged with ``reason="seed"`` in the
entity history for provenance, unless the payload declares
a different ``"reason"`` at the top level — Wikidata
snapshots use ``"wikidata-seed"`` to round-trip origin.
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

logger = logging.getLogger(__name__)

_DEFAULT_SEED = Path("data/seed/financial_entities.json")
_DEFAULT_DB = Path("data/knowledge.db")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Bootstrap the KG from a curated seed file."
        ),
    )
    p.add_argument(
        "--seed",
        type=Path,
        default=_DEFAULT_SEED,
        help=(
            "Path to the seed JSON file "
            f"(default: {_DEFAULT_SEED})."
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
            "Parse and validate the seed file without "
            "writing to the database."
        ),
    )
    return p


def _parse_entity(raw: dict) -> Entity:
    """Convert a seed JSON record to an :class:`Entity`.

    :param raw: Parsed JSON object from the seed file.
    :return: A validated :class:`Entity`.
    :raises KeyError: If a required field is missing.
    :raises ValueError: If ``entity_type`` is not a
        recognised :class:`EntityType` value.
    """
    aliases = tuple(raw.get("aliases") or ())
    return Entity(
        canonical_name=raw["canonical_name"],
        entity_type=EntityType(raw["entity_type"]),
        description=raw["description"],
        subtype=raw.get("subtype"),
        aliases=aliases,
    )


def load_seed(
    seed_path: Path,
    store: KnowledgeStore,
    *,
    dry_run: bool = False,
) -> tuple[int, int, Counter]:
    """Load entities from ``seed_path`` into ``store``.

    The seed file may declare a top-level ``"reason"``
    string. If present, every new entity is tagged with
    that value in the ``entity_history`` audit log;
    otherwise the default ``"seed"`` reason is used.

    The Wikidata snapshots under ``data/seed/wikidata/``
    set ``"reason": "wikidata-seed"`` so replaying them
    preserves the origin signal that the live
    ``wikidata_seed`` import would have emitted.

    :param seed_path: Path to the seed JSON file.
    :param store: Target knowledge store.
    :param dry_run: When True, only parse and validate;
        do not write to the database.
    :return: ``(created, skipped, counts_by_type)`` where
        ``counts_by_type`` is a :class:`Counter` of the
        created entities keyed by ``entity_type.value``.
    """
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    entities = [
        _parse_entity(r) for r in data.get("entities", [])
    ]
    reason = data.get("reason", "seed")
    return import_with_dedup(
        entities,
        store,
        get_entity=lambda e: e,
        is_duplicate=lambda s, e: exists_by_name_and_type(
            s, e.canonical_name, e.entity_type
        ),
        counter_key=lambda e: e.entity_type.value,
        reason=reason,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point for the seed CLI."""
    setup_logging()
    args = _build_parser().parse_args(argv)

    if not args.seed.exists():
        logger.error(
            "Seed file not found: %s", args.seed
        )
        raise SystemExit(1)

    logger.info(
        "Loading seed %s into %s%s",
        args.seed,
        args.db,
        " (dry run)" if args.dry_run else "",
    )

    with KnowledgeStore(db_path=args.db) as store:
        created, skipped, counts = load_seed(
            args.seed, store, dry_run=args.dry_run
        )

    logger.info(
        "Seed complete: %d created, %d skipped",
        created,
        skipped,
    )
    for etype, count in sorted(counts.items()):
        logger.info("  %-14s %d", etype, count)


if __name__ == "__main__":
    main()
