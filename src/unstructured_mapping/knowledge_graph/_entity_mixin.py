"""Entity operations mixin for KnowledgeStore.

Provides CRUD, search, merge, and audit history methods
for entities. Mixed into
:class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`.
"""

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime

from unstructured_mapping.knowledge_graph._helpers import (
    ENTITY_SELECT,
    ENTITY_SELECT_ALIASED,
    dt_to_iso,
    now_iso,
    row_to_entity,
    row_to_entity_rev,
)
from unstructured_mapping.knowledge_graph.exceptions import (
    EntityNotFound,
    RevisionNotFound,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityRevision,
    EntityStatus,
    EntityType,
)

logger = logging.getLogger(__name__)


class EntityMixin:
    """Entity operations for :class:`KnowledgeStore`."""

    _conn: sqlite3.Connection

    # -- Entity CRUD --

    def save_entity(
        self,
        entity: Entity,
        *,
        reason: str | None = None,
        _operation: str | None = None,
    ) -> None:
        """Insert or update an entity.

        Aliases are synced: old aliases removed, new ones
        added. A snapshot is written to ``entity_history``
        for every operation.

        :param entity: The entity to save.
        :param reason: Optional explanation logged in the
            audit trail.
        """
        if _operation is None:
            existing = self._conn.execute(
                "SELECT 1 FROM entities "
                "WHERE entity_id = ?",
                (entity.entity_id,),
            ).fetchone()
            _operation = (
                "update" if existing else "create"
            )
        operation = _operation
        self._conn.execute(
            "INSERT OR REPLACE INTO entities "
            "(entity_id, canonical_name, entity_type, "
            "subtype, description, valid_from, "
            "valid_until, status, merged_into, "
            "created_at, updated_at) "
            "VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entity.entity_id,
                entity.canonical_name,
                entity.entity_type.value,
                entity.subtype,
                entity.description,
                dt_to_iso(entity.valid_from),
                dt_to_iso(entity.valid_until),
                entity.status.value,
                entity.merged_into,
                dt_to_iso(entity.created_at),
                dt_to_iso(entity.updated_at),
            ),
        )
        self._sync_aliases(
            entity.entity_id, entity.aliases
        )
        self._log_entity(entity, operation, reason)
        self._conn.commit()

    def get_entity(
        self, entity_id: str
    ) -> Entity | None:
        """Fetch an entity by its ID.

        :param entity_id: The entity's unique identifier.
        :return: The entity, or ``None`` if not found.
        """
        row = self._conn.execute(
            ENTITY_SELECT + "WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        aliases = self._load_aliases(entity_id)
        return row_to_entity(row, aliases)

    def find_by_name(
        self, name: str
    ) -> list[Entity]:
        """Find entities whose canonical name matches.

        Case-insensitive search.

        :param name: Name to search for.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            ENTITY_SELECT
            + "WHERE canonical_name COLLATE NOCASE = ?",
            (name,),
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_by_alias(
        self, alias: str
    ) -> list[Entity]:
        """Find entities that have a matching alias.

        Case-insensitive search.

        :param alias: Alias to search for.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            ENTITY_SELECT_ALIASED
            + "JOIN entity_aliases a "
            "ON e.entity_id = a.entity_id "
            "WHERE a.alias COLLATE NOCASE = ?",
            (alias,),
        ).fetchall()
        return self._rows_to_entities(rows)

    # -- Entity search --

    def find_entities_by_type(
        self,
        entity_type: EntityType,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find all entities of a given type.

        :param entity_type: The type to filter by.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned. Large KGs should pass a bound to
            avoid loading unbounded result sets and
            unnecessary alias lookups.
        :return: Matching entities.
        """
        query = ENTITY_SELECT + "WHERE entity_type = ?"
        params: list[str | int] = [entity_type.value]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_entities_by_subtype(
        self,
        entity_type: EntityType,
        subtype: str,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find entities by type and subtype.

        :param entity_type: The type to filter by.
        :param subtype: The subtype to filter by.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned.
        :return: Matching entities.
        """
        query = (
            ENTITY_SELECT
            + "WHERE entity_type = ? AND subtype = ?"
        )
        params: list[str | int] = [
            entity_type.value,
            subtype,
        ]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_entities_by_status(
        self,
        status: EntityStatus,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find all entities with a given status.

        Useful for listing only ACTIVE entities or finding
        all MERGED/DEPRECATED ones.

        :param status: The status to filter by.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned.
        :return: Matching entities.
        """
        query = ENTITY_SELECT + "WHERE status = ?"
        params: list[str | int] = [status.value]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_by_name_prefix(
        self,
        prefix: str,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find entities whose name starts with a prefix.

        Case-insensitive prefix search for
        autocomplete/typeahead lookups.

        :param prefix: The prefix to match against
            ``canonical_name``.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned. Typeahead callers typically pass a
            small bound (e.g. 10).
        :return: Matching entities.
        """
        query = (
            ENTITY_SELECT
            + "WHERE canonical_name "
            "COLLATE NOCASE LIKE ? || '%'"
        )
        params: list[str | int] = [prefix]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        return self._rows_to_entities(rows)

    def count_entities_by_type(
        self,
    ) -> dict[str, int]:
        """Count entities grouped by type.

        Returns a mapping of entity type to count,
        useful for dashboard stats without fetching
        all rows.

        :return: Mapping of type string to count.
        """
        rows = self._conn.execute(
            "SELECT entity_type, COUNT(*) "
            "FROM entities GROUP BY entity_type"
        ).fetchall()
        return {t: c for t, c in rows}

    def find_entities_since(
        self,
        since: datetime,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find entities created after a given time.

        Returns entities with ``created_at >= since``,
        ordered most recent first. Useful for new-entity
        monitoring ("what was added to the KG today?").

        :param since: Only return entities created at or
            after this datetime.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned.
        :return: Matching entities, newest first.
        """
        query = (
            ENTITY_SELECT
            + "WHERE created_at >= ? "
            "ORDER BY created_at DESC"
        )
        params: list[str | int | None] = [
            dt_to_iso(since)
        ]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        return self._rows_to_entities(rows)

    # -- Merge operation --

    def merge_entities(
        self,
        deprecated_id: str,
        surviving_id: str,
    ) -> None:
        """Merge one entity into another.

        Updates all foreign key references (provenance,
        relationships) to point to the surviving entity,
        then marks the deprecated entity as MERGED.

        Both entities and all affected relationships are
        logged to the audit history.

        Runs in a single transaction for atomicity.

        :param deprecated_id: Entity to deprecate.
        :param surviving_id: Entity that absorbs the
            deprecated one.
        :raises EntityNotFound: If either entity is not
            found.
        """
        dep = self.get_entity(deprecated_id)
        surv = self.get_entity(surviving_id)
        for entity, eid in (
            (dep, deprecated_id),
            (surv, surviving_id),
        ):
            if entity is None:
                raise EntityNotFound(eid)

        merge_reason = (
            f"merged {deprecated_id} into "
            f"{surviving_id}"
        )

        self._redirect_entity_references(
            deprecated_id, surviving_id
        )
        self._conn.execute(
            "UPDATE entities SET status = ?, "
            "merged_into = ? WHERE entity_id = ?",
            ("merged", surviving_id, deprecated_id),
        )
        merged_dep = replace(
            dep,  # type: ignore[arg-type]
            status=EntityStatus.MERGED,
            merged_into=surviving_id,
        )
        self._log_entity(
            merged_dep, "merge", merge_reason
        )
        self._log_entity(
            surv, "merge", merge_reason  # type: ignore[arg-type]
        )
        self._conn.commit()
        logger.info(
            "Merged entity %s into %s",
            deprecated_id,
            surviving_id,
        )

    # -- History queries --

    def get_entity_history(
        self, entity_id: str
    ) -> list[EntityRevision]:
        """Fetch all revisions for an entity.

        Returns revisions in chronological order
        (oldest first).

        :param entity_id: The entity's unique identifier.
        :return: List of revisions.
        """
        rows = self._conn.execute(
            "SELECT revision_id, entity_id, operation,"
            " changed_at, canonical_name, entity_type,"
            " subtype, description, aliases, "
            "valid_from, valid_until, status, "
            "merged_into, reason "
            "FROM entity_history "
            "WHERE entity_id = ? "
            "ORDER BY revision_id",
            (entity_id,),
        ).fetchall()
        return [row_to_entity_rev(r) for r in rows]

    def get_entity_at(
        self,
        entity_id: str,
        at: datetime,
    ) -> EntityRevision | None:
        """Fetch an entity's state at a point in time.

        Returns the latest revision with
        ``changed_at <= at``.

        :param entity_id: The entity's unique identifier.
        :param at: The point in time to query.
        :return: The revision, or ``None`` if the entity
            did not exist at that time.
        """
        row = self._conn.execute(
            "SELECT revision_id, entity_id, operation,"
            " changed_at, canonical_name, entity_type,"
            " subtype, description, aliases, "
            "valid_from, valid_until, status, "
            "merged_into, reason "
            "FROM entity_history "
            "WHERE entity_id = ? "
            "AND changed_at <= ? "
            "ORDER BY revision_id DESC LIMIT 1",
            (entity_id, dt_to_iso(at)),
        ).fetchone()
        if row is None:
            return None
        return row_to_entity_rev(row)

    def revert_entity(
        self, entity_id: str, revision_id: int
    ) -> Entity:
        """Revert an entity to a previous revision.

        Copies the snapshot from ``entity_history`` back
        to ``entities`` and logs a ``"revert"`` operation
        in the audit trail.

        :param entity_id: The entity to revert.
        :param revision_id: The revision to restore.
        :return: The restored entity.
        :raises RevisionNotFound: If the revision is not
            found or belongs to a different entity.
        """
        row = self._conn.execute(
            "SELECT revision_id, entity_id, operation,"
            " changed_at, canonical_name, entity_type,"
            " subtype, description, aliases, "
            "valid_from, valid_until, status, "
            "merged_into, reason "
            "FROM entity_history "
            "WHERE revision_id = ? "
            "AND entity_id = ?",
            (revision_id, entity_id),
        ).fetchone()
        if row is None:
            raise RevisionNotFound(
                revision_id, entity_id
            )
        rev = row_to_entity_rev(row)
        restored = Entity(
            entity_id=rev.entity_id,
            canonical_name=rev.canonical_name,
            entity_type=rev.entity_type,
            subtype=rev.subtype,
            description=rev.description,
            aliases=rev.aliases,
            valid_from=rev.valid_from,
            valid_until=rev.valid_until,
            status=rev.status,
            merged_into=rev.merged_into,
        )
        self.save_entity(
            restored,
            reason=f"reverted to revision {revision_id}",
            _operation="revert",
        )
        return restored

    # -- Internal helpers --

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

    def _log_entity(
        self,
        entity: Entity,
        operation: str,
        reason: str | None,
    ) -> None:
        aliases_json = json.dumps(list(entity.aliases))
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
        """Fetch aliases for multiple entities in one query.

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
