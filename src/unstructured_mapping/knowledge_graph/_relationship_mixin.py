"""Relationship operations mixin for KnowledgeStore.

Provides relationship CRUD, qualifier/kind queries,
active-relationship filtering, and audit history. Mixed
into :class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`.
"""

import sqlite3

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
        before = self._conn.total_changes
        self._conn.execute(
            "INSERT OR IGNORE INTO relationships "
            "(source_id, target_id, relation_type, "
            "description, qualifier_id, "
            "relation_kind_id, valid_from, "
            "valid_until, document_id, "
            "discovered_at, run_id)"
            " VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                relationship.source_id,
                relationship.target_id,
                relationship.relation_type,
                relationship.description,
                relationship.qualifier_id,
                relationship.relation_kind_id,
                dt_to_iso(relationship.valid_from)
                or "",
                dt_to_iso(relationship.valid_until),
                relationship.document_id,
                dt_to_iso(relationship.discovered_at),
                relationship.run_id,
            ),
        )
        inserted = self._conn.total_changes - before
        if inserted > 0:
            self._log_relationship(
                relationship, "create", reason
            )
        self._conn.commit()

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
            results.extend(
                row_to_relationship(r) for r in rows
            )
        if as_target:
            rows = self._conn.execute(
                REL_SELECT + "WHERE target_id = ?",
                (entity_id,),
            ).fetchall()
            results.extend(
                row_to_relationship(r) for r in rows
            )
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
            REL_SELECT
            + "WHERE source_id = ? "
            "AND target_id = ?",
            (source_id, target_id),
        ).fetchall()
        return [row_to_relationship(r) for r in rows]

    def find_by_qualifier(
        self, qualifier_id: str
    ) -> list[Relationship]:
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
            REL_SELECT
            + "WHERE relation_kind_id = ?",
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
            REL_SELECT
            + "WHERE relation_type = ?",
            (relation_type,),
        ).fetchall()
        return [row_to_relationship(r) for r in rows]

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
                REL_SELECT
                + f"WHERE {col} = ? "
                "AND (valid_until IS NULL "
                "OR valid_until = '' "
                "OR valid_until > ?)",
                (entity_id, now),
            ).fetchall()
            results.extend(
                row_to_relationship(r) for r in rows
            )
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
            "SELECT revision_id, operation, "
            "changed_at, source_id, target_id, "
            "relation_type, description, qualifier_id,"
            " relation_kind_id, valid_from, "
            "valid_until, document_id, reason "
            "FROM relationship_history "
            "WHERE source_id = ? OR target_id = ? "
            "ORDER BY revision_id",
            (entity_id, entity_id),
        ).fetchall()
        return [
            row_to_relationship_rev(r) for r in rows
        ]

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
