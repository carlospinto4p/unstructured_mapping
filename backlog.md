## Backlog

### 2026.04.16 (optimization review v0.48.9)

- [x] **MEDIUM / Small** — Batch mention-count lookups in `cli/audit_aliases.py::score_collisions` (line 132-155). Currently calls `store.count_mentions_for_entity(eid)` once per collision-side — O(collisions × sides) queries. Replace with a single grouped query (`SELECT entity_id, COUNT(*) FROM provenance WHERE entity_id IN (…) GROUP BY entity_id`) populating a lookup dict. Adding `count_mentions_for_entities(ids)` to `ProvenanceMixin` would keep the `# noqa: SLF001` count at zero.
- [x] **MEDIUM / Small** — Batch duplicate checks in `cli/wikidata_seed.py::_already_imported` (line 124-138). Runs `alias_exists` + `exists_by_name_and_type` per candidate — 2 queries × ~500 candidates per import. Prefetch the full `wikidata:Q…` alias set and the `(canonical_name.lower(), entity_type)` set once before the loop, then do O(1) Python `in` checks. Clean fit behind a new `store.wikidata_qids()` + `store.name_type_pairs()` helper pair.
- [ ] **MEDIUM / Small** — Push token-length filter down into SQL in `knowledge_graph/_audit_mixin.py::find_short_snippets` (line 108-130). Current query `SELECT ... FROM provenance JOIN entities` loads every row then filters in Python via `_estimate_tokens`. Add `WHERE LENGTH(context_snippet) < ? * 4` (the char-per-token heuristic) so SQLite skips long snippets before hydration. Python still applies the exact token estimate as a post-filter.
- [ ] **LOW / Small** — Missing index on `relationships.document_id`. `find_relationships_by_document` (added v0.48.5, used by `cli/preview.py`) does a full table scan on every call. Add `CREATE INDEX idx_rel_document ON relationships (document_id)` to `_CREATE_INDEXES` in `knowledge_graph/storage.py:205`. Reads should benefit immediately; migration is a no-op (`CREATE INDEX IF NOT EXISTS`).


### 2026.04.14 (Wikidata import follow-ups)

- [ ] **MEDIUM / Small** — `company` SPARQL query leaks central banks. "Bank of Japan" and "Swiss National Bank" show up in `company.json` because they hold P414 listing entries. Fix: add a `MINUS { ?item wdt:P31/wdt:P279* wd:Q66344 }` clause (central bank) analogous to the exchange/bank fix.
- [ ] **MEDIUM / Medium** — Deduplicate within-snapshot rows. The index query produces "Stoxx Europe 600 Index" × 289 (of 601 rows); currency has "euro" × 27; company has "Shell" × 18. The v0.35.2 subquery-LIMIT idiom deduplicates item QIDs but the OPTIONAL joins (ticker/exchange/MIC etc.) still fan out. Options: (a) tighten the SPARQL with `SAMPLE()` / `GROUP_CONCAT` over OPTIONALs, or (b) deduplicate by QID in `mapper.py` before writing the snapshot. Impact: ~40% smaller snapshot files and cleaner diffs on refresh.
- [ ] **LOW / Small** — Residual exchange noise after v0.37.1: Deutsche Bank ATS/Off Exchange/Super X, FXCM, Convergex, KCG Americas still slip through. Verify Wikidata QIDs for foreign-exchange broker, alternative trading system, and market maker, then extend the `MINUS` list in `EXCHANGES_QUERY`. Alternatively, maintain a small curated blocklist of QIDs if class-based exclusion keeps missing.
- [ ] **LOW / Small** — Expand curated seed coverage for thin categories surfaced by the overlap review: regulators (SEC, CFTC, ECB-as-regulator, CSRC, BaFin, MAS), top-15 currencies beyond EUR/CHF/GBP, top-15 indices beyond Dow/FTSE 100/Hang Seng/Nasdaq. Curated entries get hand-tuned LLM descriptions, so they beat Wikidata's generic text for resolution quality.

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
