## Backlog

### 2026.04.23 (improvements review v0.49.20)

- [x] **MEDIUM / Medium** — Content-hash deduplication in the article scraper path. Shipped in v0.57.0: `content_hash` column on `articles` (SHA-256 over normalised body — lower-cased + whitespace-collapsed), index `idx_content_hash`, automatic migration + backfill on open, and `ArticleStore.save(skip_content_dupes=True)` that drops cross-DB and in-batch duplicates while logging each collision. `cli/scrape.py` exposes the escape hatch as `--no-dedup` for archival runs.
- [x] **LOW / Medium** — LLM provider fallback chain. Shipped as `pipeline/llm_fallback.py`: `FallbackLLMProvider(primary, secondary, ambiguity_threshold=0.5, ambiguity_fn=...)` escalates to the secondary on primary errors or when the default scorer flags the pass-1 output (malformed JSON, empty entities, or a high proposal-to-resolution ratio). Token usage sums both sides, `context_window` is the min, `supports_json_mode` is the AND, and escalation counts are exposed for monitoring.


### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
