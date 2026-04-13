# Wikidata Seed Pipeline

Bootstraps the knowledge graph with financial entities
pulled from the [Wikidata Query Service][wdqs]. The
pipeline queries SPARQL, maps each row to an `Entity`,
dedups against existing KG entries, and persists the
remainder via `KnowledgeStore.save_entity`.

[wdqs]: https://query.wikidata.org/

## Scope

The KG is narrowly scoped to entities that can plausibly
move financial markets. Wikidata contains millions of
entities, so the seed pipeline uses aggressive filters
instead of bulk-dumping.

**Phase 1 (implemented):**

- **ORGANIZATION / company** — instances of
  `Q4830453` (business) or any subclass that have a
  stock-exchange listing (`P414`). Ordered by market
  capitalisation (`P2226`) so a small `--limit` still
  captures the most impactful firms.

**Later phases (planned):**

- `ORGANIZATION / central_bank`, `regulator`, `exchange`,
  `rating_agency`
- `ASSET / currency`, `index`, `crypto`, `commodity`
- `LEGISLATION` — flagship financial regulations
- `PERSON` — CEOs, central bank governors, finance
  ministers (via relationship queries against listed
  companies rather than broad instance-of filters)

New phases only need a SPARQL template in
`wikidata/queries.py` and a mapper in `wikidata/mapper.py`;
the CLI dispatches via a small `_TYPE_HANDLERS` registry.

## External-identifier alias convention

Wikidata carries rich identifiers (QIDs, tickers, ISINs)
that don't fit the `Entity` schema directly. Until the
dedicated `external_ids` table lands (see `backlog.md`),
these IDs are stored as **prefixed aliases** so they
survive in the KG and remain queryable via
`KnowledgeStore.find_by_alias`:

| Prefix          | Example                 | Source property    |
|-----------------|-------------------------|--------------------|
| `wikidata:`     | `wikidata:Q312`         | the entity's QID   |
| `ticker:`       | `ticker:AAPL`           | `P249` (listing)   |
| `isin:`         | `isin:US0378331005`     | `P946`             |

Plain human-readable aliases (`"Apple"`, `"FOMC"`) remain
unprefixed — entity detection in free text must still
match them as-is.

### Why the colon prefix?

- **Namespacing**: `ticker:AAPL` cannot collide with a
  plain alias `"AAPL"` that a different pipeline may
  insert for entity detection.
- **Reversibility**: when the `external_ids` table is
  introduced, the migration can scan prefixed aliases,
  lift them into the new table, and drop them from the
  alias set — no ambiguity about which aliases were
  external IDs.
- **Deduplication**: the seed loader uses
  `store.find_by_alias("wikidata:Qxxx")` as the primary
  idempotency check, which is much cheaper than a
  fuzzy name match.

## Dedup strategy

Two-tier, in order:

1. **`wikidata:Qxxx` alias hit** — a previous Wikidata
   import covered this entity. Skip.
2. **`canonical_name` + `entity_type` match
   (case-insensitive)** — a curated seed entry or other
   pipeline already covers this entity under a human
   label. Skip to avoid splitting the curated record.

Rows that hit neither are inserted with
`reason="wikidata-seed"` in the `entity_history` audit
log, so post-hoc queries can count exactly what the
Wikidata pipeline contributed.

## Descriptions (phase 1: templates only)

Wikidata descriptions are short and often not aimed at
finance readers ("American multinational technology
company"). The phase-1 mapper therefore builds a
template description from structured fields
(country, exchange, ticker) and appends the Wikidata
description if present. This is enough for the LLM to
disambiguate — it is not meant to be a company profile.

A later phase will add optional LLM enrichment
(`--enrich-llm`) that rewrites descriptions to emphasise
market-moving context (primary business, key macro
exposures, regulatory footprint).

## Running the pipeline

```bash
# Dry run — fetches and maps, no DB writes
uv run python -m unstructured_mapping.cli.wikidata_seed \
    --type company --limit 10 --dry-run

# Live import, top 500 companies by market cap
uv run python -m unstructured_mapping.cli.wikidata_seed \
    --type company --limit 500

# Write a reproducibility snapshot alongside the import
uv run python -m unstructured_mapping.cli.wikidata_seed \
    --type company --limit 100 \
    --snapshot data/seed/wikidata_companies.json
```

The snapshot file is compatible with `cli.seed`, so a
captured import can be re-played offline against a fresh
database without hitting the SPARQL endpoint again.

## Why not `SPARQLWrapper`?

The project already depends on `httpx`, and the client
needs are tiny (one endpoint, JSON only, mild retry
logic). Adding `SPARQLWrapper` would pull in an
additional dependency for ~50 lines of code.
