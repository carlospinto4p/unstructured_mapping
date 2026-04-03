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


## EntityType — ten values

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
| ASSET          | Tradeable financial instruments and stores of value: |
|                | "AAPL", "Bitcoin", "Gold", "S&P 500", "US 10-Year   |
|                | Treasury", "EUR/USD". Distinct from PRODUCT (you     |
|                | hold/trade an asset for value; you buy/use a         |
|                | product) and from ORGANIZATION (AAPL the stock vs   |
|                | Apple Inc. the company)                             |
| METRIC         | Quantitative indicators that signal market state:    |
|                | "CPI", "unemployment rate", "PMI", "GDP growth",    |
|                | "federal funds rate", "VIX". Not entities you find   |
|                | in text the usual way — they are measurements with   |
|                | a value and direction — but news constantly          |
|                | references them, and linking articles to the metrics |
|                | they discuss is essential for market impact analysis |
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

Neither meta-type has a blurry boundary with the other eight.
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

### Why ASSET and METRIC?

- **ASSET** is distinct from both PRODUCT and ORGANIZATION.
  An asset is something you hold or trade for value (AAPL
  stock, Bitcoin, gold futures); a product is something you
  buy and use (iPhone, Ozempic). The same real-world company
  may have both an ORGANIZATION entity (Apple Inc.) and an
  ASSET entity (AAPL). Assets have prices, tickers, and
  move markets — products generally don't, unless they
  *become* news that moves the market.

- **METRIC** is distinct from TOPIC. A topic is a recurring
  subject ("inflation"); a metric is a specific named
  indicator ("CPI") that news articles reference. Metrics
  are the primary language of market-moving news — an
  article discussing a CPI release is a metric story, not
  a topic story. Having them as entities lets the KG link
  articles to the specific indicators they discuss. The KG
  stores *that* a metric was mentioned, not the actual
  values — numbers belong in external time-series tables.

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
  contractor?). The optional `subtype` field (added in
  v0.10.0) handles this: set `subtype="company"` or
  `subtype="central_bank"` for structured filtering without
  multiplying enum values. See
  [subtypes.md](subtypes.md) for canonical conventions.

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

- **subtype**: Optional finer classification within the entity
  type. Free-form string, not an enum, to avoid combinatorial
  explosion. See [subtypes.md](subtypes.md) for canonical
  conventions per entity type.

- **description**: Critical for LLM resolution. Should include
  distinguishing details: role, country, founding year, etc.
  This is what makes the LLM-first approach work.

- **valid_from / valid_until**: Temporal bounds. Many entities
  are time-bounded (political offices, corporate existence).
  `None` means unbounded on that side.

- **updated_at**: When this record was last modified. ``None``
  until the first update. Used for cache invalidation and
  freshness tracking — lets consumers know which entities
  have stale data.

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

- **Co-mention queries**: `find_co_mentioned(entity_id, since)`
  joins provenance on `document_id` to find entities that
  appear in the same articles. Returns `(Entity, count)` tuples
  sorted by co-occurrence count. A composite index
  `(document_id, entity_id)` makes the join fast. This is the
  core query for event-driven strategies — e.g. "which assets
  and companies were discussed alongside CPI this week?"

- **Temporal provenance queries**:
  `find_recent_mentions(entity_id, since)` returns
  provenance records after a given datetime, ordered most
  recent first. A composite index `(entity_id, detected_at)`
  makes time-windowed lookups fast — e.g. "all mentions
  of the Federal Reserve in the last 24 hours."


## Entity and relationship filtering

- **By relation type**: `find_relationships_by_type(relation_type)`
  filters on the raw free-form string before any RELATION_KIND
  normalization — e.g. "all `acquired` relationships." Indexed on
  `relation_type`.

- **By lifecycle status**: `find_entities_by_status(status)` returns
  entities filtered by `EntityStatus` (ACTIVE, MERGED, DEPRECATED).
  Any consumer listing entities should filter to ACTIVE to exclude
  stale or merged records.

- **Active relationships**: `find_active_relationships(entity_id)`
  returns relationships where `valid_until` is unbounded or in the
  future. Answers "current state" queries like "who is the current
  CEO?" or "which sanctions are in effect?" without client-side
  filtering.

- **Name prefix search**: `find_by_name_prefix(prefix)` does a
  case-insensitive prefix match on `canonical_name` — e.g.
  "App" matches "Apple Inc." and "Applied Materials". Indexed on
  `canonical_name COLLATE NOCASE` for fast autocomplete lookups.

- **Entity counts**: `count_entities_by_type()` returns a
  `{type: count}` mapping via a single `GROUP BY` query — useful
  for dashboard stats without fetching all rows.

- **New entity monitoring**: `find_entities_since(datetime)`
  returns entities with `created_at >= since`, newest first.
  Indexed on `created_at` for fast lookups — e.g. "what entities
  were discovered today?"


## Relationship — open-ended and temporal

- **relation_type is a string, not an enum**: The space of
  relationships in news is unbounded ("acquired", "invaded",
  "appointed", "sanctioned", "married", "funded", etc.).
  An enum would constantly need extending.

- **qualifier_id**: Optional FK to an entity (typically ROLE)
  that qualifies the relationship. Solves n-ary
  relationships: Person->Company qualified by CTO role means
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
  Note: `valid_from` is stored as `""` (empty string) when
  no temporal bound is set, not as NULL — because SQLite
  treats `NULL != NULL`, which would allow silent duplicate
  rows with the same composite key.
- **Multi-qualifier**: Only one qualifier per relationship.
  Sufficient for the news domain (person+role+company). If
  needed, add a join table later.
- **Structured attributes** (ownership percentages, rating
  values, price targets, deal amounts): Out of scope. The
  KG tracks *that* a relationship exists, not quantitative
  details about it. Numerical data belongs in external
  tables that can be maintained independently and joined
  via `entity_id`. This is the same boundary applied to
  METRIC release schedules and sentiment scores.


## Audit log — time-travel and revert

Every entity and relationship mutation is recorded in
append-only history tables (`entity_history`,
`relationship_history`). The approach is **snapshot-based**:
each revision stores the full state of the record after the
operation, not a delta.

### Why an audit log?

A financial KG needs point-in-time queries ("what did the KG
know about Apple on March 15th?") and the ability to revert
bad updates without losing the trail. Event sourcing was
considered but rejected as overkill — mutations are infrequent
relative to reads, and full snapshots are simpler to query and
restore from.

### Operations logged

| Operation  | Trigger                                       |
|------------|-----------------------------------------------|
| `create`   | First `save_entity()` / `save_relationship()` |
| `update`   | Subsequent `save_entity()` on existing ID     |
| `merge`    | `merge_entities()` — logged for both entities |
| `revert`   | `revert_entity()` — restores a prior revision |

### What is captured

- **Entity revisions** include the full entity snapshot
  plus aliases (as a JSON array) and an optional `reason`
  field for human-readable context.
- **Relationship revisions** include the full relationship
  snapshot plus an optional `reason` field.
- **Provenance** is not audited — it is append-only by
  nature (detections are recorded, never modified).

### Query methods

- `get_entity_history(entity_id)` — all revisions in
  chronological order.
- `get_entity_at(entity_id, datetime)` — entity state at
  a point in time (latest revision before that timestamp).
- `revert_entity(entity_id, revision_id)` — restore a
  prior snapshot and log a `"revert"` operation.
- `get_relationship_history(entity_id)` — all relationship
  revisions involving the entity.
