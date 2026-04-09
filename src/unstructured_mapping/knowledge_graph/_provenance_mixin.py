"""Provenance and co-mention operations mixin.

Provides provenance CRUD and co-mention queries. Mixed
into :class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`.
"""

import sqlite3
from datetime import datetime

from unstructured_mapping.knowledge_graph._helpers import (
    dt_to_iso,
    row_to_entity,
    row_to_provenance,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    Provenance,
)


class ProvenanceMixin:
    """Provenance operations for :class:`KnowledgeStore`."""

    _conn: sqlite3.Connection

    # -- Provenance CRUD --

    def save_provenance(
        self, provenance: Provenance
    ) -> None:
        """Insert a provenance record, skipping duplicates.

        :param provenance: The provenance to save.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO provenance "
            "(entity_id, document_id, source, "
            "mention_text, context_snippet, "
            "detected_at, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                provenance.entity_id,
                provenance.document_id,
                provenance.source,
                provenance.mention_text,
                provenance.context_snippet,
                dt_to_iso(provenance.detected_at),
                provenance.run_id,
            ),
        )
        self._conn.commit()

    def save_provenances(
        self, provenances: list[Provenance]
    ) -> int:
        """Bulk insert provenance records, skipping dupes.

        :param provenances: The provenance records to save.
        :return: Number of newly inserted records.
        """
        if not provenances:
            return 0
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO provenance "
            "(entity_id, document_id, source, "
            "mention_text, context_snippet, "
            "detected_at, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    p.entity_id,
                    p.document_id,
                    p.source,
                    p.mention_text,
                    p.context_snippet,
                    dt_to_iso(p.detected_at),
                    p.run_id,
                )
                for p in provenances
            ],
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def get_provenance(
        self, entity_id: str
    ) -> list[Provenance]:
        """Fetch all provenance records for an entity.

        :param entity_id: The entity's unique identifier.
        :return: List of provenance records.
        """
        rows = self._conn.execute(
            "SELECT entity_id, document_id, source, "
            "mention_text, context_snippet, "
            "detected_at, run_id "
            "FROM provenance WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()
        return [row_to_provenance(r) for r in rows]

    def find_recent_mentions(
        self,
        entity_id: str,
        since: datetime,
    ) -> list[Provenance]:
        """Fetch provenance records after a given time.

        Returns mentions of the entity detected at or after
        ``since``, ordered by most recent first.

        :param entity_id: The entity's unique identifier.
        :param since: Only return records with
            ``detected_at >= since``.
        :return: List of provenance records.
        """
        rows = self._conn.execute(
            "SELECT entity_id, document_id, source, "
            "mention_text, context_snippet, "
            "detected_at, run_id FROM provenance "
            "WHERE entity_id = ? "
            "AND detected_at >= ? "
            "ORDER BY detected_at DESC",
            (entity_id, dt_to_iso(since)),
        ).fetchall()
        return [row_to_provenance(r) for r in rows]

    # -- Co-mention query --

    def find_co_mentioned(
        self,
        entity_id: str,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[tuple[Entity, int]]:
        """Find entities co-mentioned with the given entity.

        Returns entities that appear in the same documents,
        sorted by co-occurrence count (descending). Each
        result is a ``(Entity, count)`` tuple where count
        is the number of distinct documents they share.

        :param entity_id: The entity to find co-mentions
            for.
        :param since: If set, only consider provenance
            records with ``detected_at >= since``.
        :param limit: Maximum number of co-mentioned
            entities to return. When ``None`` (the
            default), all are returned. Passing a bound
            avoids fetching and batch-loading aliases for
            unbounded result sets on large KGs.
        :return: List of (entity, document_count) tuples.
        """
        query = (
            "SELECT p2.entity_id, "
            "COUNT(DISTINCT p2.document_id) AS cnt, "
            "e.canonical_name, e.entity_type, "
            "e.subtype, e.description, "
            "e.valid_from, e.valid_until, "
            "e.status, e.merged_into, "
            "e.created_at, e.updated_at "
            "FROM provenance p1 "
            "JOIN provenance p2 "
            "ON p1.document_id = p2.document_id "
            "JOIN entities e "
            "ON p2.entity_id = e.entity_id "
            "WHERE p1.entity_id = ? "
            "AND p2.entity_id != ? "
        )
        params: list[str | int | None] = [
            entity_id, entity_id,
        ]
        if since is not None:
            query += "AND p1.detected_at >= ? "
            params.append(dt_to_iso(since))
        query += (
            "GROUP BY p2.entity_id "
            "ORDER BY cnt DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        if not rows:
            return []
        eids = [r["entity_id"] for r in rows]
        alias_map = self._load_aliases_batch(eids)  # type: ignore[attr-defined]
        results: list[tuple[Entity, int]] = []
        for row in rows:
            eid = row["entity_id"]
            entity = row_to_entity(
                row,
                alias_map.get(eid, ()),
            )
            results.append((entity, row["cnt"]))
        return results
