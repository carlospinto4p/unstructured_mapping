## Backlog

### 2026.04.14 (improvements review v0.38.2)

- [x] **HIGH / Medium** — Chunk aggregation + conflict resolution. Done in v0.41.0: `pipeline/aggregation.py` with `ChunkAggregator`; per-chunk processing now collects outcomes without writes, the aggregator dedupes proposals (by lowercased name+type, keeping the longest description) and relationships (by source+target+relation_type, keeping the richest snippet), flags type conflicts as `ProposalConflict` records, and the orchestrator persists once per article inside a single transaction.
- [x] **MEDIUM / Medium** — Document-level alias pre-scan. Done in v0.41.0: when a segmenter produces >1 chunk, the orchestrator runs the detector over the full article body, batch-fetches every candidate entity via `store.get_entities`, and passes the set to each chunk's `LLMEntityResolver.resolve(..., extra_candidates=...)`. Chunk 5 referring to "the company" now sees Apple in its KG context window even when only chunk 1 mentioned Apple.
- [x] **MEDIUM / Medium** — Running entity header for cross-chunk coreference. Done in v0.42.0: `LLMEntityResolver.resolve(..., prev_entities=...)` accepts a per-call override; the pipeline threads the accumulating list of resolved mentions forward so chunk 5 sees what chunks 1–4 resolved to. Works for entities the KG doesn't yet have (LLM proposals mid-article) — not just pre-scanned ones.
- [x] **HIGH / Medium** — Run scorecard. Done in v0.42.0: new `run_metrics` table keyed on `run_id`, captured via an in-run `_MetricsAccumulator`. Stores chunks_processed, mentions_detected, mentions_resolved_alias, mentions_resolved_llm, llm_resolver_calls, llm_extractor_calls, proposals_saved, relationships_saved, provider/model identity, wall-clock seconds. Token counts deliberately excluded — the `LLMProvider` contract does not expose usage today; tracked as a separate follow-up.
- [x] **MEDIUM / Small** — Expose LLM token usage on `LLMProvider`. Done in v0.43.0: `TokenUsage` dataclass on the provider, `last_token_usage` property implemented on Ollama and Claude, plumbed through resolver/extractor/cold-start into `RunMetrics` (`input_tokens` / `output_tokens` + `total_tokens`). Schema migrated via `_migrate_run_metrics`.
- [ ] **MEDIUM / Medium** — Cold-start benchmarking CLI. `docs/pipeline/13_cold_start.md` already designs the feature; add `cli/benchmark_cold_start.py` that runs a labelled article set twice (cold-start vs KG-driven) and reports precision/recall against ground truth. Starts small (50-100 labelled articles) and grows as a regression harness for prompt changes.
- [ ] **MEDIUM / Medium** — Temporal + confidence qualifiers on relationships. The `relationships` schema already carries `valid_from` / `valid_until`; extend `LLMRelationshipExtractor` prompts to infer temporal bounds when the text states them ("CEO from 2015 to 2020"), plus an optional `confidence` field (0–1). Then expose `find_relationships(..., at=date, min_confidence=0.8)` for time-sliced queries.
- [ ] **MEDIUM / Small** — Pipeline dry-run / preview mode. Add `--dry-run` to `cli/populate.py` (and/or a new `cli/preview.py`) that runs detection + resolution + extraction on a single article without writing to the KG, dumping proposed entities and relationships as JSON. Makes edge-case debugging (ambiguous mentions, new proposals) cheap without polluting the DB.
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
