## Backlog

### 2026.04.13 (KG population plan)

- [ ] **MEDIUM / Medium** — Add `cli/populate.py` orchestrator that runs the whole seed + Wikidata sequence with a single command and writes a summary report. Alternative: keep manual per-type invocation so each stage can be inspected before proceeding. Decide before implementing.
- [ ] **MEDIUM / Small** — After population, review the `entity_history` audit log for `reason="wikidata-seed"` conflicts (Wikidata rows skipped because a curated entry covered them) — those are the most interesting signals for improving the curated seed.

### 2026.04.14 (Wikidata import follow-ups)

- [ ] **MEDIUM / Small** — Tighten the `exchange` SPARQL query to exclude banks and broker-dealers. The v0.35.2 fix (`wdt:P31/wdt:P279*` → `wdt:P31`) wasn't enough — Wikidata directly tags Commerzbank, FXCM, Convergex, KCG Americas, OTP banka etc. as P31 stock exchange. Candidate fixes: add a `MINUS` clause for `Q22687` (bank) / `Q806735` (broker-dealer), or apply a curated blocklist in the mapper.
- [ ] **LOW / Small** — Preserve Wikidata provenance on snapshot replay. `cli.seed` currently tags all replayed rows with `reason="seed"`, so rebuilding from `data/seed/wikidata/*.json` loses the `reason="wikidata-seed"` signal in `entity_history`. Options: teach `cli.seed` to read a `reason` hint from the snapshot header, or add a dedicated `cli/replay_snapshot.py` that preserves the origin reason.

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
