---
name: review-kg-scope
version: 1.0.0
description: Audit KG scope boundaries — flag anything that leaks quantitative data, operational metadata, or analysis concerns into the KG. The KG is an index into the news, not a database of facts or numbers.
---

Audit the knowledge graph for scope violations. The KG is
an **index into the news** — it stores just enough metadata
for an LLM to detect, resolve, and link entities. Everything
else belongs in external tables joined via `entity_id`.

## Inputs

Read ALL of the following before producing output:

1. `docs/knowledge_graph/design.md`
2. `docs/knowledge_graph/subtypes.md`
3. `docs/knowledge_graph/schema.md`
4. `docs/knowledge_graph/relationships.md`
5. `src/unstructured_mapping/knowledge_graph/models.py`
6. `src/unstructured_mapping/knowledge_graph/storage.py`

## The KG boundary

**In scope** (the KG stores this):

- Entity identity: names, aliases, types, subtypes
- Entity descriptions: natural-language context for LLM
  resolution and disambiguation
- Relationships: *that* a connection exists between
  entities, its type, temporal bounds, and provenance
- Provenance: which document mentioned which entity,
  with context snippets for disambiguation
- Audit history: snapshots of entity/relationship state
  over time

**Out of scope** (belongs in external tables):

- Quantitative values: ownership percentages, deal
  amounts, price targets, rating values, EPS numbers,
  stake sizes
- Operational metadata: release schedules, frequencies,
  economic calendar data
- Analysis outputs: sentiment scores, polarity,
  relevance rankings, signal strength
- Market data: prices, volumes, returns, spreads
- External identifiers: tickers, ISINs, FIGIs (planned
  for `external_ids` table, not on the entity itself)

## What to flag

### 1. Schema violations

- Fields on Entity, Relationship, or Provenance that
  store numbers, percentages, scores, or amounts
- Columns that hold operational metadata (schedules,
  frequencies, calendar data)
- Fields that duplicate what external tables should own

### 2. Documentation drift

- Passages in design.md, subtypes.md, or relationships.md
  that suggest storing quantitative data in the KG
- Missing or inconsistent scope boundary statements
- Examples that imply the KG holds numbers (e.g. "stores
  the 7.2% ownership stake" rather than "tracks that
  BlackRock owns a stake in Apple")

### 3. Code drift

- Query methods that return or filter by numeric values
  that shouldn't be in the KG
- Storage methods that accept quantitative parameters
- Description fields being used as structured data stores
  (e.g. parsing numbers from description text)

### 4. Backlog contamination

- Open backlog items that would pull quantitative data
  or analysis concerns into the KG
- Items that blur the boundary between the KG and
  external systems

## Output format

```
## KG Scope Audit

### Summary
[1-2 sentence overall assessment: clean / minor drift /
scope violation found]

### Findings

| # | Area | Status | Finding |
|---|------|--------|---------|
| 1 | ...  | CLEAN / DRIFT / VIOLATION | ... |

### Recommendations
[Numbered list. For each: what to fix and why it matters
for keeping the KG focused.]
```
