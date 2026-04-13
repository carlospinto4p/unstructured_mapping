"""SQLite storage for the knowledge graph.

Extends :class:`~unstructured_mapping.storage_base.SQLiteStore`
with knowledge-graph-specific tables, migrations, and queries.

The public interface is :class:`KnowledgeStore`, which composes
domain-focused mixins:

- :class:`~._entity_mixin.EntityMixin` -- entity CRUD, search,
  merge, and audit history (composed from
  ``EntityCRUDMixin``, ``EntitySearchMixin``,
  ``EntityMergeMixin``, ``EntityHistoryMixin``).
- :class:`~._provenance_mixin.ProvenanceMixin` -- provenance
  records and co-mention queries.
- :class:`~._relationship_mixin.RelationshipMixin` --
  relationship CRUD, qualifiers, and history.
- :class:`~._run_mixin.RunMixin` -- ingestion run tracking.

See ``docs/knowledge_graph/`` for table schema rationale.
"""

from pathlib import Path

from unstructured_mapping.knowledge_graph._entity_mixin import (
    EntityMixin,
)
from unstructured_mapping.knowledge_graph._provenance_mixin import (
    ProvenanceMixin,
)
from unstructured_mapping.knowledge_graph._relationship_mixin import (
    RelationshipMixin,
)
from unstructured_mapping.knowledge_graph._run_mixin import (
    RunMixin,
)
from unstructured_mapping.storage_base import SQLiteStore

_DEFAULT_DB_PATH = Path("data/knowledge.db")

# -- DDL ---------------------------------------------------------

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
    history_id    INTEGER PRIMARY KEY AUTOINCREMENT,
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
    history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
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

_CREATE_INGESTION_RUNS = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id             TEXT PRIMARY KEY,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    status             TEXT NOT NULL DEFAULT 'running',
    document_count     INTEGER NOT NULL DEFAULT 0,
    entity_count       INTEGER NOT NULL DEFAULT 0,
    relationship_count INTEGER NOT NULL DEFAULT 0,
    error_message      TEXT
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
    "CREATE INDEX IF NOT EXISTS idx_prov_run "
    "ON provenance (run_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_run "
    "ON relationships (run_id)",
    "CREATE INDEX IF NOT EXISTS idx_run_status "
    "ON ingestion_runs (status)",
    "CREATE INDEX IF NOT EXISTS idx_entity_hist "
    "ON entity_history (entity_id, changed_at)",
    "CREATE INDEX IF NOT EXISTS idx_rel_hist_source "
    "ON relationship_history (source_id, changed_at)",
    "CREATE INDEX IF NOT EXISTS idx_rel_hist_target "
    "ON relationship_history (target_id, changed_at)",
)


# -- KnowledgeStore ----------------------------------------------


class KnowledgeStore(
    EntityMixin,
    ProvenanceMixin,
    RelationshipMixin,
    RunMixin,
    SQLiteStore,
):
    """SQLite-backed store for knowledge graph data.

    Composes domain-focused mixins for entities,
    provenance, relationships, and ingestion runs on
    top of :class:`~unstructured_mapping.storage_base.SQLiteStore`.

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
        _CREATE_INGESTION_RUNS,
    )
    _index_statements = _CREATE_INDEXES

    def __init__(
        self, db_path: Path = _DEFAULT_DB_PATH
    ) -> None:
        super().__init__(
            db_path,
            pragmas=("foreign_keys = ON",),
        )

    # -- Migrations ----------------------------------------------

    def _migrate(self) -> None:
        """Run knowledge graph schema migrations."""
        self._migrate_relationships()
        self._migrate_entities()
        self._migrate_provenance()

    def _migrate_provenance(self) -> None:
        """Add ``run_id`` column introduced in v0.15.0."""
        cursor = self._conn.execute(
            "PRAGMA table_info(provenance)"
        )
        cols = {row[1] for row in cursor.fetchall()}
        if "run_id" not in cols:
            self._conn.execute(
                "ALTER TABLE provenance "
                "ADD COLUMN run_id TEXT"
            )

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
        if "run_id" not in cols:
            self._conn.execute(
                "ALTER TABLE relationships "
                "ADD COLUMN run_id TEXT"
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
