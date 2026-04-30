"""Wikidata fetch and snapshot helpers.

Provides the two operations shared by the CLI seed command
and the API refresh endpoint: fetching a batch of entities
from the Wikidata SPARQL endpoint and writing the result as
a seed-compatible JSON snapshot.

These live here (rather than in ``cli/wikidata_seed.py``)
because the API layer needs them independently of the CLI.
Having them in the ``wikidata`` package keeps the API →
Wikidata dependency clean and avoids importing CLI internals
from API handlers.
"""

import json
from pathlib import Path

from unstructured_mapping.wikidata.client import SparqlClient
from unstructured_mapping.wikidata.mapper import (
    MappedEntity,
    dedupe_mapped_by_qid,
)
from unstructured_mapping.wikidata.queries import build_query
from unstructured_mapping.wikidata.registry import TYPE_REGISTRY


def fetch_mapped(kind: str, limit: int) -> list[MappedEntity]:
    """Fetch rows from Wikidata and map them to entities.

    Queries the Wikidata SPARQL endpoint for the given
    entity type, maps each row through the registered
    handler, and deduplicates by QID before returning.

    :param kind: One of the keys of
        :data:`unstructured_mapping.wikidata.TYPE_REGISTRY`.
    :param limit: Row cap passed to the SPARQL query.
    :return: Deduplicated mapped entities, with ``None``
        results (unlabelled rows, etc.) filtered out.
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
    return dedupe_mapped_by_qid(mapped)


def _entity_to_seed_json(entity: object) -> dict:
    return {
        "canonical_name": entity.canonical_name,  # type: ignore[attr-defined]
        "entity_type": entity.entity_type.value,  # type: ignore[attr-defined]
        "subtype": entity.subtype,  # type: ignore[attr-defined]
        "description": entity.description,  # type: ignore[attr-defined]
        "aliases": list(entity.aliases),  # type: ignore[attr-defined]
    }


def write_snapshot(mapped: list[MappedEntity], path: Path) -> None:
    """Write mapped entities as a seed-compatible JSON file.

    The ``"reason"`` field tells ``cli.seed.load_seed`` how to
    tag ``entity_history`` entries on replay, so a rebuild from
    snapshots preserves the ``reason="wikidata-seed"`` origin.

    :param mapped: Entities returned by :func:`fetch_mapped`.
    :param path: Destination path. Parent directories are
        created automatically.
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
