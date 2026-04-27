"""Shared internal helpers for entity mixins.

Module-level functions providing alias loading, syncing,
and row-conversion utilities. Each function takes a
``conn`` parameter directly so all entity sub-mixins
can call them without inheriting a shared base class.
Not part of the public API.
"""

import json
import logging
import sqlite3

from unstructured_mapping.knowledge_graph._helpers import (
    ENTITY_SELECT,
    dt_to_iso,
    now_iso,
    row_to_entity,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
)

logger = logging.getLogger(__name__)


def rows_to_entities(
    conn: sqlite3.Connection,
    rows: list[tuple[str, ...]],
) -> list[Entity]:
    """Convert entity rows with batch alias loading."""
    if not rows:
        return []
    eids = [r["entity_id"] for r in rows]
    alias_map = load_aliases_batch(conn, eids)
    return [row_to_entity(r, alias_map.get(r["entity_id"], ())) for r in rows]


def find_entities_where(
    conn: sqlite3.Connection,
    where_clause: str,
    params: list[object],
    *,
    suffix: str = "",
    limit: int | None = None,
) -> list[Entity]:
    """Run ``ENTITY_SELECT + WHERE ...`` with optional
    suffix (ORDER BY) and LIMIT, returning entities.

    Every filtered-entity query in
    :class:`EntitySearchMixin` follows the same shape;
    this helper centralises the query assembly and
    row-to-entity conversion so callers only supply
    the discriminating parts.

    :param conn: SQLite connection.
    :param where_clause: The WHERE expression, without
        the ``WHERE`` keyword (e.g. ``"entity_type = ?"``).
    :param params: Positional parameters for the WHERE
        placeholders, in order.
    :param suffix: Optional SQL fragment appended after
        the WHERE clause and before any LIMIT (e.g.
        ``"ORDER BY created_at DESC"``).
    :param limit: Optional LIMIT bound; appended as a
        parameter when present.
    :return: Matching entities with aliases hydrated.
    """
    query = ENTITY_SELECT + "WHERE " + where_clause
    effective_params = list(params)
    if suffix:
        query += " " + suffix
    if limit is not None:
        query += " LIMIT ?"
        effective_params.append(limit)
    rows = conn.execute(query, effective_params).fetchall()
    return rows_to_entities(conn, rows)


def sync_aliases(
    conn: sqlite3.Connection,
    entity_id: str,
    aliases: tuple[str, ...],
) -> None:
    """Delete old aliases and insert new ones."""
    conn.execute(
        "DELETE FROM entity_aliases WHERE entity_id = ?",
        (entity_id,),
    )
    if aliases:
        conn.executemany(
            "INSERT INTO entity_aliases (entity_id, alias) VALUES (?, ?)",
            [(entity_id, a) for a in aliases],
        )


def log_entity(
    conn: sqlite3.Connection,
    entity: Entity,
    operation: str,
    reason: str | None,
) -> None:
    aliases_json = json.dumps(entity.aliases)
    conn.execute(
        "INSERT INTO entity_history "
        "(entity_id, operation, changed_at, "
        "canonical_name, entity_type, subtype, "
        "description, aliases, valid_from, "
        "valid_until, status, merged_into, "
        "reason) "
        "VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entity.entity_id,
            operation,
            now_iso(),
            entity.canonical_name,
            entity.entity_type.value,
            entity.subtype,
            entity.description,
            aliases_json,
            dt_to_iso(entity.valid_from),
            dt_to_iso(entity.valid_until),
            entity.status.value,
            entity.merged_into,
            reason,
        ),
    )


def load_aliases(
    conn: sqlite3.Connection,
    entity_id: str,
) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT alias FROM entity_aliases WHERE entity_id = ?",
        (entity_id,),
    ).fetchall()
    return tuple(r["alias"] for r in rows)


def load_aliases_batch(
    conn: sqlite3.Connection,
    entity_ids: list[str],
) -> dict[str, tuple[str, ...]]:
    """Fetch aliases for multiple entities.

    The id list is chunked so each ``WHERE IN (...)``
    query stays well under SQLite's default
    ``SQLITE_MAX_VARIABLE_NUMBER = 999`` parameter
    limit. Without chunking, bulk reads on a large KG
    (e.g. ``find_entities_by_status(limit=100_000)``
    after a Wikidata import) raise
    ``OperationalError: too many SQL variables``.

    :return: Mapping of entity_id to aliases tuple.
    """
    if not entity_ids:
        return {}
    # 500 keeps a comfortable margin below the 999 cap
    # and matches the chunk size SQLite itself
    # documents as the safe upper bound for portable
    # builds.
    chunk_size = 500
    result: dict[str, list[str]] = {}
    for start in range(0, len(entity_ids), chunk_size):
        chunk = entity_ids[start : start + chunk_size]
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT entity_id, alias "
            "FROM entity_aliases "
            f"WHERE entity_id IN ({placeholders})",
            chunk,
        ).fetchall()
        for eid, alias in rows:
            result.setdefault(eid, []).append(alias)
    return {eid: tuple(aliases) for eid, aliases in result.items()}


def redirect_entity_references(
    conn: sqlite3.Connection,
    old_id: str,
    new_id: str,
) -> None:
    """Redirect all FK references from old to new."""
    for sql in (
        "UPDATE provenance SET entity_id = ? WHERE entity_id = ?",
        "UPDATE relationships SET source_id = ? WHERE source_id = ?",
        "UPDATE relationships SET target_id = ? WHERE target_id = ?",
        "UPDATE relationships SET qualifier_id = ? WHERE qualifier_id = ?",
        "UPDATE relationships "
        "SET relation_kind_id = ? "
        "WHERE relation_kind_id = ?",
    ):
        conn.execute(sql, (new_id, old_id))
