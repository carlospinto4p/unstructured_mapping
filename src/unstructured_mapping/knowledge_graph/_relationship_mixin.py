"""Relationship operations mixin for KnowledgeStore.

Provides relationship CRUD, qualifier/kind queries,
active-relationship filtering, and audit history. Mixed
into :class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`.
"""

import sqlite3
from datetime import datetime

from unstructured_mapping.knowledge_graph._helpers import (
    REL_SELECT,
    dt_to_iso,
    now_iso,
    row_to_relationship,
    row_to_relationship_rev,
)
from unstructured_mapping.knowledge_graph.models import (
    Relationship,
    RelationshipRevision,
)
from unstructured_mapping.knowledge_graph.validation import (
    validate_temporal,
)


class RelationshipMixin:
    """Relationship operations for :class:`KnowledgeStore`."""

    _conn: sqlite3.Connection

    # -- Relationship CRUD --

    def save_relationship(
        self,
        relationship: Relationship,
        *,
        reason: str | None = None,
    ) -> None:
        """Insert a relationship, skipping duplicates.

        A snapshot is written to ``relationship_history``
        when a new relationship is created (duplicates
        are silently skipped).

        :param relationship: The relationship to save.
        :param reason: Optional explanation logged in the
            audit trail.
        """
        validate_temporal(relationship)
        before = self._conn.total_changes
        self._conn.execute(
            "INSERT OR IGNORE INTO relationships "
            "(source_id, target_id, relation_type, "
            "description, qualifier_id, "
            "relation_kind_id, valid_from, "
            "valid_until, document_id, "
            "discovered_at, run_id, confidence)"
            " VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                relationship.source_id,
                relationship.target_id,
                relationship.relation_type,
                relationship.description,
                relationship.qualifier_id,
                relationship.relation_kind_id,
                dt_to_iso(relationship.valid_from) or "",
                dt_to_iso(relationship.valid_until),
                relationship.document_id,
                dt_to_iso(relationship.discovered_at),
                relationship.run_id,
                relationship.confidence,
            ),
        )
        inserted = self._conn.total_changes - before
        if inserted > 0:
            self._log_relationship(relationship, "create", reason)
        self._commit()

    def save_relationships(
        self,
        relationships: list[Relationship],
        *,
        reason: str | None = None,
    ) -> int:
        """Bulk insert relationships, skipping duplicates.

        Uses ``executemany`` to avoid the per-record commit
        overhead of calling :meth:`save_relationship` in a
        loop. Duplicates (same primary key:
        ``source_id, target_id, relation_type, valid_from``)
        are silently skipped, matching
        :meth:`save_relationship` semantics. Each newly
        inserted relationship is logged to
        ``relationship_history``.

        Input is also deduplicated against itself so the
        same relationship appearing twice in the list is
        inserted and logged once.

        :param relationships: The relationships to save.
        :param reason: Optional explanation logged in the
            audit trail for every newly inserted record.
        :return: Number of newly inserted records.
        """
        if not relationships:
            return 0
        for rel in relationships:
            validate_temporal(rel)
        # Dedupe input by PK, then filter out rows already
        # present in the DB. This lets us insert + log only
        # genuinely new rows, since executemany does not
        # report per-row insertion status.
        seen: set[tuple[str, str, str, str]] = set()
        candidates: list[Relationship] = []
        for rel in relationships:
            key = (
                rel.source_id,
                rel.target_id,
                rel.relation_type,
                dt_to_iso(rel.valid_from) or "",
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(rel)
        new_rels = [
            rel
            for rel in candidates
            if self._conn.execute(
                "SELECT 1 FROM relationships "
                "WHERE source_id = ? "
                "AND target_id = ? "
                "AND relation_type = ? "
                "AND valid_from = ?",
                (
                    rel.source_id,
                    rel.target_id,
                    rel.relation_type,
                    dt_to_iso(rel.valid_from) or "",
                ),
            ).fetchone()
            is None
        ]
        if not new_rels:
            return 0
        self._conn.executemany(
            "INSERT INTO relationships "
            "(source_id, target_id, relation_type, "
            "description, qualifier_id, "
            "relation_kind_id, valid_from, "
            "valid_until, document_id, "
            "discovered_at, run_id, confidence) "
            "VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r.source_id,
                    r.target_id,
                    r.relation_type,
                    r.description,
                    r.qualifier_id,
                    r.relation_kind_id,
                    dt_to_iso(r.valid_from) or "",
                    dt_to_iso(r.valid_until),
                    r.document_id,
                    dt_to_iso(r.discovered_at),
                    r.run_id,
                    r.confidence,
                )
                for r in new_rels
            ],
        )
        for rel in new_rels:
            self._log_relationship(rel, "create", reason)
        self._commit()
        return len(new_rels)

    def get_relationships(
        self,
        entity_id: str,
        as_source: bool = True,
        as_target: bool = True,
    ) -> list[Relationship]:
        """Fetch relationships involving an entity.

        :param entity_id: The entity's unique identifier.
        :param as_source: Include relationships where the
            entity is the source.
        :param as_target: Include relationships where the
            entity is the target.
        :return: List of relationships.
        """
        results: list[Relationship] = []
        if as_source:
            rows = self._conn.execute(
                REL_SELECT + "WHERE source_id = ?",
                (entity_id,),
            ).fetchall()
            results.extend(row_to_relationship(r) for r in rows)
        if as_target:
            rows = self._conn.execute(
                REL_SELECT + "WHERE target_id = ?",
                (entity_id,),
            ).fetchall()
            results.extend(row_to_relationship(r) for r in rows)
        return results

    def get_relationships_between(
        self,
        source_id: str,
        target_id: str,
    ) -> list[Relationship]:
        """Fetch all relationships between two entities.

        Returns relationships where ``source_id`` is the
        source and ``target_id`` is the target. Does not
        return the reverse direction -- call again with
        swapped arguments if needed.

        :param source_id: The source entity's ID.
        :param target_id: The target entity's ID.
        :return: Matching relationships.
        """
        rows = self._conn.execute(
            REL_SELECT + "WHERE source_id = ? AND target_id = ?",
            (source_id, target_id),
        ).fetchall()
        return [row_to_relationship(r) for r in rows]

    def find_by_qualifier(self, qualifier_id: str) -> list[Relationship]:
        """Find relationships with a given qualifier.

        Typically used to find all relationships qualified
        by a specific ROLE entity (e.g. all CTOs).

        :param qualifier_id: Entity ID of the qualifier.
        :return: Matching relationships.
        """
        rows = self._conn.execute(
            REL_SELECT + "WHERE qualifier_id = ?",
            (qualifier_id,),
        ).fetchall()
        return [row_to_relationship(r) for r in rows]

    def find_by_relation_kind(
        self, relation_kind_id: str
    ) -> list[Relationship]:
        """Find relationships of a normalized kind.

        Returns all relationships linked to the given
        RELATION_KIND entity, regardless of the raw
        `relation_type` string.

        :param relation_kind_id: Entity ID of the kind.
        :return: Matching relationships.
        """
        rows = self._conn.execute(
            REL_SELECT + "WHERE relation_kind_id = ?",
            (relation_kind_id,),
        ).fetchall()
        return [row_to_relationship(r) for r in rows]

    def find_relationships_by_type(
        self, relation_type: str
    ) -> list[Relationship]:
        """Find relationships by raw ``relation_type``.

        Filters on the free-form string before any
        RELATION_KIND normalization. Case-sensitive match.

        :param relation_type: The relation type string to
            filter by (e.g. ``"acquired"``, ``"works_at"``).
        :return: Matching relationships.
        """
        rows = self._conn.execute(
            REL_SELECT + "WHERE relation_type = ?",
            (relation_type,),
        ).fetchall()
        return [row_to_relationship(r) for r in rows]

    def find_relationships(
        self,
        entity_id: str,
        *,
        as_source: bool = True,
        as_target: bool = True,
        at: datetime | None = None,
        min_confidence: float | None = None,
    ) -> list[Relationship]:
        """Fetch relationships with temporal / confidence
        filters.

        Generalises :meth:`get_relationships` and
        :meth:`find_active_relationships`: when neither
        filter is supplied the result matches
        :meth:`get_relationships`; when ``at`` is set,
        only rows that were in force at that instant
        survive (``valid_from <= at`` and
        ``valid_until IS NULL`` or ``valid_until >= at``);
        when ``min_confidence`` is set, rows with a lower
        or missing confidence score are dropped.

        :param entity_id: Entity to match on source or
            target.
        :param as_source: Include rows where this is the
            source.
        :param as_target: Include rows where this is the
            target.
        :param at: Temporal cut — ``None`` for "no
            temporal filter". Missing ``valid_from``
            values (stored as ``""``) are treated as
            "unbounded on the left" and always pass.
        :param min_confidence: Drop rows whose
            ``confidence`` is below this threshold or
            ``NULL``. ``None`` disables the filter.
        :return: Matching relationships.
        """
        clauses: list[str] = []
        params: list[object] = []
        if at is not None:
            at_iso = dt_to_iso(at)
            clauses.append(
                "(valid_from IS NULL OR valid_from = '' OR valid_from <= ?)"
            )
            params.append(at_iso)
            clauses.append(
                "(valid_until IS NULL "
                "OR valid_until = '' "
                "OR valid_until >= ?)"
            )
            params.append(at_iso)
        if min_confidence is not None:
            clauses.append("confidence IS NOT NULL AND confidence >= ?")
            params.append(min_confidence)
        extra = " AND " + " AND ".join(clauses) if clauses else ""
        results: list[Relationship] = []
        for col, include in (
            ("source_id", as_source),
            ("target_id", as_target),
        ):
            if not include:
                continue
            rows = self._conn.execute(
                REL_SELECT + f"WHERE {col} = ?" + extra,
                (entity_id, *params),
            ).fetchall()
            results.extend(row_to_relationship(r) for r in rows)
        return results

    def find_active_relationships(
        self,
        entity_id: str,
        as_source: bool = True,
        as_target: bool = True,
    ) -> list[Relationship]:
        """Fetch currently active relationships.

        Returns relationships where ``valid_until`` is
        ``None`` (unbounded) or in the future. Useful for
        "current state" queries like "who is the current
        CEO?" or "which sanctions are in effect?"

        :param entity_id: The entity's unique identifier.
        :param as_source: Include relationships where the
            entity is the source.
        :param as_target: Include relationships where the
            entity is the target.
        :return: Active relationships.
        """
        now = now_iso()
        results: list[Relationship] = []
        for col, include in (
            ("source_id", as_source),
            ("target_id", as_target),
        ):
            if not include:
                continue
            rows = self._conn.execute(
                REL_SELECT + f"WHERE {col} = ? "
                "AND (valid_until IS NULL "
                "OR valid_until = '' "
                "OR valid_until > ?)",
                (entity_id, now),
            ).fetchall()
            results.extend(row_to_relationship(r) for r in rows)
        return results

    # -- History queries --

    def get_relationship_history(
        self,
        entity_id: str,
    ) -> list[RelationshipRevision]:
        """Fetch relationship revisions involving an entity.

        Returns revisions where the entity appears as
        source or target, in chronological order.

        :param entity_id: The entity's unique identifier.
        :return: List of relationship revisions.
        """
        rows = self._conn.execute(
            "SELECT history_id, operation, "
            "changed_at, source_id, target_id, "
            "relation_type, description, qualifier_id,"
            " relation_kind_id, valid_from, "
            "valid_until, document_id, reason "
            "FROM relationship_history "
            "WHERE source_id = ? OR target_id = ? "
            "ORDER BY history_id",
            (entity_id, entity_id),
        ).fetchall()
        return [row_to_relationship_rev(r) for r in rows]

    # -- Internal helpers --

    def _log_relationship(
        self,
        rel: Relationship,
        operation: str,
        reason: str | None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO relationship_history "
            "(operation, changed_at, source_id, "
            "target_id, relation_type, description, "
            "qualifier_id, relation_kind_id, "
            "valid_from, valid_until, document_id, "
            "reason) "
            "VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                operation,
                now_iso(),
                rel.source_id,
                rel.target_id,
                rel.relation_type,
                rel.description,
                rel.qualifier_id,
                rel.relation_kind_id,
                dt_to_iso(rel.valid_from) or "",
                dt_to_iso(rel.valid_until),
                rel.document_id,
                reason,
            ),
        )
