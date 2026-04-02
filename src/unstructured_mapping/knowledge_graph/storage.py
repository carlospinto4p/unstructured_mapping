"""SQLite storage for the knowledge graph.

Follows the same pattern as
:class:`~unstructured_mapping.web_scraping.storage.ArticleStore`:
constructor takes a :class:`~pathlib.Path`, creates tables and
indexes, and supports context-manager usage.

See ``DESIGN.md`` in this package for table schema rationale.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityStatus,
    EntityType,
    Provenance,
    Relationship,
)

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
    created_at     TEXT
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

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_entity_type "
    "ON entities (entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_entity_type_subtype "
    "ON entities (entity_type, subtype)",
    "CREATE INDEX IF NOT EXISTS idx_entity_status "
    "ON entities (status)",
    "CREATE INDEX IF NOT EXISTS idx_alias_lookup "
    "ON entity_aliases (alias COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_prov_document "
    "ON provenance (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_source "
    "ON relationships (source_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_target "
    "ON relationships (target_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_qualifier "
    "ON relationships (qualifier_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_kind "
    "ON relationships (relation_kind_id)",
]


_REL_SELECT = (
    "SELECT source_id, target_id, relation_type, "
    "description, qualifier_id, relation_kind_id, "
    "valid_from, valid_until, document_id, "
    "discovered_at FROM relationships "
)


class KnowledgeStore:
    """SQLite-backed store for knowledge graph data.

    :param db_path: Path to the SQLite database file.
        Parent directories are created automatically.
    """

    def __init__(
        self, db_path: Path = _DEFAULT_DB_PATH
    ) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        for ddl in (
            _CREATE_ENTITIES,
            _CREATE_ALIASES,
            _CREATE_PROVENANCE,
            _CREATE_RELATIONSHIPS,
        ):
            self._conn.execute(ddl)
        self._migrate_relationships()
        self._migrate_entities()
        for idx in _CREATE_INDEXES:
            self._conn.execute(idx)
        self._conn.commit()

    # -- Entity operations --

    def save_entity(self, entity: Entity) -> None:
        """Insert or update an entity.

        Aliases are synced: old aliases removed, new ones
        added. Uses a transaction for atomicity.

        :param entity: The entity to save.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO entities "
            "(entity_id, canonical_name, entity_type, "
            "subtype, description, valid_from, "
            "valid_until, status, merged_into, "
            "created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ),
        )
        self._conn.execute(
            "DELETE FROM entity_aliases "
            "WHERE entity_id = ?",
            (entity.entity_id,),
        )
        if entity.aliases:
            self._conn.executemany(
                "INSERT INTO entity_aliases "
                "(entity_id, alias) VALUES (?, ?)",
                [
                    (entity.entity_id, a)
                    for a in entity.aliases
                ],
            )
        self._conn.commit()

    def get_entity(self, entity_id: str) -> Entity | None:
        """Fetch an entity by its ID.

        :param entity_id: The entity's unique identifier.
        :return: The entity, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT entity_id, canonical_name, "
            "entity_type, subtype, description, "
            "valid_from, valid_until, status, "
            "merged_into, created_at FROM entities "
            "WHERE entity_id = ?",
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
            "SELECT entity_id, canonical_name, "
            "entity_type, subtype, description, "
            "valid_from, valid_until, status, "
            "merged_into, created_at FROM entities "
            "WHERE canonical_name COLLATE NOCASE = ?",
            (name,),
        ).fetchall()
        return [
            _row_to_entity(r, self._load_aliases(r[0]))
            for r in rows
        ]

    def find_by_alias(
        self, alias: str
    ) -> list[Entity]:
        """Find entities that have a matching alias.

        Case-insensitive search.

        :param alias: Alias to search for.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            "SELECT e.entity_id, e.canonical_name, "
            "e.entity_type, e.subtype, e.description, "
            "e.valid_from, e.valid_until, e.status, "
            "e.merged_into, e.created_at "
            "FROM entities e "
            "JOIN entity_aliases a "
            "ON e.entity_id = a.entity_id "
            "WHERE a.alias COLLATE NOCASE = ?",
            (alias,),
        ).fetchall()
        return [
            _row_to_entity(r, self._load_aliases(r[0]))
            for r in rows
        ]

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

    # -- Relationship operations --

    def save_relationship(
        self, relationship: Relationship
    ) -> None:
        """Insert a relationship, skipping duplicates.

        :param relationship: The relationship to save.
        """
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
                _dt_to_iso(relationship.valid_from),
                _dt_to_iso(relationship.valid_until),
                relationship.document_id,
                _dt_to_iso(relationship.discovered_at),
            ),
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

    def find_entities_by_type(
        self, entity_type: EntityType
    ) -> list[Entity]:
        """Find all entities of a given type.

        :param entity_type: The type to filter by.
        :return: Matching entities.
        """
        rows = self._conn.execute(
            "SELECT entity_id, canonical_name, "
            "entity_type, subtype, description, "
            "valid_from, valid_until, status, "
            "merged_into, created_at FROM entities "
            "WHERE entity_type = ?",
            (entity_type.value,),
        ).fetchall()
        return [
            _row_to_entity(r, self._load_aliases(r[0]))
            for r in rows
        ]

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
            "SELECT entity_id, canonical_name, "
            "entity_type, subtype, description, "
            "valid_from, valid_until, status, "
            "merged_into, created_at FROM entities "
            "WHERE entity_type = ? AND subtype = ?",
            (entity_type.value, subtype),
        ).fetchall()
        return [
            _row_to_entity(
                r, self._load_aliases(r[0])
            )
            for r in rows
        ]

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

        Runs in a single transaction for atomicity.

        :param deprecated_id: Entity to deprecate.
        :param surviving_id: Entity that absorbs the
            deprecated one.
        :raises ValueError: If either entity is not found.
        """
        for eid, label in (
            (deprecated_id, "deprecated_id"),
            (surviving_id, "surviving_id"),
        ):
            if self.get_entity(eid) is None:
                msg = f"{label} '{eid}' not found"
                raise ValueError(msg)

        self._conn.execute(
            "UPDATE provenance SET entity_id = ? "
            "WHERE entity_id = ?",
            (surviving_id, deprecated_id),
        )
        self._conn.execute(
            "UPDATE relationships SET source_id = ? "
            "WHERE source_id = ?",
            (surviving_id, deprecated_id),
        )
        self._conn.execute(
            "UPDATE relationships SET target_id = ? "
            "WHERE target_id = ?",
            (surviving_id, deprecated_id),
        )
        self._conn.execute(
            "UPDATE relationships "
            "SET qualifier_id = ? "
            "WHERE qualifier_id = ?",
            (surviving_id, deprecated_id),
        )
        self._conn.execute(
            "UPDATE relationships "
            "SET relation_kind_id = ? "
            "WHERE relation_kind_id = ?",
            (surviving_id, deprecated_id),
        )
        self._conn.execute(
            "UPDATE entities SET status = ?, "
            "merged_into = ? WHERE entity_id = ?",
            ("merged", surviving_id, deprecated_id),
        )
        self._conn.commit()
        logger.info(
            "Merged entity %s into %s",
            deprecated_id,
            surviving_id,
        )

    # -- Lifecycle --

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "KnowledgeStore":
        return self

    def __exit__(
        self, exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    # -- Internal helpers --

    def _migrate_relationships(self) -> None:
        """Add columns introduced in v0.8.0."""
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

    def _load_aliases(
        self, entity_id: str
    ) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT alias FROM entity_aliases "
            "WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()
        return tuple(r[0] for r in rows)


# -- Module-level helpers --


def _dt_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _iso_to_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _row_to_entity(
    row: tuple[
        str, str, str, str | None, str,
        str | None, str | None,
        str, str | None, str | None,
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
