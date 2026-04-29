## Backlog

### 2026 April 29th (KG population)

- [ ] **HIGH** — Expose `cli/populate.py` via API: `POST /api/kg/populate` triggers curated seed (`data/seed/financial_entities.json`) + Wikidata snapshots load into KnowledgeStore — currently CLI-only, so the KG can never be seeded from the UI and no relationships can ever be extracted
- [ ] **HIGH** — Add "Seed entities" as Step 0 in the Feed page: show current entity count from `/api/health`, display a warning banner if count is 0, and provide a button that calls `POST /api/kg/populate` — prevents users from running ingest on an empty KG
- [ ] **MEDIUM** — Add LLM provider health check before ingest: before spawning the background thread, verify `ANTHROPIC_API_KEY` is set (for Claude) or the Ollama daemon is reachable (for Ollama); return HTTP 400 with a clear message instead of silently failing in a background thread
- [ ] **MEDIUM** — Surface cold-start toggle in Feed UI: add a checkbox to the ingest form for `cold_start` (skip relationship extraction on first pass) with a tooltip explaining it — currently hardcoded to `False` in the UI
- [ ] **MEDIUM** — Wikidata snapshot refresh endpoint: `POST /api/kg/wikidata-refresh` re-runs `cli/wikidata_seed.py` for all entity types (central_bank, company, crypto, currency, exchange, index, regulator) — current snapshots are from April 2024
- [ ] **LOW** — Alias deduplication via API: expose `audit_aliases` logic via `GET /api/kg/alias-audit` and surface results in UI or as a scheduled post-ingest step — prevents canonical name drift as the KG grows

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
