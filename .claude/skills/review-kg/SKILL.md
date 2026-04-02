---
name: review-kg
version: 1.0.0
description: Review KG architecture and design for gaps, inconsistencies, and improvements. Evaluates from the perspective of quant researchers and market analysts building custom strategies.
---

Review the knowledge graph design for completeness, consistency,
and fitness for quantitative finance and market analysis use cases.

## Inputs

Read ALL of the following before producing output:

1. `docs/knowledge_graph/design.md` — design philosophy and rationale
2. `docs/knowledge_graph/subtypes.md` — subtype conventions
3. `docs/knowledge_graph/schema.md` — SQLite table schemas
4. `src/unstructured_mapping/knowledge_graph/models.py` — data models
5. `src/unstructured_mapping/knowledge_graph/storage.py` — storage layer
6. `backlog.md` — existing open items (avoid duplicating them)

## Audience

The KG will be consumed by:

- **Quant researchers** building systematic strategies from news signals
- **Market analysts** tracking macro themes, sector rotations, and
  event-driven opportunities
- **Trading systems** that need structured, queryable entity data
  to correlate with price/volume feeds

## Review checklist

Evaluate the design against each area below. For each, note whether
the current design is **adequate**, has a **gap**, or has an
**inconsistency**.

### 1. Entity type coverage

- Are the ten entity types sufficient to model the financial news
  domain? What real-world entities fall through the cracks?
- Are there entity types that overlap or cause classification
  ambiguity for an LLM?
- Would a quant researcher need entity types not currently modeled?

### 2. Subtype fitness

- Are the canonical subtypes in `subtypes.md` sufficient for
  financial use cases?
- Are there missing subtypes that would block common queries?
  (e.g., "show me all sovereign bonds", "find all tech companies")
- Is the deferred sub-classification plan (e.g., company →
  public/private) adequate, or does it need to be promoted?

### 3. Relationship expressiveness

- Can the relationship model capture the connections a market
  analyst cares about? (ownership chains, supply chains, regulatory
  jurisdiction, competitive landscape, policy impact)
- Are temporal bounds on relationships sufficient for event-driven
  strategies (e.g., "CEO changed", "sanction imposed")?
- Is the qualifier system (ROLE, RELATION_KIND) expressive enough?

### 4. Market-signal readiness

- Can the KG support linking entities to price-moving events?
- Is there enough structure to correlate entities with time-series
  data (prices, volumes, economic releases)?
- Can a trading system answer: "which assets are affected by this
  entity/event/metric?"

### 5. Query patterns

- Can the storage layer support the queries a quant would run?
  (e.g., "all companies mentioned alongside CPI this month",
  "relationship graph for a given asset", "entities by subtype
  with temporal filter")
- Are there missing indexes or query methods?

### 6. Schema gaps

- Are there fields that quant/analyst workflows would need but
  are not modeled? (e.g., external identifiers like ISIN/CUSIP,
  sector codes, exchange listings)
- Are deferred fields (in design.md) correctly prioritized?

### 7. Consistency

- Do the models, schema, docs, and subtypes all agree?
- Are there contradictions between design.md rationale and actual
  implementation?

## Output format

```
## KG Design Review

### Summary
[2-3 sentence overall assessment]

### Findings

| # | Area | Status | Finding |
|---|------|--------|---------|
| 1 | ...  | GAP / INCONSISTENCY / ADEQUATE | ... |

### Recommendations
[Numbered list, sorted by impact. For each: what to do, why it
matters for quant/analyst use cases, and suggested priority
(HIGH/MEDIUM/LOW).]

### Suggested backlog items
[Ready-to-paste `- [ ]` items for `backlog.md`. Check against
existing open items to avoid duplicates.]
```
