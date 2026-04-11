## Backlog

### 2026 April 11th (v0.28.0 refactor review)

- [x] **HIGH** — Deduplicate retry logic: `LLMEntityResolver.resolve()` and `LLMRelationshipExtractor.extract()` have identical retry-with-error-feedback loops — extract into a shared `_retry_llm_call()` helper
- [x] **HIGH** — Deduplicate `_FakeProvider`: identical class in `test_resolution.py`, `test_extraction.py`, and `test_llm_provider.py` — move to `conftest.py`
- [x] **MEDIUM** — Deduplicate `_append_error`: identical in `resolution.py` (static method) and `extraction.py` (standalone function) — extract into shared module
- [x] **MEDIUM** — Consolidate `_parse_json` / `_parse_json_pass2` in `llm_parsers.py`: identical logic differing only in exception type — unify with a parameterized exception class
- [x] **LOW** — Standardize `__all__` sort order in `pipeline/__init__.py`: mixed alphabetical/logical ordering — sort fully alphabetically

### 2026 March 30th

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
