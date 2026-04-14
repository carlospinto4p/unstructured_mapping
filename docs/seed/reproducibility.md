# KG Reproducibility Strategy

How a cloned repo reconstructs the populated knowledge graph.

## Decision

The populated `data/knowledge.db` is **not** checked into
git. Instead, the **seed JSON files under `data/seed/` are
the source of truth** for KG population:

- `data/seed/financial_entities.json` — curated entities
  with hand-tuned LLM-facing descriptions.
- `data/seed/wikidata/<type>.json` — one snapshot per
  Wikidata category (`currency`, `central_bank`,
  `exchange`, `regulator`, `index`, `crypto`, `company`),
  written by `wikidata_seed --snapshot`. Format is
  compatible with `cli.seed`, so they can be replayed
  offline against a fresh database.

A fresh clone rebuilds the KG by running the curated
seed first, then each Wikidata snapshot in turn. No
network access is required.

## Why not commit the `.db`?

Considered and rejected:

- **Binary churn in git.** Every re-seed rewrites a
  large opaque blob; merges are unresolvable.
- **Silent staleness.** A committed DB drifts from
  Wikidata with no signal. The seed JSONs, by contrast,
  are diffable in PRs — schema drift, renamed entities,
  and new additions all show up as textual changes.
- **`.gitignore` already excludes `*.db`.** Carving out
  an exception for one DB invites confusion about which
  DBs are tracked.

## Why not rebuild live from Wikidata each time?

Also considered and rejected:

- **Non-determinism.** Wikidata results shift between
  runs (labels change, classes get retagged, the company
  query has no stable ORDER BY). Two clones seeded on
  different days would hold different KGs.
- **Network dependency for a deterministic artefact.**
  CI, offline work, and Wikidata outages would all
  block rebuilds.
- **Rate limits.** The SPARQL endpoint throttles and
  occasionally returns 502s (see v0.35.2 for the query
  rewrite that fixed the company-query timeout).

Committing the snapshots captures a single authoritative
fetch and makes every subsequent rebuild reproducible.

## Trade-offs accepted

- **Snapshots go stale.** The committed JSONs freeze
  Wikidata state at the moment of capture. Refreshing
  them is a deliberate act (re-run `wikidata_seed
  --snapshot`, review the diff, commit). This is a
  feature: refreshes are reviewable.
- **Seven files to keep in sync.** Any change to the
  SPARQL queries or mappers should be followed by a
  snapshot refresh; otherwise the snapshots and the
  live query diverge silently.
- **Snapshot replay loses `reason="wikidata-seed"`
  provenance.** `cli.seed` tags its writes with
  `reason="seed"`. A future improvement could teach the
  loader (or add a new snapshot-replay CLI) to preserve
  the origin reason, letting `entity_history` audits
  still distinguish Wikidata-sourced rows.

## Rebuild workflow

```bash
# 1. Curated seed first — canonical names and
#    LLM-facing descriptions take precedence.
uv run python -m unstructured_mapping.cli.seed \
    --seed data/seed/financial_entities.json

# 2. Replay each Wikidata snapshot.
for f in data/seed/wikidata/*.json; do
    uv run python -m unstructured_mapping.cli.seed \
        --seed "$f"
done
```

Dedup is by `canonical_name` + `entity_type`
(case-insensitive), so the order matters: curated entries
win over Wikidata rows that happen to share a name.

A `cli/populate.py` orchestrator that wraps this
sequence into a single command is tracked in `backlog.md`.
