# Knowledge Graph — Design Decisions

## Approach: LLM-first

The knowledge graph is an **index into the news** — it stores
just enough metadata (names, aliases, descriptions, relationship
types) for the LLM to recognize and track entity mentions across
unstructured text. The actual knowledge lives in the articles;
the KG exists to identify entities and link them, not to
replicate structured facts (amounts, deal values, positions)
that already exist in the source text.

It is also a **runtime knowledge supplement**: an LLM's training
data has a cutoff, and entities that appear after that date (new
companies, people, events) are unknown to the model. The KG
stores enough natural-language context that the LLM can resolve
and reason about these entities without prior knowledge.

Entities are resolved by reading descriptions, aliases, and
provenance context — not by algorithmic vector matching. This
means:

- No embeddings stored on entities (defer to a companion vector
  store if bulk/cost-sensitive processing needs it later).
- No confidence scores on matches (the LLM reasons directly).
- No structured attributes on relationships (no amounts, deal
  values, etc.) — the KG is shallow but wide.
- Rich natural-language `description` fields are first-class —
  they are **instructions for the LLM**, not labels for humans.
  The richer and more distinguishing they are, the better
  resolution works.


## EntityType — eight values

| Type           | Covers                                              |
|----------------|-----------------------------------------------------|
| PERSON         | Individuals: politicians, executives, athletes, etc |
| ORGANIZATION   | Companies, governments, NGOs, parties, universities |
| PLACE          | Countries, cities, regions, landmarks, bodies of    |
|                | water                                               |
| TOPIC          | Recurring subjects: "inflation", "AI regulation",   |
|                | "NATO expansion"                                    |
| PRODUCT        | Named products, services, platforms: "iPhone",       |
|                | "ChatGPT", "Boeing 737 MAX", "Ozempic". Distinct    |
|                | from the ORGANIZATION that manufactures them        |
| LEGISLATION    | Laws, regulations, treaties, legal instruments:      |
|                | "GDPR", "Paris Agreement", "Dodd-Frank Act".        |
|                | Have temporal bounds (enacted/repealed) and          |
|                | relationships to sponsors, jurisdictions, and        |
|                | affected entities                                   |
| ROLE           | Positions and titles: "CTO", "President", "Board    |
|                | Member". Uses the alias system for synonym           |
|                | resolution ("CTO" = "Chief Technology Officer")     |
| RELATION_KIND  | Canonical relationship types: "employment",          |
|                | "acquisition". Uses aliases so "works_at",           |
|                | "employed_by", "serves_as" resolve to the same kind |

### Why ROLE and RELATION_KIND as entity types?

Both are **meta-types** that reuse the entity/alias system
for structured querying and synonym resolution:

- **ROLE** entities solve n-ary relationships. "Person X is
  CTO at Company Y" is modeled as a relationship with
  `qualifier_id` pointing to the CTO role entity. Querying
  "all CTOs" becomes an indexed lookup, not a free-text
  scan. Roles get aliases for free — "CTO", "Chief
  Technology Officer", "head of technology" all resolve
  to the same entity.

- **RELATION_KIND** entities normalize relationship types.
  The raw `relation_type` string is LLM-generated and
  free-form. The `relation_kind_id` FK links to a canonical
  kind entity with aliases, so "works_at", "employed_by",
  and "serves_as" all resolve to the same "employment"
  kind. This enables querying all relationships of a kind
  regardless of surface form.

Neither meta-type has a blurry boundary with the other six.
A role is never confused with a person, organization, place,
or topic. They were added in v0.8.0.

### Why PRODUCT and LEGISLATION?

- **PRODUCT** is distinct from ORGANIZATION. News frequently
  references products as standalone entities ("iPhone sales
  dropped", "Boeing 737 MAX grounded"). Shoehorning them
  into TOPIC loses the ability to query "all products" and
  model manufacturer relationships.

- **LEGISLATION** is distinct from TOPIC. A topic is a
  recurring subject ("data privacy regulation"); a
  legislation entity is a specific named instrument
  ("GDPR") with sponsors, jurisdictions, enactment dates,
  and affected entities. These drive substantial news
  coverage and have rich relationship structures.

### Why not more types?

- **No EVENT type.** Events are better modeled as
  *relationships with temporal bounds* between entities.
  "Russia invaded Ukraine" becomes
  Relationship(source=Russia, target=Ukraine,
  relation_type="invaded", valid_from=2022-02-24). A
  separate entity type would duplicate what relationships
  already express.

- **TOPIC instead of a broader CONCEPT.** "Concept" is too
  vague — anything qualifies. "Topic" is concrete: a
  recurring subject the news covers, useful for clustering
  and linking articles.

- **ORGANIZATION is not split into COMPANY, GOVERNMENT, etc.**
  The boundary is blurry (is the BBC a company or a public
  institution? Is SpaceX a company or a government
  contractor?). The LLM resolves this nuance via
  `Entity.description`. If subtypes are needed later, add an
  optional `subtype` field rather than multiplying enum values.

- **PLACE rather than LOCATION.** "Place" reads more naturally
  in news context and avoids implying coordinates or
  geospatial precision.

### Adding new types

New values can be added to `EntityType` without migration — the
database stores them as text. However, think twice: every new
type makes LLM classification harder. Prefer using `description`
for finer distinctions within a type.


## EntityStatus — lifecycle states

| Status     | Meaning                                           |
|------------|---------------------------------------------------|
| ACTIVE     | Current and valid                                 |
| MERGED     | Merged into another entity; `merged_into` field   |
|            | points to the surviving entity's ID               |
| DEPRECATED | No longer relevant but kept for provenance history|

Merge is a common operation: two entities that looked distinct
turn out to be the same ("Apple Inc." and "Apple Computer").
The MERGED status preserves provenance links while redirecting
future queries to the surviving entity.


## Entity fields

- **entity_id**: UUID hex (32 chars), auto-generated. Matches
  the `document_id` pattern in `Article` — offline-generatable,
  no DB round-trip needed.

- **canonical_name**: The authoritative name. Not a display
  name — display formatting is a presentation concern.

- **aliases**: Tuple of surface forms for detection. Stored
  separately in the DB as a normalized table for indexed
  case-insensitive lookups.

- **description**: Critical for LLM resolution. Should include
  distinguishing details: role, country, founding year, etc.
  This is what makes the LLM-first approach work.

- **valid_from / valid_until**: Temporal bounds. Many entities
  are time-bounded (political offices, corporate existence).
  `None` means unbounded on that side.

### Deferred fields

- **Embeddings**: Not on the entity. If needed, store in a
  companion vector DB keyed by `entity_id`.
- **Confidence scores**: LLM reasons directly; no numeric score.
- **Display name**: `canonical_name` suffices.
- **external_ids** (Wikidata QID, etc.): Separate mapping table
  later. Keeps the core model minimal.
- **Metadata dict**: Wait for a concrete need.


## Provenance — linking entities to documents

- **document_id** (not URL): References `Article.document_id`,
  a stable UUID. URLs can change or be non-unique across
  sources. The document_id is source-agnostic, so the KG can
  be populated from non-scraper sources without coupling.

- **context_snippet**: Not just the mention — the surrounding
  text. Critical for the LLM to disambiguate (e.g. "Apple"
  the company vs "apple" the fruit depends on context).

- **No object references**: Provenance links by `document_id`
  string, not by `Article` object. This avoids cross-module
  coupling and keeps the KG independently testable.


## Relationship — open-ended and temporal

- **relation_type is a string, not an enum**: The space of
  relationships in news is unbounded ("acquired", "invaded",
  "appointed", "sanctioned", "married", "funded", etc.).
  An enum would constantly need extending.

- **qualifier_id**: Optional FK to an entity (typically ROLE)
  that qualifies the relationship. Solves n-ary
  relationships: Person→Company qualified by CTO role means
  "Person is CTO at Company". Without this, you can't
  distinguish which role is at which company when a person
  holds multiple positions.

- **relation_kind_id**: Optional FK to a RELATION_KIND entity
  for normalized lookup. The raw `relation_type` string is
  kept as-is (LLM output); this provides canonical grouping
  so synonyms resolve to the same kind. Populated during
  ingestion post-processing.

- **Events are relationships**: "2024 US Election" is modeled
  as relationships between candidates and a PLACE entity with
  temporal bounds — not as a standalone entity.

- **document_id on Relationship**: Where the relationship was
  discovered. `None` for manually curated relationships.

### Deferred fields

- **Weight / importance**: Not needed for LLM-first. The LLM
  judges importance from context.
- **Relationship ID**: Not needed yet — the composite key
  (source_id, target_id, relation_type, valid_from) is unique.
- **Multi-qualifier**: Only one qualifier per relationship.
  Sufficient for the news domain (person+role+company). If
  needed, add a join table later.


## Storage: SQLite

Follows the `ArticleStore` pattern established in `web_scraping`:

- Constructor takes `Path`, creates tables/indexes.
- Context manager for connection lifecycle.
- Bulk insert with deduplication.

### `entities`

Core entity records. Dates stored as ISO 8601 text.

| Column         | Type     | Constraint       | Purpose                                    |
|----------------|----------|------------------|--------------------------------------------|
| entity_id      | TEXT     | PRIMARY KEY      | UUID hex (32 chars), auto-generated        |
| canonical_name | TEXT     | NOT NULL         | Authoritative display name                 |
| entity_type    | TEXT     | NOT NULL         | person, organization, place, topic, product, legislation, role, relation_kind |
| description    | TEXT     | NOT NULL         | Natural-language context for LLM resolution|
| valid_from     | TEXT     |                  | When this entity became relevant           |
| valid_until    | TEXT     |                  | When this entity ceased to be relevant     |
| status         | TEXT     | NOT NULL, DEFAULT 'active' | Lifecycle: active, merged, deprecated |
| merged_into    | TEXT     |                  | If merged, the surviving entity's ID       |
| created_at     | TEXT     |                  | When this record was created               |

Indexes: `entity_type`, `status`.

### `entity_aliases`

Surface forms for entity detection. Stored separately from
`entities` for indexed case-insensitive lookups.

| Column    | Type | Constraint                    | Purpose                          |
|-----------|------|-------------------------------|----------------------------------|
| entity_id | TEXT | FK → entities, part of PK    | Which entity this alias belongs to|
| alias     | TEXT | Part of PK                   | Alternative name (e.g. "MBS")    |

Primary key: `(entity_id, alias)`.
Index: `alias COLLATE NOCASE` for case-insensitive search.

### `provenance`

Evidence that an entity was mentioned in a specific document.
Links the knowledge graph to the articles database via
`document_id` (not URL) to avoid cross-module coupling.

| Column          | Type | Constraint                 | Purpose                              |
|-----------------|------|----------------------------|--------------------------------------|
| entity_id       | TEXT | FK → entities, part of PK | Which entity was mentioned           |
| document_id     | TEXT | Part of PK                | References `articles.document_id`    |
| source          | TEXT | NOT NULL                  | News source name (e.g. "bbc")        |
| mention_text    | TEXT | Part of PK                | Exact surface form found in text     |
| context_snippet | TEXT | NOT NULL                  | Surrounding text for LLM disambiguation|
| detected_at     | TEXT |                           | When the detection occurred           |

Primary key: `(entity_id, document_id, mention_text)`.
Index: `document_id` for lookups by article.

### `relationships`

Directed relationships between entities. `relation_type` is a
free-form string because the space of possible relationships
in news is unbounded. Events are modeled as relationships with
temporal bounds rather than as a separate entity type.

| Column           | Type | Constraint                 | Purpose                              |
|------------------|------|----------------------------|--------------------------------------|
| source_id        | TEXT | FK → entities, part of PK | Subject entity                       |
| target_id        | TEXT | FK → entities, part of PK | Object entity                        |
| relation_type    | TEXT | Part of PK                | Free-form label (LLM-generated)      |
| description      | TEXT | NOT NULL                  | Natural-language context              |
| qualifier_id     | TEXT | FK → entities             | Qualifies the relationship (e.g. ROLE)|
| relation_kind_id | TEXT | FK → entities             | Canonical kind (e.g. "employment")   |
| valid_from       | TEXT | Part of PK                | When the relationship started         |
| valid_until      | TEXT |                           | When the relationship ended           |
| document_id      | TEXT |                           | Where this relationship was discovered|
| discovered_at    | TEXT |                           | When this relationship was detected   |

Primary key: `(source_id, target_id, relation_type, valid_from)`.
Indexes: `source_id`, `target_id`, `qualifier_id`,
`relation_kind_id`.
