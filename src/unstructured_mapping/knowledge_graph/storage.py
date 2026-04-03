"""SQLite storage for the knowledge graph.

Extends :class:`~unstructured_mapping.storage_base.SQLiteStore`
with knowledge-graph-specific tables, migrations, and queries.

See ``docs/knowledge_graph/`` for table schema rationale.
"""

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from unstructured_mapping.knowledge_graph.exceptions import (
    EntityNotFound,
    RevisionNotFound,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityRevision,
    EntityStatus,
    EntityType,
    Provenance,
    Relationship,
    RelationshipRevision,
)
from unstructured_mapping.storage_base import SQLiteStore

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/knowledge.db")

_CREATE_ENTITIES = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    subtype        TEXT,
    description    TEXT NOT NULL,
    valid_from     TEXT,
    valid_until    TEXT,
    status         TEXT NOT NULL DEFAULT 'active',
    merged_into    TEXT,
    created_at     TEXT,
    updated_at     TEXT
)
"""

_CREATE_ALIASES = """
CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id TEXT NOT NULL,
    alias     TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias),
    FOREIGN KEY (entity_id)
        REFERENCES entities (entity_id)
)
"""

_CREATE_PROVENANCE = """
CREATE TABLE IF NOT EXISTS provenance (
    entity_id       TEXT NOT NULL,
    document_id     TEXT NOT NULL,
    source          TEXT NOT NULL,
    mention_text    TEXT NOT NULL,
    context_snippet TEXT NOT NULL,
    detected_at     TEXT,
    PRIMARY KEY (entity_id, document_id, mention_text),
    FOREIGN KEY (entity_id)
        REFERENCES entities (entity_id)
)
"""

_CREATE_RELATIONSHIPS = """
CREATE TABLE IF NOT EXISTS relationships (
    source_id        TEXT NOT NULL,
    target_id        TEXT NOT NULL,
    relation_type    TEXT NOT NULL,
    description      TEXT NOT NULL,
    qualifier_id     TEXT,
    relation_kind_id TEXT,
    valid_from       TEXT,
    valid_until      TEXT,
    document_id      TEXT,
    discovered_at    TEXT,
    PRIMARY KEY (
        source_id, target_id,
        relation_type, valid_from
    ),
    FOREIGN KEY (source_id)
        REFERENCES entities (entity_id),
    FOREIGN KEY (target_id)
        REFERENCES entities (entity_id),
    FOREIGN KEY (qualifier_id)
        REFERENCES entities (entity_id),
    FOREIGN KEY (relation_kind_id)
        REFERENCES entities (entity_id)
)
"""

_CREATE_ENTITY_HISTORY = """
CREATE TABLE IF NOT EXISTS entity_history (
    revision_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id      TEXT NOT NULL,
    operation      TEXT NOT NULL,
    changed_at     TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    subtype        TEXT,
    description    TEXT NOT NULL,
    aliases        TEXT,
    valid_from     TEXT,
    valid_until    TEXT,
    status         TEXT NOT NULL,
    merged_into    TEXT,
    reason         TEXT
)
"""

_CREATE_RELATIONSHIP_HISTORY = """
CREATE TABLE IF NOT EXISTS relationship_history (
    revision_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation        TEXT NOT NULL,
    changed_at       TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    target_id        TEXT NOT NULL,
    relation_type    TEXT NOT NULL,
    description      TEXT NOT NULL,
    qualifier_id     TEXT,
    relation_kind_id TEXT,
    valid_from       TEXT,
    valid_until      TEXT,
    document_id      TEXT,
    reason           TEXT
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_entity_type "
    "ON entities (entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_entity_type_subtype "
    "ON entities (entity_type, subtype)",
    "CREATE INDEX IF NOT EXISTS idx_entity_status "
    "ON entities (status)",
    "CREATE INDEX IF NOT EXISTS idx_entity_name "
    "ON entities (canonical_name COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_entity_created "
    "ON entities (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_alias_lookup "
    "ON entity_aliases (alias COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_prov_document "
    "ON provenance (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_prov_co_mention "
    "ON provenance (document_id, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_prov_temporal "
    "ON provenance (entity_id, detected_at)",
    "CREATE INDEX IF NOT EXISTS idx_rel_source "
    "ON relationships (source_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_target "
    "ON relationships (target_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_qualifier "
    "ON relationships (qualifier_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_kind "
    "ON relationships (relation_kind_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_type "
    "ON relationships (relation_type)",
    "CREATE INDEX IF NOT EXISTS idx_entity_hist "
    "ON entity_history (entity_id, changed_at)",
    "CREATE INDEX IF NOT EXISTS idx_rel_hist_source "
    "ON relationship_history (source_id, changed_at)",
    "CREATE INDEX IF NOT EXISTS idx_rel_hist_target "
    "ON relationship_history (target_id, changed_at)",
)


_ENTITY_SELECT = (
    "SELECT entity_id, canonical_name, "
    "entity_type, subtype, description, "
    "valid_from, valid_until, status, "
    "merged_into, created_at, updated_at "
    "FROM entities "
)

_ENTITY_SELECT_ALIASED = (
    "SELECT e.entity_id, e.canonical_name, "
    "e.entity_type, e.subtype, e.description, "
    "e.valid_from, e.valid_until, e.status, "
    "e.merged_into, e.created_at, "
    "e.updated_at FROM entities e "
)

_REL_SELECT = (
    "SELECT source_id, target_id, relation_type, "
    "description, qualifier_id, relation_kind_id, "
    "valid_from, valid_until, document_id, "
    "discovered_at FROM relationships "
)


class KnowledgeStore(SQLiteStore):
    """SQLite-backed store for knowledge graph data.

    :param db_path: Path to the SQLite database file.
        Parent directories are created automatically.
    """

    _ddl_statements = (
        _CREATE_ENTITIES,
        _CREATE_ALIASES,
        _CREATE_PROVENANCE,
        _CREATE_RELATIONSHIPS,
        _CREATE_ENTITY_HISTORY,
        _CREATE_RELATIONSHIP_HISTORY,
    )
    _index_statements = _CREATE_INDEXES

    def __init__(
        self, db_path: Path = _DEFAULT_DB_PATH
    ) -> None:
        super().__init__(
            db_path,
            pragmas=("foreign_keys = ON",),
        )

    # -- Entity operations --

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
                _dt_to_iso(entity.valid_from),
                _dt_to_iso(entity.valid_until),
                entity.status.value,
                entity.merged_into,
                _dt_to_iso(entity.created_at),
                _dt_to_iso(entity.updated_at),
            ),
        )
        self._sync_aliases(
            entity.entity_id, entity.aliases
        )
        self._log_entity(entity, operation, reason)
        self._conn.commit()

    def get_entity(self, entity_id: str) -> Entity | None:
        """Fetch an entity by its ID.

        :param entity_id: The entity's unique identifier.
        :return: The entity, or ``None`` if not found.
        """
        row = self._conn.execute(
            _ENTITY_SELECT + "WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        aliases = self._load_aliases(entity_id)
        return _row_to_entity(row, aliases)

    def find_by_name(
        self, name: str
    ) -> list[Entity]:
        """Find entities whose canonical name matches.

        Case-insensitive search.

        :param name: Name to search for.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            _ENTITY_SELECT
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
            _ENTITY_SELECT_ALIASED
            + "JOIN entity_aliases a "
            "ON e.entity_id = a.entity_id "
            "WHERE a.alias COLLATE NOCASE = ?",
            (alias,),
        ).fetchall()
        return self._rows_to_entities(rows)

    # -- Provenance operations --

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
            "detected_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                provenance.entity_id,
                provenance.document_id,
                provenance.source,
                provenance.mention_text,
                provenance.context_snippet,
                _dt_to_iso(provenance.detected_at),
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
            "detected_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    p.entity_id,
                    p.document_id,
                    p.source,
                    p.mention_text,
                    p.context_snippet,
                    _dt_to_iso(p.detected_at),
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
            "mention_text, context_snippet, detected_at "
            "FROM provenance WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()
        return [_row_to_provenance(r) for r in rows]

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
            "detected_at FROM provenance "
            "WHERE entity_id = ? "
            "AND detected_at >= ? "
            "ORDER BY detected_at DESC",
            (entity_id, _dt_to_iso(since)),
        ).fetchall()
        return [_row_to_provenance(r) for r in rows]

    # -- Relationship operations --

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
            "valid_until, document_id, discovered_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                relationship.source_id,
                relationship.target_id,
                relationship.relation_type,
                relationship.description,
                relationship.qualifier_id,
                relationship.relation_kind_id,
                _dt_to_iso(relationship.valid_from)
                or "",
                _dt_to_iso(relationship.valid_until),
                relationship.document_id,
                _dt_to_iso(relationship.discovered_at),
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
                _REL_SELECT + "WHERE source_id = ?",
                (entity_id,),
            ).fetchall()
            results.extend(
                _row_to_relationship(r) for r in rows
            )
        if as_target:
            rows = self._conn.execute(
                _REL_SELECT + "WHERE target_id = ?",
                (entity_id,),
            ).fetchall()
            results.extend(
                _row_to_relationship(r) for r in rows
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
        return the reverse direction — call again with
        swapped arguments if needed.

        :param source_id: The source entity's ID.
        :param target_id: The target entity's ID.
        :return: Matching relationships.
        """
        rows = self._conn.execute(
            _REL_SELECT
            + "WHERE source_id = ? "
            "AND target_id = ?",
            (source_id, target_id),
        ).fetchall()
        return [_row_to_relationship(r) for r in rows]

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
            _REL_SELECT + "WHERE qualifier_id = ?",
            (qualifier_id,),
        ).fetchall()
        return [_row_to_relationship(r) for r in rows]

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
            _REL_SELECT
            + "WHERE relation_kind_id = ?",
            (relation_kind_id,),
        ).fetchall()
        return [_row_to_relationship(r) for r in rows]

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
            _REL_SELECT
            + "WHERE relation_type = ?",
            (relation_type,),
        ).fetchall()
        return [_row_to_relationship(r) for r in rows]

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
        now = _now_iso()
        results: list[Relationship] = []
        for col, include in (
            ("source_id", as_source),
            ("target_id", as_target),
        ):
            if not include:
                continue
            rows = self._conn.execute(
                _REL_SELECT
                + f"WHERE {col} = ? "
                "AND (valid_until IS NULL "
                "OR valid_until = '' "
                "OR valid_until > ?)",
                (entity_id, now),
            ).fetchall()
            results.extend(
                _row_to_relationship(r) for r in rows
            )
        return results

    def find_entities_by_type(
        self, entity_type: EntityType
    ) -> list[Entity]:
        """Find all entities of a given type.

        :param entity_type: The type to filter by.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            _ENTITY_SELECT + "WHERE entity_type = ?",
            (entity_type.value,),
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_entities_by_subtype(
        self,
        entity_type: EntityType,
        subtype: str,
    ) -> list[Entity]:
        """Find entities by type and subtype.

        :param entity_type: The type to filter by.
        :param subtype: The subtype to filter by.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            _ENTITY_SELECT
            + "WHERE entity_type = ? AND subtype = ?",
            (entity_type.value, subtype),
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_entities_by_status(
        self, status: EntityStatus
    ) -> list[Entity]:
        """Find all entities with a given status.

        Useful for listing only ACTIVE entities or finding
        all MERGED/DEPRECATED ones.

        :param status: The status to filter by.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            _ENTITY_SELECT + "WHERE status = ?",
            (status.value,),
        ).fetchall()
        return self._rows_to_entities(rows)

    def find_by_name_prefix(
        self, prefix: str
    ) -> list[Entity]:
        """Find entities whose name starts with a prefix.

        Case-insensitive prefix search for
        autocomplete/typeahead lookups.

        :param prefix: The prefix to match against
            ``canonical_name``.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            _ENTITY_SELECT
            + "WHERE canonical_name "
            "COLLATE NOCASE LIKE ? || '%'",
            (prefix,),
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
        self, since: datetime
    ) -> list[Entity]:
        """Find entities created after a given time.

        Returns entities with ``created_at >= since``,
        ordered most recent first. Useful for new-entity
        monitoring ("what was added to the KG today?").

        :param since: Only return entities created at or
            after this datetime.
        :return: Matching entities, newest first.
        """
        rows = self._conn.execute(
            _ENTITY_SELECT
            + "WHERE created_at >= ? "
            "ORDER BY created_at DESC",
            (_dt_to_iso(since),),
        ).fetchall()
        return self._rows_to_entities(rows)

    # -- Co-mention query --

    def find_co_mentioned(
        self,
        entity_id: str,
        since: datetime | None = None,
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
        params: list[str | None] = [
            entity_id, entity_id,
        ]
        if since is not None:
            query += "AND p1.detected_at >= ? "
            params.append(_dt_to_iso(since))
        query += (
            "GROUP BY p2.entity_id "
            "ORDER BY cnt DESC"
        )
        rows = self._conn.execute(
            query, params
        ).fetchall()
        if not rows:
            return []
        eids = [r[0] for r in rows]
        alias_map = self._load_aliases_batch(eids)
        results: list[tuple[Entity, int]] = []
        for row in rows:
            eid, cnt = row[0], row[1]
            entity = _row_to_entity(
                (eid, *row[2:]),
                alias_map.get(eid, ()),
            )
            results.append((entity, cnt))
        return results

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
        return [_row_to_entity_rev(r) for r in rows]

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
            (entity_id, _dt_to_iso(at)),
        ).fetchone()
        if row is None:
            return None
        return _row_to_entity_rev(row)

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
        rev = _row_to_entity_rev(row)
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
        return [_row_to_relationship_rev(r) for r in rows]

    # -- Internal helpers --

    def _migrate(self) -> None:
        """Run knowledge graph schema migrations."""
        self._migrate_relationships()
        self._migrate_entities()

    def _migrate_relationships(self) -> None:
        """Add columns and fix NULLs from prior versions."""
        cursor = self._conn.execute(
            "PRAGMA table_info(relationships)"
        )
        cols = {row[1] for row in cursor.fetchall()}
        for col in ("qualifier_id", "relation_kind_id"):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE relationships "
                    f"ADD COLUMN {col} TEXT "
                    f"REFERENCES entities(entity_id)"
                )
        # v0.11.29: coalesce NULL valid_from to "" so
        # the PK dedup works (NULL != NULL in SQLite).
        self._conn.execute(
            "UPDATE relationships SET valid_from = '' "
            "WHERE valid_from IS NULL"
        )

    def _migrate_entities(self) -> None:
        """Add columns introduced in v0.10.0."""
        cursor = self._conn.execute(
            "PRAGMA table_info(entities)"
        )
        cols = {row[1] for row in cursor.fetchall()}
        if "subtype" not in cols:
            self._conn.execute(
                "ALTER TABLE entities "
                "ADD COLUMN subtype TEXT"
            )
        if "updated_at" not in cols:
            self._conn.execute(
                "ALTER TABLE entities "
                "ADD COLUMN updated_at TEXT"
            )

    def _rows_to_entities(
        self,
        rows: list[tuple[str, ...]],
    ) -> list[Entity]:
        """Convert entity rows with batch alias loading."""
        if not rows:
            return []
        eids = [r[0] for r in rows]
        alias_map = self._load_aliases_batch(eids)
        return [
            _row_to_entity(
                r, alias_map.get(r[0], ())
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
                _now_iso(),
                entity.canonical_name,
                entity.entity_type.value,
                entity.subtype,
                entity.description,
                aliases_json,
                _dt_to_iso(entity.valid_from),
                _dt_to_iso(entity.valid_until),
                entity.status.value,
                entity.merged_into,
                reason,
            ),
        )

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
                _now_iso(),
                rel.source_id,
                rel.target_id,
                rel.relation_type,
                rel.description,
                rel.qualifier_id,
                rel.relation_kind_id,
                _dt_to_iso(rel.valid_from) or "",
                _dt_to_iso(rel.valid_until),
                rel.document_id,
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
        return tuple(r[0] for r in rows)

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


# -- Module-level helpers --


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _iso_to_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _row_to_entity(
    row: tuple[
        str, str, str, str | None, str,
        str | None, str | None,
        str, str | None, str | None,
        str | None,
    ],
    aliases: tuple[str, ...],
) -> Entity:
    return Entity(
        entity_id=row[0],
        canonical_name=row[1],
        entity_type=EntityType(row[2]),
        subtype=row[3],
        description=row[4],
        aliases=aliases,
        valid_from=_iso_to_dt(row[5]),
        valid_until=_iso_to_dt(row[6]),
        status=EntityStatus(row[7]),
        merged_into=row[8],
        created_at=_iso_to_dt(row[9]),
        updated_at=_iso_to_dt(row[10]),
    )


def _row_to_provenance(
    row: tuple[
        str, str, str, str, str, str | None
    ],
) -> Provenance:
    return Provenance(
        entity_id=row[0],
        document_id=row[1],
        source=row[2],
        mention_text=row[3],
        context_snippet=row[4],
        detected_at=_iso_to_dt(row[5]),
    )


def _row_to_relationship(
    row: tuple[
        str, str, str, str,
        str | None, str | None,
        str | None, str | None,
        str | None, str | None,
    ],
) -> Relationship:
    return Relationship(
        source_id=row[0],
        target_id=row[1],
        relation_type=row[2],
        description=row[3],
        qualifier_id=row[4],
        relation_kind_id=row[5],
        valid_from=_iso_to_dt(row[6]),
        valid_until=_iso_to_dt(row[7]),
        document_id=row[8],
        discovered_at=_iso_to_dt(row[9]),
    )


def _row_to_entity_rev(
    row: tuple[
        int, str, str, str, str, str,
        str | None, str, str | None,
        str | None, str | None,
        str, str | None, str | None,
    ],
) -> EntityRevision:
    aliases_raw = row[8]
    aliases = tuple(json.loads(aliases_raw)) if aliases_raw else ()
    return EntityRevision(
        revision_id=row[0],
        entity_id=row[1],
        operation=row[2],
        changed_at=datetime.fromisoformat(row[3]),
        canonical_name=row[4],
        entity_type=EntityType(row[5]),
        subtype=row[6],
        description=row[7],
        aliases=aliases,
        valid_from=_iso_to_dt(row[9]),
        valid_until=_iso_to_dt(row[10]),
        status=EntityStatus(row[11]),
        merged_into=row[12],
        reason=row[13],
    )


def _row_to_relationship_rev(
    row: tuple[
        int, str, str, str, str,
        str, str, str | None,
        str | None, str | None,
        str | None, str | None,
        str | None,
    ],
) -> RelationshipRevision:
    return RelationshipRevision(
        revision_id=row[0],
        operation=row[1],
        changed_at=datetime.fromisoformat(row[2]),
        source_id=row[3],
        target_id=row[4],
        relation_type=row[5],
        description=row[6],
        qualifier_id=row[7],
        relation_kind_id=row[8],
        valid_from=_iso_to_dt(row[9]),
        valid_until=_iso_to_dt(row[10]),
        document_id=row[11],
        reason=row[12],
    )
