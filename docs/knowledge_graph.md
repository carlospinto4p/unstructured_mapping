# Knowledge Graph — Design Decisions

## Approach: LLM-first

The knowledge graph is a **reference catalog** that an LLM reads
and reasons over. Entities are resolved by reading descriptions,
aliases, and provenance context — not by algorithmic vector
matching. This means:

- No embeddings stored on entities (defer to a companion vector
  store if bulk/cost-sensitive processing needs it later).
- No confidence scores on matches (the LLM reasons directly).
- Rich natural-language `description` fields are first-class.


## EntityType — why four values

| Type           | Covers                                              |
|----------------|-----------------------------------------------------|
| PERSON         | Individuals: politicians, executives, athletes, etc |
| ORGANIZATION   | Companies, governments, NGOs, parties, universities |
| PLACE          | Countries, cities, regions, landmarks, bodies of    |
|                | water                                               |
| TOPIC          | Recurring subjects: "inflation", "AI regulation",   |
|                | "NATO expansion"                                    |

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


## Storage: SQLite

Follows the `ArticleStore` pattern established in `web_scraping`:

- Constructor takes `Path`, creates tables/indexes.
- Context manager for connection lifecycle.
- Bulk insert with deduplication.

### Tables

- `entities` — core fields, dates as ISO text.
- `entity_aliases` — (entity_id, alias) PK, normalized
  lowercase for case-insensitive lookups.
- `provenance` — (entity_id, document_id, mention_text) PK.
- `relationships` — (source_id, target_id, relation_type,
  valid_from) PK.
