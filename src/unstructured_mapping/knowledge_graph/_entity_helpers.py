"""Shared internal helpers for entity mixins.

Provides alias loading, syncing, and row-conversion
utilities used by the CRUD, search, merge, and history
mixins. Not part of the public API.
"""

import json
import logging
import sqlite3

from unstructured_mapping.knowledge_graph._helpers import (
    dt_to_iso,
    now_iso,
    row_to_entity,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
)

logger = logging.getLogger(__name__)


class EntityHelpersMixin:
    """Internal helpers shared across entity mixins."""

    _conn: sqlite3.Connection

    def _rows_to_entities(
        self,
        rows: list[tuple[str, ...]],
    ) -> list[Entity]:
        """Convert entity rows with batch alias loading."""
        if not rows:
            return []
        eids = [r["entity_id"] for r in rows]
        alias_map = self._load_aliases_batch(eids)
        return [
            row_to_entity(
                r, alias_map.get(r["entity_id"], ())
            )
            for r in rows
        ]

    def _sync_aliases(
        self,
        entity_id: str,
        aliases: tuple[str, ...],
    ) -> None:
        """Delete old aliases and insert new ones."""
        self._conn.execute(
            "DELETE FROM entity_aliases "
            "WHERE entity_id = ?",
            (entity_id,),
        )
        if aliases:
            self._conn.executemany(
                "INSERT INTO entity_aliases "
                "(entity_id, alias) VALUES (?, ?)",
                [
                    (entity_id, a) for a in aliases
                ],
            )

    def _log_entity(
        self,
        entity: Entity,
        operation: str,
        reason: str | None,
    ) -> None:
        aliases_json = json.dumps(entity.aliases)
        self._conn.execute(
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

    def _load_aliases(
        self, entity_id: str
    ) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT alias FROM entity_aliases "
            "WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()
        return tuple(r["alias"] for r in rows)

    def _load_aliases_batch(
        self, entity_ids: list[str]
    ) -> dict[str, tuple[str, ...]]:
        """Fetch aliases for multiple entities.

        :return: Mapping of entity_id to aliases tuple.
        """
        if not entity_ids:
            return {}
        placeholders = ", ".join(
            "?" for _ in entity_ids
        )
        rows = self._conn.execute(
            "SELECT entity_id, alias "
            "FROM entity_aliases "
            f"WHERE entity_id IN ({placeholders})",
            entity_ids,
        ).fetchall()
        result: dict[str, list[str]] = {}
        for eid, alias in rows:
            result.setdefault(eid, []).append(alias)
        return {
            eid: tuple(aliases)
            for eid, aliases in result.items()
        }

    def _redirect_entity_references(
        self,
        old_id: str,
        new_id: str,
    ) -> None:
        """Redirect all FK references from old to new."""
        for sql in (
            "UPDATE provenance SET entity_id = ? "
            "WHERE entity_id = ?",
            "UPDATE relationships SET source_id = ? "
            "WHERE source_id = ?",
            "UPDATE relationships SET target_id = ? "
            "WHERE target_id = ?",
            "UPDATE relationships "
            "SET qualifier_id = ? "
            "WHERE qualifier_id = ?",
            "UPDATE relationships "
            "SET relation_kind_id = ? "
            "WHERE relation_kind_id = ?",
        ):
            self._conn.execute(sql, (new_id, old_id))
