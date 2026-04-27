"""Entity-centric k-hop subgraph extraction.

Given an entity id or canonical name, walk outward N hops
through the relationship graph and emit a JSON payload of:

* the root entity,
* the set of entities reachable within N hops,
* the relationships connecting them, and
* the documents that justify each edge (read from the
  ``relationships.document_id`` column that the extractor
  populates on every row it saves).

Why this CLI
------------

The KG already exposes :meth:`find_co_mentioned`,
:meth:`find_relationships_by_document`, and
:meth:`find_provenance_for_entity`, but none of them answers "given
entity X, show its neighbourhood in the news graph with
supporting documents" in a single call. This CLI stitches
the building blocks together and keeps the output shape
stable so downstream tooling (notebooks, dashboards, LLM
prompts) can depend on it.

Scope boundary
--------------

The payload indexes *which news connected these
entities*; it is not a quantitative dataset. Per the KG
design intent, edges carry context snippets and
confidence but no numeric analytics. Callers that want
counts / time-series / sentiment layer those on top.

Usage::

    # By entity id
    uv run python -m unstructured_mapping.cli.subgraph \\
        --db data/knowledge.db \\
        --entity-id <hex> --hops 2

    # By canonical name (exact, case-insensitive)
    uv run python -m unstructured_mapping.cli.subgraph \\
        --db data/knowledge.db \\
        --name "Apple Inc." --hops 1

    # Write to a file and filter weak edges
    uv run python -m unstructured_mapping.cli.subgraph \\
        --db data/knowledge.db \\
        --entity-id <hex> --hops 2 \\
        --min-confidence 0.5 --output subgraph.json

Ambiguous names (``--name`` matches >1 entity) exit with
an error listing the candidates so the caller can pick
one by id. Isolated roots with no edges return the root
in ``entities`` and empty ``relationships`` /
``documents``.
"""

import argparse
import logging
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
)
from unstructured_mapping.cli._json_output import emit_json
from unstructured_mapping.cli._runner import run_cli_with_kg
from unstructured_mapping.knowledge_graph import (
    Entity,
    KnowledgeStore,
    Relationship,
)

logger = logging.getLogger(__name__)


def _resolve_root(
    store: KnowledgeStore,
    *,
    entity_id: str | None,
    name: str | None,
) -> Entity:
    """Resolve the root entity from ``--entity-id`` / ``--name``.

    Ambiguous names are a hard error — the user needs to
    pick. Unknown ids / names are also hard errors so the
    caller doesn't end up with an empty-but-"successful"
    payload.
    """
    if entity_id is not None:
        entity = store.get_entity(entity_id)
        if entity is None:
            raise SystemExit(f"error: entity {entity_id!r} not found")
        return entity
    assert name is not None  # argparse guarantees one is set
    matches = store.find_by_name(name)
    if not matches:
        raise SystemExit(f"error: no entity matches name {name!r}")
    if len(matches) > 1:
        preview = ", ".join(
            f"{e.entity_id[:8]}:{e.canonical_name}" for e in matches[:5]
        )
        raise SystemExit(
            f"error: {len(matches)} entities match name {name!r}: "
            f"{preview}. Pass --entity-id to disambiguate."
        )
    return matches[0]


def _edge_key(rel: Relationship) -> tuple[str, str, str, str]:
    """Identity tuple for dedup across the BFS.

    ``valid_from`` is part of the relationships primary
    key, so two edges with the same source/target/type
    but different temporal bounds are genuinely distinct
    records and stay separate in the output.
    """
    vf = rel.valid_from.isoformat() if rel.valid_from else ""
    return (rel.source_id, rel.target_id, rel.relation_type, vf)


def _expand_hops(
    store: KnowledgeStore,
    *,
    root_id: str,
    hops: int,
    min_confidence: float | None,
) -> tuple[set[str], list[Relationship]]:
    """BFS the k-hop frontier around ``root_id``.

    Each hop expands the frontier by following edges in
    both directions (source→target and target→source) —
    relationships are directed in the KG but for a
    neighbourhood view the arrowhead is irrelevant; what
    matters is that the entities are connected.

    :return: ``(entity_ids, edges)`` — all distinct
        entities visited including the root, and the
        deduped relationships discovered during the walk.
        The two sets are consistent: every entity
        appearing as source or target of an edge is in
        ``entity_ids``.
    """
    visited: set[str] = {root_id}
    edges: dict[tuple[str, str, str, str], Relationship] = {}
    frontier: set[str] = {root_id}
    for _ in range(hops):
        next_frontier: set[str] = set()
        for eid in frontier:
            # ``min_confidence=None`` matches
            # ``find_relationships``'s "no filter" contract.
            rels = store.find_relationships(
                eid,
                min_confidence=min_confidence,
            )
            for rel in rels:
                edges.setdefault(_edge_key(rel), rel)
                for neighbour in (rel.source_id, rel.target_id):
                    if neighbour not in visited:
                        visited.add(neighbour)
                        next_frontier.add(neighbour)
        if not next_frontier:
            break
        frontier = next_frontier
    return visited, list(edges.values())


def _render_entity(entity: Entity) -> dict:
    """Serialise an entity into the JSON payload shape."""
    return {
        "entity_id": entity.entity_id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type.value,
        "subtype": entity.subtype,
        "description": entity.description,
        "aliases": list(entity.aliases),
        "status": entity.status.value,
    }


def _render_relationship(rel: Relationship) -> dict:
    return {
        "source_id": rel.source_id,
        "target_id": rel.target_id,
        "relation_type": rel.relation_type,
        "description": rel.description,
        "qualifier_id": rel.qualifier_id,
        "relation_kind_id": rel.relation_kind_id,
        "valid_from": (
            rel.valid_from.isoformat() if rel.valid_from else None
        ),
        "valid_until": (
            rel.valid_until.isoformat() if rel.valid_until else None
        ),
        "document_id": rel.document_id,
        "confidence": rel.confidence,
        "run_id": rel.run_id,
    }


def build_subgraph(
    store: KnowledgeStore,
    *,
    entity_id: str | None,
    name: str | None,
    hops: int,
    min_confidence: float | None = None,
) -> dict:
    """Return the JSON-ready subgraph payload.

    :param store: Open KG store.
    :param entity_id: Root entity id. Mutually exclusive
        with ``name``.
    :param name: Root entity canonical name. Mutually
        exclusive with ``entity_id``.
    :param hops: Frontier depth. ``0`` returns just the
        root; ``1`` the immediate neighbourhood; etc.
    :param min_confidence: When set, drop edges with
        confidence below this threshold (and edges
        missing a confidence score).
    :return: Dict with keys ``root``, ``hops``,
        ``entities``, ``relationships``, ``documents``.
    """
    if hops < 0:
        raise ValueError("hops must be >= 0")
    if (entity_id is None) == (name is None):
        raise ValueError("Provide exactly one of --entity-id or --name.")

    root = _resolve_root(store, entity_id=entity_id, name=name)
    entity_ids, edges = _expand_hops(
        store,
        root_id=root.entity_id,
        hops=hops,
        min_confidence=min_confidence,
    )
    entities_by_id = store.get_entities(list(entity_ids))
    # Stable ordering: root first, then deterministic by
    # canonical_name so the payload diffs cleanly between
    # runs.
    ordered_ids = [root.entity_id] + sorted(
        (eid for eid in entity_ids if eid != root.entity_id),
        key=lambda e: (
            entities_by_id[e].canonical_name if e in entities_by_id else e
        ),
    )
    rendered_entities = [
        _render_entity(entities_by_id[eid])
        for eid in ordered_ids
        if eid in entities_by_id
    ]
    # Relationships deterministic by (source, target, rel,
    # valid_from) for the same reason.
    edges_sorted = sorted(edges, key=_edge_key)
    # Documents: every distinct ``document_id`` that shows
    # up as provenance for an edge. The extraction
    # pipeline writes one ``document_id`` per
    # relationship; missing values (manually curated
    # rows) are skipped.
    documents = sorted({r.document_id for r in edges_sorted if r.document_id})

    return {
        "root": _render_entity(root),
        "hops": hops,
        "min_confidence": min_confidence,
        "entities": rendered_entities,
        "relationships": [_render_relationship(r) for r in edges_sorted],
        "documents": documents,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Extract the k-hop subgraph around one entity "
            "and emit entities, relationships, and the "
            "documents that justify each edge as JSON."
        ),
    )
    add_db_argument(p, required=True)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--entity-id",
        help="Root entity id (hex).",
    )
    target.add_argument(
        "--name",
        help=(
            "Root entity canonical name (exact, case-"
            "insensitive). Ambiguous names fail fast; "
            "use --entity-id to disambiguate."
        ),
    )
    p.add_argument(
        "--hops",
        type=int,
        default=1,
        help=("Frontier depth (default 1). 0 returns just the root."),
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help=(
            "Drop edges with confidence below this "
            "threshold. Edges with NULL confidence are "
            "also dropped when this is set."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=("Where to write the JSON payload. Defaults to stdout."),
    )
    return p


def _validate(args: argparse.Namespace) -> None:
    if args.hops < 0:
        raise SystemExit("error: --hops must be >= 0")


def main(argv: list[str] | None = None) -> None:
    """Entry point for the subgraph CLI."""

    def _body(store: KnowledgeStore, args: argparse.Namespace) -> None:
        payload = build_subgraph(
            store,
            entity_id=args.entity_id,
            name=args.name,
            hops=args.hops,
            min_confidence=args.min_confidence,
        )
        emit_json(payload, args.output)
        if args.output is not None:
            logger.info(
                "Wrote %d entities, %d relationships, %d documents to %s",
                len(payload["entities"]),
                len(payload["relationships"]),
                len(payload["documents"]),
                args.output,
            )

    run_cli_with_kg(_build_parser, _body, argv, validate=_validate)


if __name__ == "__main__":
    main()


__all__ = [
    "build_subgraph",
    "main",
]
