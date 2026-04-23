"""Entity CRUD and name/alias lookup mixin.

Save, get, and basic name/alias queries. Split out of
:mod:`._entity_mixin` once that module crossed the point
where four mixin classes in one file was friction.

The search, merge, and history mixins live alongside in
their own files and are composed together in
:class:`._entity_mixin.EntityMixin`.
"""

import logging
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph._entity_helpers import (
    EntityHelpersMixin,
)
from unstructured_mapping.knowledge_graph._helpers import (
    ENTITY_SELECT,
    ENTITY_SELECT_ALIASED,
    dt_to_iso,
    iso_to_dt,
    row_to_entity,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityType,
)
from unstructured_mapping.knowledge_graph.validation import (
    validate_temporal,
)

logger = logging.getLogger(__name__)


class EntityCRUDMixin(EntityHelpersMixin):
    """Create, read, update, and basic name/alias lookup."""

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

        Timestamps are owned by the storage layer, not the
        caller. ``updated_at`` is stamped on every save
        with the current UTC time. ``created_at`` is set
        once, on the first save; subsequent saves preserve
        the original value regardless of what the caller
        passes. A caller-provided ``created_at`` on a brand
        new entity is respected, which is useful for
        backfills and history-preserving imports.

        :param entity: The entity to save.
        :param reason: Optional explanation logged in the
            audit trail.
        """
        validate_temporal(entity)
        existing_row = self._conn.execute(
            "SELECT created_at FROM entities WHERE entity_id = ?",
            (entity.entity_id,),
        ).fetchone()
        is_update = existing_row is not None
        if _operation is None:
            _operation = "update" if is_update else "create"
        operation = _operation

        now = datetime.now(timezone.utc)
        if is_update:
            created_at = (
                iso_to_dt(existing_row[0]) or entity.created_at or now
            )
        else:
            created_at = entity.created_at or now
        updated_at = now

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
                dt_to_iso(created_at),
                dt_to_iso(updated_at),
            ),
        )
        self._sync_aliases(entity.entity_id, entity.aliases)
        self._log_entity(entity, operation, reason)
        self._commit()

    def get_entity(self, entity_id: str) -> Entity | None:
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

    def get_entities(self, entity_ids: list[str]) -> dict[str, Entity]:
        """Batch-load entities by id.

        Single ``WHERE entity_id IN (...)`` query plus one
        alias fetch, vs. N round-trips for a per-id loop.
        Callers that resolve many candidates per chunk
        (e.g. the LLM resolver) should prefer this over
        a loop of :meth:`get_entity`.

        :param entity_ids: Ids to look up. Order does not
            matter; duplicates are deduplicated before
            hitting SQLite.
        :return: ``{entity_id: Entity}`` for every id that
            resolved. Missing ids are silently absent — no
            exception — so callers keep the per-id
            "candidate may have been deleted" semantics.
        """
        unique_ids = list({eid for eid in entity_ids})
        if not unique_ids:
            return {}
        placeholders = ",".join("?" * len(unique_ids))
        rows = self._conn.execute(
            ENTITY_SELECT + f"WHERE entity_id IN ({placeholders})",
            unique_ids,
        ).fetchall()
        entities = self._rows_to_entities(rows)
        return {e.entity_id: e for e in entities}

    def find_by_name(self, name: str) -> list[Entity]:
        """Find entities whose canonical name matches.

        Case-insensitive search.

        :param name: Name to search for.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            ENTITY_SELECT + "WHERE canonical_name COLLATE NOCASE = ?",
            (name,),
        ).fetchall()
        return self._rows_to_entities(rows)

    def exists_by_name_and_type(
        self,
        name: str,
        entity_type: EntityType,
    ) -> bool:
        """Return True if a name+type match exists.

        Uses the composite index
        ``idx_entity_name_type (canonical_name, entity_type)``
        so SQLite can resolve the lookup without scanning
        the alias table or returning the full row. This
        is the hot path for seed-import dedup (every
        candidate runs this check).
        """
        row = self._conn.execute(
            "SELECT 1 FROM entities "
            "WHERE canonical_name COLLATE NOCASE = ? "
            "AND entity_type = ? "
            "LIMIT 1",
            (name, entity_type.value),
        ).fetchone()
        return row is not None

    def backfill_entity_timestamps(self) -> int:
        """Fill NULL ``created_at`` / ``updated_at`` on
        existing rows from the audit history.

        Written to correct databases that were populated
        before the storage layer started stamping
        timestamps automatically. For each affected entity
        we use the ``entity_history`` row with
        ``operation = 'create'`` as the authoritative
        creation time, and mirror it into ``updated_at``.
        Rows whose history has been purged (no ``create``
        record remains) are left untouched.

        Safe to re-run — rows that already have non-NULL
        timestamps are skipped. Intended for one-shot use
        during migration; production entity writes never
        need this.

        :return: Number of rows updated.
        """
        rows = self._conn.execute(
            "SELECT e.entity_id, h.changed_at "
            "FROM entities e "
            "JOIN entity_history h "
            "  ON h.entity_id = e.entity_id "
            "WHERE (e.created_at IS NULL "
            "       OR e.updated_at IS NULL) "
            "  AND h.operation = 'create'"
        ).fetchall()
        if not rows:
            return 0
        self._conn.executemany(
            "UPDATE entities "
            "SET created_at = COALESCE(created_at, ?), "
            "    updated_at = COALESCE(updated_at, ?) "
            "WHERE entity_id = ?",
            [
                (row["changed_at"], row["changed_at"], row["entity_id"])
                for row in rows
            ],
        )
        self._commit()
        return len(rows)

    def find_by_alias(self, alias: str) -> list[Entity]:
        """Find entities that have a matching alias.

        Case-insensitive search.

        :param alias: Alias to search for.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            ENTITY_SELECT_ALIASED + "JOIN entity_aliases a "
            "ON e.entity_id = a.entity_id "
            "WHERE a.alias COLLATE NOCASE = ?",
            (alias,),
        ).fetchall()
        return self._rows_to_entities(rows)

    def alias_exists(self, alias: str) -> bool:
        """Return True if any entity carries this alias.

        Cheaper than :meth:`find_by_alias` when the caller
        only needs existence: no JOIN to ``entities`` and
        no row-to-Entity conversion. Used by the Wikidata
        seed loader's QID dedup check, which runs once per
        candidate.
        """
        row = self._conn.execute(
            "SELECT 1 FROM entity_aliases "
            "WHERE alias COLLATE NOCASE = ? LIMIT 1",
            (alias,),
        ).fetchone()
        return row is not None

    def wikidata_qids(self) -> set[str]:
        """Return every Wikidata QID currently carried as an alias.

        QIDs are stored as ``wikidata:Q…`` aliases; this method
        returns the bare ``Q…`` part so callers can compare
        against ``MappedEntity.qid`` directly. Bulk dedup helper
        for the Wikidata seed loader, which otherwise calls
        :meth:`alias_exists` once per candidate.

        :return: Set of QIDs (e.g. ``{"Q312", "Q95"}``). Empty
            when the KG has no Wikidata-sourced entities.
        """
        rows = self._conn.execute(
            "SELECT SUBSTR(alias, 10) FROM entity_aliases "
            "WHERE alias LIKE 'wikidata:Q%'"
        ).fetchall()
        return {r[0] for r in rows}

    def name_type_pairs(self) -> set[tuple[str, str]]:
        """Return ``(canonical_name.lower(), entity_type)`` for every entity.

        Mirrors the dedup key used by
        :meth:`exists_by_name_and_type` (case-insensitive name
        match + exact type match). Letting the seed loader
        prefetch this set once turns its per-candidate
        duplicate check into an O(1) ``in`` probe.

        :return: Set of ``(lowered_name, entity_type_value)``
            tuples. Values match :class:`EntityType.value`, not
            the enum itself, so callers use
            ``entity.entity_type.value`` on the lookup side.
        """
        rows = self._conn.execute(
            "SELECT canonical_name, entity_type FROM entities"
        ).fetchall()
        return {(name.lower(), etype) for name, etype in rows}
