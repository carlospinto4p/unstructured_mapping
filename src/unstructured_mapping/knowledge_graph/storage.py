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

from unstructured_mapping.knowledge_graph._audit_mixin import (
    AuditMixin,
)
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
    confidence       REAL,
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

#: Per-run scorecard; one row per run, keyed on the same
#: ``run_id`` as ``ingestion_runs``. Split from the main
#: run table so adding new metrics later does not drag
#: column changes onto every existing run record.
_CREATE_RUN_METRICS = """
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id                  TEXT PRIMARY KEY,
    chunks_processed        INTEGER NOT NULL DEFAULT 0,
    mentions_detected       INTEGER NOT NULL DEFAULT 0,
    mentions_resolved_alias INTEGER NOT NULL DEFAULT 0,
    mentions_resolved_llm   INTEGER NOT NULL DEFAULT 0,
    llm_resolver_calls      INTEGER NOT NULL DEFAULT 0,
    llm_extractor_calls     INTEGER NOT NULL DEFAULT 0,
    proposals_saved         INTEGER NOT NULL DEFAULT 0,
    relationships_saved     INTEGER NOT NULL DEFAULT 0,
    provider_name           TEXT,
    model_name              TEXT,
    wall_clock_seconds      REAL NOT NULL DEFAULT 0.0,
    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id)
        REFERENCES ingestion_runs (run_id)
)
"""

#: Per-article failure ledger. One row per
#: ``(run_id, document_id)`` pair; multiple runs can each
#: record their own failure for the same document. The
#: composite primary key dedupes re-tries within a single
#: run (if a resumed article fails again it overwrites the
#: prior row via :meth:`save_article_failure`'s
#: ``INSERT OR REPLACE``). Populated from the orchestrator's
#: per-article ``except`` block so a crashed batch leaves
#: behind the exact list of documents that need re-queueing.
_CREATE_ARTICLE_FAILURES = """
CREATE TABLE IF NOT EXISTS article_failures (
    run_id        TEXT NOT NULL,
    document_id   TEXT NOT NULL,
    error_message TEXT NOT NULL,
    failed_at     TEXT NOT NULL,
    PRIMARY KEY (run_id, document_id),
    FOREIGN KEY (run_id)
        REFERENCES ingestion_runs (run_id)
)
"""


_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_entity_type ON entities (entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_entity_type_subtype "
    "ON entities (entity_type, subtype)",
    "CREATE INDEX IF NOT EXISTS idx_entity_status ON entities (status)",
    "CREATE INDEX IF NOT EXISTS idx_entity_name "
    "ON entities (canonical_name COLLATE NOCASE)",
    # Seed dedup (see `cli._seed_helpers.exists_by_name_and_type`)
    # hits name+type together on every row. A composite
    # index lets SQLite filter both columns at once
    # instead of returning every row matching the name
    # and filtering the type in Python.
    "CREATE INDEX IF NOT EXISTS idx_entity_name_type "
    "ON entities (canonical_name COLLATE NOCASE, entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_entity_created ON entities (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_alias_lookup "
    "ON entity_aliases (alias COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_prov_document "
    "ON provenance (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_prov_co_mention "
    "ON provenance (document_id, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_prov_temporal "
    "ON provenance (entity_id, detected_at)",
    "CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships (source_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships (target_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_qualifier "
    "ON relationships (qualifier_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_kind "
    "ON relationships (relation_kind_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_type "
    "ON relationships (relation_type)",
    # `find_relationships_by_document` (cli/preview.py) ran a
    # full table scan without this index. Added v0.49.4 after
    # the v0.48.9 optimization review flagged it.
    "CREATE INDEX IF NOT EXISTS idx_rel_document "
    "ON relationships (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_prov_run ON provenance (run_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_run ON relationships (run_id)",
    "CREATE INDEX IF NOT EXISTS idx_run_status ON ingestion_runs (status)",
    "CREATE INDEX IF NOT EXISTS idx_article_failures_run "
    "ON article_failures (run_id)",
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
    AuditMixin,
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
        _CREATE_RUN_METRICS,
        _CREATE_ARTICLE_FAILURES,
    )
    _index_statements = _CREATE_INDEXES

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
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
        self._migrate_run_metrics()

    def _migrate_run_metrics(self) -> None:
        """Add token counters introduced in v0.43.0."""
        cursor = self._conn.execute("PRAGMA table_info(run_metrics)")
        cols = {row[1] for row in cursor.fetchall()}
        if not cols:
            return
        for col in ("input_tokens", "output_tokens"):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE run_metrics "
                    f"ADD COLUMN {col} INTEGER "
                    f"NOT NULL DEFAULT 0"
                )

    def _migrate_provenance(self) -> None:
        """Add ``run_id`` column introduced in v0.15.0."""
        cursor = self._conn.execute("PRAGMA table_info(provenance)")
        cols = {row[1] for row in cursor.fetchall()}
        if "run_id" not in cols:
            self._conn.execute(
                "ALTER TABLE provenance ADD COLUMN run_id TEXT"
            )

    def _migrate_relationships(self) -> None:
        """Add columns and fix NULLs from prior versions."""
        cursor = self._conn.execute("PRAGMA table_info(relationships)")
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
                "ALTER TABLE relationships ADD COLUMN run_id TEXT"
            )
        if "confidence" not in cols:
            # v0.45.0: optional LLM-reported extraction
            # confidence. REAL + nullable keeps prior rows
            # valid — NULL means "not scored".
            self._conn.execute(
                "ALTER TABLE relationships ADD COLUMN confidence REAL"
            )
        # v0.11.29: coalesce NULL valid_from to "" so
        # the PK dedup works (NULL != NULL in SQLite).
        self._conn.execute(
            "UPDATE relationships SET valid_from = '' "
            "WHERE valid_from IS NULL"
        )

    def _migrate_entities(self) -> None:
        """Add columns introduced in v0.10.0."""
        cursor = self._conn.execute("PRAGMA table_info(entities)")
        cols = {row[1] for row in cursor.fetchall()}
        if "subtype" not in cols:
            self._conn.execute("ALTER TABLE entities ADD COLUMN subtype TEXT")
        if "updated_at" not in cols:
            self._conn.execute(
                "ALTER TABLE entities ADD COLUMN updated_at TEXT"
            )
