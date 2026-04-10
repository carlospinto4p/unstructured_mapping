# Knowledge Graph — SQLite Schema

Extends :class:`SQLiteStore` from ``storage_base.py``, which
handles directory creation, connection lifecycle, DDL execution,
migration, and index creation. ``KnowledgeStore`` declares its
tables and indexes as class attributes and overrides ``_migrate``
for schema evolution.


## `entities`

Core entity records. Dates stored as ISO 8601 text.

| Column         | Type     | Constraint       | Purpose                                    |
|----------------|----------|------------------|--------------------------------------------|
| entity_id      | TEXT     | PRIMARY KEY      | UUID hex (32 chars), auto-generated        |
| canonical_name | TEXT     | NOT NULL         | Authoritative display name                 |
| entity_type    | TEXT     | NOT NULL         | person, organization, place, topic, product, legislation, asset, metric, role, relation_kind |
| subtype        | TEXT     |                  | Optional finer classification (e.g. "company", "equity"). See [subtypes.md](subtypes.md) |
| description    | TEXT     | NOT NULL         | Natural-language context for LLM resolution|
| valid_from     | TEXT     |                  | When this entity became relevant           |
| valid_until    | TEXT     |                  | When this entity ceased to be relevant     |
| status         | TEXT     | NOT NULL, DEFAULT 'active' | Lifecycle: active, merged, deprecated |
| merged_into    | TEXT     |                  | If merged, the surviving entity's ID       |
| created_at     | TEXT     |                  | When this record was created               |
| updated_at     | TEXT     |                  | When this record was last modified          |

Indexes: `entity_type`, `(entity_type, subtype)`, `status`,
`canonical_name COLLATE NOCASE`, `created_at`.


## `entity_aliases`

Surface forms for entity detection. Stored separately from
`entities` for indexed case-insensitive lookups.

| Column    | Type | Constraint                    | Purpose                          |
|-----------|------|-------------------------------|----------------------------------|
| entity_id | TEXT | FK -> entities, part of PK    | Which entity this alias belongs to|
| alias     | TEXT | Part of PK                   | Alternative name (e.g. "MBS")    |

Primary key: `(entity_id, alias)`.
Index: `alias COLLATE NOCASE` for case-insensitive search.


## `provenance`

Evidence that an entity was mentioned in a specific document.
Links the knowledge graph to the articles database via
`document_id` (not URL) to avoid cross-module coupling.

| Column          | Type | Constraint                 | Purpose                              |
|-----------------|------|----------------------------|--------------------------------------|
| entity_id       | TEXT | FK -> entities, part of PK | Which entity was mentioned           |
| document_id     | TEXT | Part of PK                | References `articles.document_id`    |
| source          | TEXT | NOT NULL                  | News source name (e.g. "bbc")        |
| mention_text    | TEXT | Part of PK                | Exact surface form found in text     |
| context_snippet | TEXT | NOT NULL                  | Surrounding text for LLM disambiguation|
| detected_at     | TEXT |                           | When the detection occurred           |
| run_id          | TEXT |                           | FK -> ingestion_runs. Pipeline run that created this record |
| section_name    | TEXT |                           | Document section (e.g. "Risk Factors")|

Primary key: `(entity_id, document_id, mention_text)`.
Indexes: `document_id`, `(document_id, entity_id)` for
co-mention joins, `(entity_id, detected_at)` for temporal
queries.

### `section_name` column

Added to support long-form document processing (research
reports, earnings transcripts, regulatory filings). Where
in a document an entity is mentioned carries analytical
signal — an entity in "Risk Factors" means something
different from one in "Executive Summary."

Nullable — news articles and other unsegmented documents
leave this as NULL. Only populated when the pipeline
processes a chunked document with section-aware
segmentation. See
[pipeline/09_chunking.md](../pipeline/09_chunking.md) for the
segmentation design.

Enables section-level queries:
- "Which entities appear in Risk Factors across filings?"
- "Compare entity mentions in prepared remarks vs Q&A."


## `relationships`

Directed relationships between entities. `relation_type` is a
free-form string because the space of possible relationships
in news is unbounded. Events are modeled as relationships with
temporal bounds rather than as a separate entity type.

| Column           | Type | Constraint                 | Purpose                              |
|------------------|------|----------------------------|--------------------------------------|
| source_id        | TEXT | FK -> entities, part of PK | Subject entity                       |
| target_id        | TEXT | FK -> entities, part of PK | Object entity                        |
| relation_type    | TEXT | Part of PK                | Free-form label (LLM-generated)      |
| description      | TEXT | NOT NULL                  | Natural-language context              |
| qualifier_id     | TEXT | FK -> entities             | Qualifies the relationship (e.g. ROLE)|
| relation_kind_id | TEXT | FK -> entities             | Canonical kind (e.g. "employment")   |
| valid_from       | TEXT | Part of PK, `""` if unset | When the relationship started         |
| valid_until      | TEXT |                           | When the relationship ended           |
| document_id      | TEXT |                           | Where this relationship was discovered|
| discovered_at    | TEXT |                           | When this relationship was detected   |
| run_id           | TEXT |                           | FK -> ingestion_runs. Pipeline run that created this record |
| section_name     | TEXT |                           | Document section (e.g. "Q&A")        |

Primary key: `(source_id, target_id, relation_type, valid_from)`.

### `section_name` column

Same rationale as on `provenance` — a relationship
discovered in the Q&A section of an earnings call carries
different context than one in prepared remarks. Nullable
for the same reasons. See
[pipeline/09_chunking.md](../pipeline/09_chunking.md).
Note: `valid_from` stores `""` (empty string) instead of NULL
when no temporal bound is set — SQLite treats `NULL != NULL`,
which would allow silent duplicate rows with the same
composite key. The storage layer converts `""` back to `None`
on read.

Indexes: `source_id`, `target_id`, `qualifier_id`,
`relation_kind_id`, `relation_type`.


## `entity_history`

Append-only audit log for entity mutations. Each row is a
full snapshot of the entity after the operation.

| Column         | Type    | Constraint            | Purpose                               |
|----------------|---------|-----------------------|---------------------------------------|
| revision_id    | INTEGER | PRIMARY KEY AUTOINCR  | Monotonically increasing revision     |
| entity_id      | TEXT    | NOT NULL              | Which entity this revision belongs to |
| operation      | TEXT    | NOT NULL              | create, update, merge, revert         |
| changed_at     | TEXT    | NOT NULL              | When the operation occurred (UTC ISO)  |
| canonical_name | TEXT    | NOT NULL              | Name at this revision                 |
| entity_type    | TEXT    | NOT NULL              | Type at this revision                 |
| subtype        | TEXT    |                       | Subtype at this revision              |
| description    | TEXT    | NOT NULL              | Description at this revision          |
| aliases        | TEXT    |                       | JSON array of aliases at this revision|
| valid_from     | TEXT    |                       | Temporal lower bound                  |
| valid_until    | TEXT    |                       | Temporal upper bound                  |
| status         | TEXT    | NOT NULL              | Lifecycle status at this revision     |
| merged_into    | TEXT    |                       | Merge target, if applicable           |
| reason         | TEXT    |                       | Free-text explanation                 |

Index: `(entity_id, changed_at)`.


## `relationship_history`

Append-only audit log for relationship mutations.

| Column           | Type    | Constraint            | Purpose                               |
|------------------|---------|-----------------------|---------------------------------------|
| revision_id      | INTEGER | PRIMARY KEY AUTOINCR  | Monotonically increasing revision     |
| operation        | TEXT    | NOT NULL              | create, merge                         |
| changed_at       | TEXT    | NOT NULL              | When the operation occurred (UTC ISO)  |
| source_id        | TEXT    | NOT NULL              | Subject entity at this revision       |
| target_id        | TEXT    | NOT NULL              | Object entity at this revision        |
| relation_type    | TEXT    | NOT NULL              | Relationship label                    |
| description      | TEXT    | NOT NULL              | Context at this revision              |
| qualifier_id     | TEXT    |                       | Qualifier FK at this revision         |
| relation_kind_id | TEXT    |                       | Kind FK at this revision              |
| valid_from       | TEXT    |                       | Temporal lower bound                  |
| valid_until      | TEXT    |                       | Temporal upper bound                  |
| document_id      | TEXT    |                       | Originating document                  |
| reason           | TEXT    |                       | Free-text explanation                 |

Indexes: `(source_id, changed_at)`, `(target_id, changed_at)`.


## `ingestion_runs`

Metadata for pipeline executions. Each row represents one
invocation of the ingestion pipeline, grouping the provenance
and relationship records it created via `run_id` foreign keys.

Replaces timestamp-based correlation with an explicit link:
instead of inferring "which records came from the same run"
by matching `detected_at`/`discovered_at` windows, consumers
can filter directly on `run_id`.

| Column             | Type    | Constraint  | Purpose                                    |
|--------------------|---------|-------------|--------------------------------------------|
| run_id             | TEXT    | PRIMARY KEY | UUID hex (32 chars), auto-generated        |
| started_at         | TEXT    | NOT NULL    | When the run began (UTC ISO 8601)          |
| finished_at        | TEXT    |             | When the run ended (NULL while running)    |
| status             | TEXT    | NOT NULL, DEFAULT 'running' | running, completed, failed |
| document_count     | INTEGER | NOT NULL, DEFAULT 0 | Documents processed in this run       |
| entity_count       | INTEGER | NOT NULL, DEFAULT 0 | Entity mentions found                 |
| relationship_count | INTEGER | NOT NULL, DEFAULT 0 | Relationships extracted                |
| error_message      | TEXT    |             | Error details if status is 'failed'        |

Index: `status`.
