## Backlog

### 2026 April 29th (KG population)

- [x] **MEDIUM** — Wikidata snapshot refresh endpoint: `POST /api/kg/wikidata-refresh` re-runs `cli/wikidata_seed.py` for all entity types (central_bank, company, crypto, currency, exchange, index, regulator) — current snapshots are from April 2024
- [x] **LOW** — Alias deduplication via API: expose `audit_aliases` logic via `GET /api/kg/alias-audit` and surface results in UI or as a scheduled post-ingest step — prevents canonical name drift as the KG grows

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
