## Backlog

### 2026.04.23 (improvements review v0.49.20)

- [x] **MEDIUM / Small** — Parquet export format follow-up to `cli/export.py`. The v0.51.0 export ships `jsonl` and `json-ld` but defers `parquet` to keep the default install free of `pyarrow`. Add an `export` optional extra in `pyproject.toml` (`pyarrow>=15`), a `--format parquet` branch that uses `pyarrow.Table.from_pylist` + `write_table` per stream, and a clear ImportError when the extra is missing. Preserves the existing filter / opt-in surface so the three format branches stay symmetric.
- [x] **MEDIUM / Small** — Golden-snapshot KG validation gate. The storage layer already enforces per-write validation (temporal bounds, alias collisions), but there's no way to record a baseline and compare a new run against it. Add `cli/validate_snapshot.py` with `--record <path>` (persist counts by type/subtype + top-K alias collisions + provenance density to JSON) and `--check <baseline>` (diff a live KG against the file; nonzero exit on threshold breach). Useful as a CI gate and a quick "did my latest change blow up quality?" check.
- [x] **MEDIUM / Medium** — Per-article failure tracking + `--resume-run` for `cli/populate.py`. `IngestionRun` today carries only aggregate counts; a crashed 1000-article batch has no record of which document_ids succeeded so the restart re-processes everything and burns LLM tokens. Add an `article_failures` child table (run_id, document_id, error_message, failed_at) that the orchestrator populates in its per-article `except` block, plus a `--resume-run <run_id>` flag on `populate` that fetches the failed list and only re-queues those. Blocks the next suggestion. *(v0.54.0 shipped the table, orchestrator wiring, store methods, and `Pipeline.run(resume_run_id=...)`. CLI flag deferred — see below.)*
- [x] **MEDIUM / Small** — Batch-ingest CLI with `--resume-run`. Follow-up to v0.54.0. Shipped as `cli/ingest.py`: reads from the scraped-articles DB, supports `--source` / `--limit` filters, cold-start / no-LLM / full pipeline modes, and `--resume-run <run_id>` which pulls the failed document ids from the KG and hands them to `Pipeline.run`. `ArticleStore.load()` gained a `document_ids=` filter that accepts both canonical UUID and hex forms so the resume path can query by the hex ids the pipeline stores.
- [ ] **MEDIUM / Medium** — Entity-centric subgraph extraction. `find_co_mentioned`, `find_relationships_by_document`, and `get_provenance` exist as building blocks, but there's no single view "given entity X, show its k-hop neighbourhood in the news graph with supporting documents". Add a `cli/subgraph.py` that takes an entity id/name and `--hops N` and emits a JSON payload of the entity, its k-hop neighbours, the relationships linking them, and the provenance documents that justify each edge. Stays in index-into-news territory: the output describes *which news talked about these entities together*, not a fact dataset.
- [ ] **MEDIUM / Medium** — Content-hash deduplication in the article scraper path. Major newswires publish identical or near-identical copies of the same AP story across outlets; the current scrapers save all of them as distinct articles, inflating storage and making later provenance noisy. Add a `content_hash` column on `articles` (stable hash over normalised body text) and on-insert skip when the hash already exists, surfacing the collision in the scrape log. Optional `--no-dedup` escape hatch for archival runs.
- [ ] **LOW / Medium** — LLM provider fallback chain. `LLMProvider` is already an ABC with Ollama and Claude implementations; in practice users pick one binary switch. Add a `FallbackLLMProvider(primary, secondary, ambiguity_threshold)` that escalates to the secondary provider only when the primary's pass-1 response has low-confidence or many unresolved mentions. Keeps fast/cheap as the default path while rescuing the genuinely hard chunks without a full cross-provider run.


### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
