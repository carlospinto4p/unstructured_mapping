"""Provenance and co-mention operations mixin.

Provides provenance CRUD and co-mention queries. Mixed
into :class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`.
"""

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

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

    if TYPE_CHECKING:
        # Provided by ``EntityHelpersMixin`` when composed
        # into ``KnowledgeStore``; declared here so
        # co-mention queries can batch-load aliases
        # without ``# type: ignore[attr-defined]``.
        def _load_aliases_batch(
            self, entity_ids: list[str]
        ) -> dict[str, tuple[str, ...]]: ...

    # -- Provenance CRUD --

    def save_provenance(self, provenance: Provenance) -> None:
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
        self._commit()

    def save_provenances(self, provenances: list[Provenance]) -> int:
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
        self._commit()
        return self._conn.total_changes - before

    def get_provenance(self, entity_id: str) -> list[Provenance]:
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

    def has_document_provenance(self, document_id: str) -> bool:
        """Check whether a document has any provenance.

        Used by the ingestion pipeline for idempotency:
        articles whose ``document_id`` already appears in
        provenance are treated as already processed and
        skipped on re-runs. The ``idx_prov_document``
        index keeps the lookup O(log n).

        :param document_id: The document's string ID.
        :return: ``True`` if at least one provenance row
            references this document.
        """
        row = self._conn.execute(
            "SELECT 1 FROM provenance WHERE document_id = ? LIMIT 1",
            (document_id,),
        ).fetchone()
        return row is not None

    def documents_with_provenance(self, document_ids: list[str]) -> set[str]:
        """Return the subset of ids that already have
        provenance rows.

        Batches the idempotency check the pipeline runs
        for each article in a run: a single ``IN (...)``
        query replaces the per-article round-trip, so a
        1000-article batch goes from 1000 queries to 1.

        :param document_ids: IDs to check. Empty input
            returns an empty set without a query.
        :return: The set of ids that are already present
            in the provenance table.
        """
        if not document_ids:
            return set()
        placeholders = ",".join("?" * len(document_ids))
        rows = self._conn.execute(
            "SELECT DISTINCT document_id FROM provenance "
            f"WHERE document_id IN ({placeholders})",
            document_ids,
        ).fetchall()
        return {row["document_id"] for row in rows}

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

    def count_mentions_for_entity(self, entity_id: str) -> int:
        """Count provenance rows tied to an entity.

        Cheaper than ``len(get_provenance(entity_id))``
        because the hydrated ``Provenance`` rows are
        never materialised. Used by the alias-collision
        audit to rank collisions by mention prevalence.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM provenance WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def count_mentions_for_entities(
        self, entity_ids: list[str]
    ) -> dict[str, int]:
        """Batch ``count_mentions_for_entity`` over many ids.

        One grouped query instead of one query per id. Entities
        with zero mentions are included in the returned dict (as
        ``0``) so callers can use ``result[eid]`` without a
        ``.get(eid, 0)`` guard.

        :param entity_ids: Entity ids to count. Duplicates are
            accepted; the result is keyed by unique id.
        :return: ``{entity_id: mention_count}`` for every id in
            ``entity_ids``.
        """
        if not entity_ids:
            return {}
        unique_ids = list(dict.fromkeys(entity_ids))
        placeholders = ",".join("?" * len(unique_ids))
        rows = self._conn.execute(
            f"SELECT entity_id, COUNT(*) FROM provenance "
            f"WHERE entity_id IN ({placeholders}) "
            f"GROUP BY entity_id",
            unique_ids,
        ).fetchall()
        counts = {eid: 0 for eid in unique_ids}
        for eid, cnt in rows:
            counts[eid] = int(cnt)
        return counts

    def find_mentions_with_entities(
        self, document_id: str
    ) -> list[tuple[Entity, Provenance]]:
        """Return every mention the pipeline produced for
        a document, paired with its entity.

        One row per provenance record: the entity side
        hydrates ``canonical_name`` / ``entity_type`` /
        ``description`` so presentation-layer callers
        (preview CLI, cold-start benchmark) do not need
        a second fetch. Ordered by ``detected_at`` so the
        first row is the first mention, matching how the
        pipeline writes them.

        :param document_id: The document's string id.
        :return: ``(Entity, Provenance)`` tuples. Empty
            when the document has no provenance.
        """
        rows = self._conn.execute(
            "SELECT e.entity_id, e.canonical_name, "
            "e.entity_type, e.subtype, "
            "e.description, e.valid_from, "
            "e.valid_until, e.status, "
            "e.merged_into, e.created_at, "
            "e.updated_at, "
            "p.document_id, p.source, "
            "p.mention_text, p.context_snippet, "
            "p.detected_at, p.run_id "
            "FROM provenance p "
            "JOIN entities e "
            "ON e.entity_id = p.entity_id "
            "WHERE p.document_id = ? "
            "ORDER BY p.detected_at",
            (document_id,),
        ).fetchall()
        if not rows:
            return []
        eids = [r["entity_id"] for r in rows]
        alias_map = self._load_aliases_batch(eids)
        results: list[tuple[Entity, Provenance]] = []
        for row in rows:
            eid = row["entity_id"]
            entity = row_to_entity(row, alias_map.get(eid, ()))
            provenance = row_to_provenance(row)
            results.append((entity, provenance))
        return results

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
            entity_id,
            entity_id,
        ]
        if since is not None:
            query += "AND p1.detected_at >= ? "
            params.append(dt_to_iso(since))
        query += "GROUP BY p2.entity_id ORDER BY cnt DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        if not rows:
            return []
        eids = [r["entity_id"] for r in rows]
        alias_map = self._load_aliases_batch(eids)
        results: list[tuple[Entity, int]] = []
        for row in rows:
            eid = row["entity_id"]
            entity = row_to_entity(
                row,
                alias_map.get(eid, ()),
            )
            results.append((entity, row["cnt"]))
        return results
