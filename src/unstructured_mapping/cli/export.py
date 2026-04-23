"""Export KG entities / relationships / provenance to
portable files.

Two output shapes are supported today, both plain-text so
no extra dependency is required:

- ``jsonl`` — one JSON object per line. Lowest-friction
  shape for downstream scripts and streaming consumers
  (``cat | jq``, ``pandas.read_json(lines=True)``,
  ``duckdb read_json_auto``).
- ``json-ld`` — a JSON-LD document per stream with a
  minimal ``@context`` that renames the entity /
  relationship fields into IRIs scoped under a per-project
  namespace. Not a semantic-web ontology mapping — the
  aim is "a well-formed JSON-LD document other tools can
  parse", not full RDF / schema.org compliance. A future
  iteration can swap in a richer context without changing
  the export shape.

Parquet is intentionally deferred to keep the default
install light; tracked separately in the backlog so the
``pyarrow`` dependency only lands when the ``export``
extra exists.

Usage::

    # Entities only (default), JSON-L, filtered by type:
    uv run python -m unstructured_mapping.cli.export \\
        --db data/knowledge.db \\
        --output-dir exports/ \\
        --type organization

    # All three streams in JSON-LD, scoped to recent rows:
    uv run python -m unstructured_mapping.cli.export \\
        --db data/knowledge.db \\
        --output-dir exports/ \\
        --format json-ld \\
        --with-relationships --with-provenance \\
        --since 2026-01-01
"""

import argparse
import json
import logging
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
)
from unstructured_mapping.cli._db_helpers import open_kg_store
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    Entity,
    KnowledgeStore,
    Provenance,
    Relationship,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityType,
)

logger = logging.getLogger(__name__)

#: Supported output format slugs. Kept as a sorted tuple so
#: ``--format`` choices render deterministically in
#: ``--help``.
SUPPORTED_FORMATS: tuple[str, ...] = ("json-ld", "jsonl")

#: Default file-name stems per stream. Extension is
#: appended at write time based on the chosen format.
_FILENAMES: dict[str, str] = {
    "entities": "entities",
    "relationships": "relationships",
    "provenance": "provenance",
}

#: Minimal JSON-LD @context. Renames every field onto a
#: local namespace IRI so the document is valid JSON-LD
#: without claiming mapping into any external vocabulary.
_JSONLD_CONTEXT: dict[str, str] = {
    "@vocab": ("https://example.org/unstructured_mapping/vocab#"),
    "entities": "@graph",
    "relationships": "@graph",
    "provenance": "@graph",
}


def _iter_entities(
    store: KnowledgeStore,
    *,
    entity_type: EntityType | None,
    subtype: str | None,
    since: datetime | None,
) -> list[Entity]:
    """Select entities matching the filter combination.

    Filters compose: ``type`` narrows to a specific enum
    value, ``subtype`` further narrows inside that type,
    and ``since`` scopes to entities created on or after a
    timestamp. When *no* filter is supplied the export
    falls back to every ACTIVE entity, the same universe
    the pipeline uses for detection.
    """
    if subtype is not None and entity_type is not None:
        return store.find_entities_by_subtype(
            entity_type=entity_type, subtype=subtype
        )
    if entity_type is not None:
        return store.find_entities_by_type(entity_type=entity_type)
    if since is not None:
        return store.find_entities_since(since=since)
    # No filter: export the active universe. Deprecated /
    # merged entities are intentionally skipped — callers
    # that need them can dump the full DB directly.
    from unstructured_mapping.knowledge_graph.models import (
        EntityStatus,
    )

    return store.find_entities_by_status(EntityStatus.ACTIVE)


def _entity_payload(entity: Entity) -> dict[str, object]:
    """Serialise an entity to a JSON-safe dict.

    Datetimes are ISO-formatted; enums are rendered as
    their ``.value`` so the export is consumable by any
    JSON reader without custom decoders.
    """
    payload = asdict(entity)
    payload["entity_type"] = entity.entity_type.value
    payload["status"] = entity.status.value
    for field in ("valid_from", "valid_until", "created_at", "updated_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    payload["aliases"] = list(entity.aliases)
    return payload


def _relationship_payload(
    rel: Relationship,
) -> dict[str, object]:
    payload = asdict(rel)
    for field in ("valid_from", "valid_until", "discovered_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    return payload


def _provenance_payload(
    prov: Provenance,
) -> dict[str, object]:
    payload = asdict(prov)
    value = payload.get("detected_at")
    if isinstance(value, datetime):
        payload["detected_at"] = value.isoformat()
    return payload


def _collect_relationships(
    store: KnowledgeStore, entities: Sequence[Entity]
) -> list[Relationship]:
    """Fetch relationships touching any exported entity.

    Uses the per-entity ``get_relationships`` lookup in a
    loop — the relationship count per entity is small and
    the store returns both source-side and target-side
    matches in one call. Deduplicates across entities on
    ``(source_id, target_id, relation_type, valid_from)``
    so a shared edge is emitted once.
    """
    if not entities:
        return []
    seen: set[tuple[str, str, str, str]] = set()
    out: list[Relationship] = []
    for entity in entities:
        for rel in store.get_relationships(entity.entity_id):
            key = (
                rel.source_id,
                rel.target_id,
                rel.relation_type,
                rel.valid_from.isoformat()
                if rel.valid_from is not None
                else "",
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(rel)
    return out


def _collect_provenance(
    store: KnowledgeStore, entities: Sequence[Entity]
) -> list[Provenance]:
    """Fetch provenance rows for the exported entities."""
    out: list[Provenance] = []
    for entity in entities:
        out.extend(store.get_provenance(entity.entity_id))
    return out


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> int:
    """Serialise ``rows`` to newline-delimited JSON.

    :return: Count of rows written.
    """
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
            count += 1
    return count


def _write_jsonld(
    path: Path,
    stream_key: str,
    rows: list[dict[str, object]],
) -> int:
    """Serialise ``rows`` as a JSON-LD document.

    ``stream_key`` controls which @context alias renders
    as ``@graph``; the three streams share a single
    context so multi-file consumers can merge them.

    :return: Count of rows written.
    """
    document = {
        "@context": _JSONLD_CONTEXT,
        stream_key: rows,
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return len(rows)


def export_kg(
    store: KnowledgeStore,
    output_dir: Path,
    *,
    fmt: str,
    entity_type: EntityType | None = None,
    subtype: str | None = None,
    since: datetime | None = None,
    with_relationships: bool = False,
    with_provenance: bool = False,
) -> dict[str, int]:
    """Export the selected slice to ``output_dir``.

    :return: Mapping of stream name (``entities`` /
        ``relationships`` / ``provenance``) to row count
        written. Streams the caller did not opt into are
        absent from the result.
    """
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"unsupported format: {fmt!r}; "
            f"expected one of {SUPPORTED_FORMATS}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    entities = _iter_entities(
        store,
        entity_type=entity_type,
        subtype=subtype,
        since=since,
    )
    rels = (
        _collect_relationships(store, entities) if with_relationships else []
    )
    provs = _collect_provenance(store, entities) if with_provenance else []

    entity_rows = [_entity_payload(e) for e in entities]
    rel_rows = [_relationship_payload(r) for r in rels]
    prov_rows = [_provenance_payload(p) for p in provs]

    ext = {"jsonl": "jsonl", "json-ld": "jsonld"}[fmt]
    counts: dict[str, int] = {}
    if fmt == "jsonl":
        counts["entities"] = _write_jsonl(
            output_dir / f"{_FILENAMES['entities']}.{ext}",
            entity_rows,
        )
        if with_relationships:
            counts["relationships"] = _write_jsonl(
                output_dir / f"{_FILENAMES['relationships']}.{ext}",
                rel_rows,
            )
        if with_provenance:
            counts["provenance"] = _write_jsonl(
                output_dir / f"{_FILENAMES['provenance']}.{ext}",
                prov_rows,
            )
    else:  # json-ld
        counts["entities"] = _write_jsonld(
            output_dir / f"{_FILENAMES['entities']}.{ext}",
            "entities",
            entity_rows,
        )
        if with_relationships:
            counts["relationships"] = _write_jsonld(
                output_dir / f"{_FILENAMES['relationships']}.{ext}",
                "relationships",
                rel_rows,
            )
        if with_provenance:
            counts["provenance"] = _write_jsonld(
                output_dir / f"{_FILENAMES['provenance']}.{ext}",
                "provenance",
                prov_rows,
            )
    return counts


def _parse_since(value: str) -> datetime:
    """Accept ``YYYY-MM-DD`` or full ISO 8601 timestamps.

    ``fromisoformat`` handles both since Python 3.11; we
    normalise bare dates to midnight UTC so ``--since``
    and ``find_entities_since`` agree on the boundary.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Export KG entities and optionally "
            "relationships / provenance to JSON-L or "
            "JSON-LD."
        ),
    )
    add_db_argument(p, required=True)
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write export files into.",
    )
    p.add_argument(
        "--format",
        choices=SUPPORTED_FORMATS,
        default="jsonl",
        help="Output format (default: jsonl).",
    )
    p.add_argument(
        "--type",
        choices=[t.value for t in EntityType],
        default=None,
        help="Filter entities by type.",
    )
    p.add_argument(
        "--subtype",
        default=None,
        help=("Filter entities by subtype (requires --type)."),
    )
    p.add_argument(
        "--since",
        type=_parse_since,
        default=None,
        help=(
            "Only export entities created on or after "
            "this date/ISO timestamp."
        ),
    )
    p.add_argument(
        "--with-relationships",
        action="store_true",
        help="Also export relationships touching exported entities.",
    )
    p.add_argument(
        "--with-provenance",
        action="store_true",
        help="Also export provenance rows for exported entities.",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _build_parser().parse_args(argv)
    if args.subtype is not None and args.type is None:
        raise SystemExit("error: --subtype requires --type")
    entity_type = EntityType(args.type) if args.type is not None else None
    with open_kg_store(args.db) as store:
        counts = export_kg(
            store,
            args.output_dir,
            fmt=args.format,
            entity_type=entity_type,
            subtype=args.subtype,
            since=args.since,
            with_relationships=args.with_relationships,
            with_provenance=args.with_provenance,
        )
    summary = ", ".join(f"{k}={v}" for k, v in counts.items())
    sys.stdout.write(
        f"Wrote {args.format} export to {args.output_dir}: {summary}\n"
    )


if __name__ == "__main__":
    main()


__all__ = [
    "SUPPORTED_FORMATS",
    "export_kg",
    "main",
]
