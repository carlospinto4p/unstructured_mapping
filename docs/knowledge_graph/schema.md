# Knowledge Graph — SQLite Schema

Follows the `ArticleStore` pattern established in `web_scraping`:

- Constructor takes `Path`, creates tables/indexes.
- Context manager for connection lifecycle.
- Bulk insert with deduplication.


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

Indexes: `entity_type`, `(entity_type, subtype)`, `status`.


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

Primary key: `(entity_id, document_id, mention_text)`.
Index: `document_id` for lookups by article.


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
| valid_from       | TEXT | Part of PK                | When the relationship started         |
| valid_until      | TEXT |                           | When the relationship ended           |
| document_id      | TEXT |                           | Where this relationship was discovered|
| discovered_at    | TEXT |                           | When this relationship was detected   |

Primary key: `(source_id, target_id, relation_type, valid_from)`.
Indexes: `source_id`, `target_id`, `qualifier_id`,
`relation_kind_id`.
