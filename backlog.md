## Backlog

### 2026.04.13 (KG population plan)

- [x] **MEDIUM / Medium** — Add `cli/populate.py` orchestrator that runs the whole seed + Wikidata sequence with a single command and writes a summary report. Alternative: keep manual per-type invocation so each stage can be inspected before proceeding. Decide before implementing.
- [x] **MEDIUM / Small** — After population, review the `entity_history` audit log for `reason="wikidata-seed"` conflicts (Wikidata rows skipped because a curated entry covered them) — those are the most interesting signals for improving the curated seed. Done: 24 distinct name overlaps across 91 curated entries. Coverage is solid for central banks/exchanges/crypto; thin on regulators (only FCA), currencies, and indices. Also surfaced two noise bugs tracked below.

### 2026.04.14 (refactor review v0.38.0)

- [x] **HIGH / Medium** — Factor Wikidata row mappers in `wikidata/mapper.py`. All seven `map_*_row()` functions share the same shape. Done in v0.38.1: single `_make_row_mapper()` factory; each type is one builder function plus one factory call.
- [x] **MEDIUM / Small** — Share seed dedup + import loop between `cli/seed.py` and `cli/wikidata_seed.py`. Done in v0.38.1: `cli/_seed_helpers.py` with `import_with_dedup()` + `exists_by_name_and_type()`.
- [x] **MEDIUM / Small** — Harmonise the CLI modules. Done in v0.38.1 with a narrowed scope: `db_health` now has a `_build_parser()` matching the other CLIs. The broader "shared cli runner" proposal was dropped — the remaining divergences (db_health using `print`, per-loader reporting formats) are intentional, not accidental, so a forced merge would add complexity without clarity.
- [x] **MEDIUM / Small** — Move `_TYPE_HANDLERS` out of `cli/wikidata_seed.py` into the `wikidata` package. Done in v0.38.1: `wikidata/registry.py` exposes `TYPE_REGISTRY` and a `TypeHandler` dataclass.
- [x] **LOW / Small** — Deduplicate the `_write_seed` helper between test files. Done in v0.38.1: `tests/unit/conftest.write_seed_file()`.

### 2026.04.14 (optimize review v0.38.1)

- [x] **HIGH / Small** — N+1 entity lookups in `pipeline/resolution.py`. Done in v0.38.2: `KnowledgeStore.get_entities(ids)` batch method; `LLMEntityResolver` takes an optional `entity_batch_lookup` and collects candidates in one query.
- [x] **HIGH / Medium** — Per-row `commit()` in write helpers. Done in v0.38.2: `SQLiteStore._commit()` + `SQLiteStore.transaction()` context manager (reentrant, rolls back on exception). `import_with_dedup` wraps its loop in one transaction, cutting ~2000 fsyncs per populate run to 1. All 11 commit sites in the KG + article stores now go through `_commit()`.
- [x] **MEDIUM / Small** — Missing composite name+type index. Done in v0.38.2: `idx_entity_name_type`; `KnowledgeStore.exists_by_name_and_type` now filters both columns in a single SQL query with `LIMIT 1`.
- [x] **MEDIUM / Small** — Per-article idempotency query in orchestrator. Done in v0.38.2: `documents_with_provenance(ids) -> set[str]` pre-fetches the whole run once; `_process_article` now checks set membership in memory.
- [x] **MEDIUM / Small** — `find_by_alias` used as existence probe. Done in v0.38.2: `KnowledgeStore.alias_exists(alias)` (SELECT 1 ... LIMIT 1, no JOIN); Wikidata QID dedup uses it.
- [x] **MEDIUM / Small** — Unbounded detector-init entity scan. Done in v0.38.2: example + docs recommend `limit=5000` and the docstring warns future readers that unbounded fetches blow up trie-construction cost.
- [x] **LOW / Small** — ~~Add UNIQUE index on `articles.document_id`~~. False finding: the table already declares `document_id TEXT NOT NULL UNIQUE` (`web_scraping/storage.py:23`), and `INSERT OR IGNORE` trips on it. Agent scan missed the inline constraint; no change needed.

### 2026.04.14 (improvements review v0.38.2)

- [x] **HIGH / Large** — Implement the document-segmentation module designed in `docs/pipeline/09_chunking.md`. Done in v0.39.0: `pipeline/segmentation/` with ABC + 4 segmenters (News / Research / Transcript / Filing) + `DocumentType` enum + 19 unit tests. Pipeline wiring (ingestion interface, document-level alias pre-scan, running entity header) still to come — tracked as a new follow-up below.
- [ ] **HIGH / Medium** — Chunk aggregation + conflict resolution (follow-up to the segmenter above, also designed in `docs/pipeline/09_chunking.md`). `ChunkAggregator` runs post-extraction: dedupes entities across chunks, merges relationships on `(source_id, target_id, relation_kind)`, flags same-name-different-type conflicts for review. Needed the moment segmentation produces >1 chunk per document.
- [ ] **HIGH / Medium** — Wire segmentation into the pipeline. Current `Pipeline.run` takes already-segmented articles; needs a `DocumentType`-aware entry point that (a) dispatches to the right `DocumentSegmenter`, (b) runs the design's document-level alias pre-scan once, (c) processes each chunk with a running entity header prepended to the resolver prompt, (d) hands all chunk results to `ChunkAggregator` before persistence. Blocks #2 above.
- [ ] **MEDIUM / Medium** — Hybrid-fallback sub-chunking for oversized sections. A 30-page Risk Factors section currently comes out as one huge chunk; design calls for sub-chunking at paragraph boundaries with 10-20% overlap when a section exceeds the token budget. Implement as a shared helper used by `ResearchSegmenter` / `TranscriptSegmenter` / `FilingSegmenter` when given an optional `max_tokens` cap.
- [ ] **HIGH / Medium** — Run scorecard: persist per-run metrics (chunks scanned, detections, unambiguous vs LLM-resolved mentions, proposals created, relationships extracted, LLM tokens in/out, provider+model, wall-clock) to a new `run_metrics` table keyed by `run_id`. Exposes a trend line for pipeline quality + cost; foundational for any A/B comparison (Ollama vs Claude, cold-start vs KG-driven, prompt revisions).
- [ ] **MEDIUM / Medium** — Cold-start benchmarking CLI. `docs/pipeline/13_cold_start.md` already designs the feature; add `cli/benchmark_cold_start.py` that runs a labelled article set twice (cold-start vs KG-driven) and reports precision/recall against ground truth. Starts small (50-100 labelled articles) and grows as a regression harness for prompt changes.
- [ ] **MEDIUM / Medium** — Temporal + confidence qualifiers on relationships. The `relationships` schema already carries `valid_from` / `valid_until`; extend `LLMRelationshipExtractor` prompts to infer temporal bounds when the text states them ("CEO from 2015 to 2020"), plus an optional `confidence` field (0–1). Then expose `find_relationships(..., at=date, min_confidence=0.8)` for time-sliced queries.
- [ ] **MEDIUM / Small** — Pipeline dry-run / preview mode. Add `--dry-run` to `cli/populate.py` (and/or a new `cli/preview.py`) that runs detection + resolution + extraction on a single article without writing to the KG, dumping proposed entities and relationships as JSON. Makes edge-case debugging (ambiguous mentions, new proposals) cheap without polluting the DB.
- [ ] **MEDIUM / Small** — Alias-collision CLI. `knowledge_graph.validation.find_alias_collisions` already exists as an audit function; wrap it in `cli/audit_aliases.py` that ranks collisions by mention prevalence and proposes merges when the colliding entities share a type. Human confirms before any merge runs. Improves detection precision as the KG grows.
- [ ] **LOW / Small** — Provenance quality audit CLI. Surface low-signal provenance (context snippets < N tokens, entities with < 2 distinct mentions, temporal spread < 1 day) to flag where the pipeline is under-covering foundational entities. Three or four SQL queries + CSV export.
- [ ] **LOW / Small** — Query cookbook. Add `docs/examples/queries.sql` with a handful of labelled queries (most-mentioned entities this week, entity merge history, relationships by relation_type, provenance timeline per entity) so an analyst can explore the KG without reading the schema doc first.

### 2026.04.14 (Wikidata import follow-ups)

- [x] **MEDIUM / Small** — Tighten the `exchange` SPARQL query to exclude banks and broker-dealers. The v0.35.2 fix (`wdt:P31/wdt:P279*` → `wdt:P31`) wasn't enough — Wikidata directly tags Commerzbank, FXCM, Convergex, KCG Americas, OTP banka etc. as P31 stock exchange. Candidate fixes: add a `MINUS` clause for `Q22687` (bank) / `Q806735` (broker-dealer), or apply a curated blocklist in the mapper. Done in v0.37.1: `MINUS` clauses added; Commerzbank and OTP banka are now excluded. Residual noise (DB ATS, FXCM, Convergex, KCG Americas) tracked below — they're tagged with forex-broker / ATS / market-maker classes that the current MINUS doesn't cover.
- [x] **LOW / Small** — Preserve Wikidata provenance on snapshot replay. `cli.seed` currently tags all replayed rows with `reason="seed"`, so rebuilding from `data/seed/wikidata/*.json` loses the `reason="wikidata-seed"` signal in `entity_history`. Options: teach `cli.seed` to read a `reason` hint from the snapshot header, or add a dedicated `cli/replay_snapshot.py` that preserves the origin reason. Done in v0.38.0: `load_seed` honours a top-level `"reason"` field; snapshots now write `"reason": "wikidata-seed"` and all 7 snapshots refreshed.
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
