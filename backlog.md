## Backlog

### 2026.04.14 (improvements review v0.38.2)

- [x] **MEDIUM / Medium** — Temporal + confidence qualifiers on relationships. Done in v0.45.0: `Relationship.confidence` + `relationships.confidence` column (nullable REAL); Pass 2 prompt + parser capture an optional 0–1 score (clamped, non-numeric → None); new `store.find_relationships(entity_id, *, at=date, min_confidence=N)` combines an at-date window with a confidence floor. `valid_from` / `valid_until` inference continues via the existing Pass 2 prompt fields.
- [x] **MEDIUM / Small** — Pipeline dry-run / preview mode. Done in v0.46.0: new `cli/preview.py` runs one article against a throwaway copy of the KG and emits mentions / proposals / relationships / token usage as JSON. Supports `--article-file`, `--text`, `--cold-start`, and `--no-llm`. Source KG is never mutated.
- [ ] **MEDIUM / Small** — Alias-collision CLI. `knowledge_graph.validation.find_alias_collisions` already exists as an audit function; wrap it in `cli/audit_aliases.py` that ranks collisions by mention prevalence and proposes merges when the colliding entities share a type. Human confirms before any merge runs. Improves detection precision as the KG grows.
- [ ] **LOW / Small** — Provenance quality audit CLI. Surface low-signal provenance (context snippets < N tokens, entities with < 2 distinct mentions, temporal spread < 1 day) to flag where the pipeline is under-covering foundational entities. Three or four SQL queries + CSV export.
- [ ] **LOW / Small** — Query cookbook. Add `docs/examples/queries.sql` with a handful of labelled queries (most-mentioned entities this week, entity merge history, relationships by relation_type, provenance timeline per entity) so an analyst can explore the KG without reading the schema doc first.

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
