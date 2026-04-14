## Backlog

### 2026.04.13 (KG population plan)

- [x] **MEDIUM / Medium** — Add `cli/populate.py` orchestrator that runs the whole seed + Wikidata sequence with a single command and writes a summary report. Alternative: keep manual per-type invocation so each stage can be inspected before proceeding. Decide before implementing.
- [x] **MEDIUM / Small** — After population, review the `entity_history` audit log for `reason="wikidata-seed"` conflicts (Wikidata rows skipped because a curated entry covered them) — those are the most interesting signals for improving the curated seed. Done: 24 distinct name overlaps across 91 curated entries. Coverage is solid for central banks/exchanges/crypto; thin on regulators (only FCA), currencies, and indices. Also surfaced two noise bugs tracked below.

### 2026.04.14 (Wikidata import follow-ups)

- [x] **MEDIUM / Small** — Tighten the `exchange` SPARQL query to exclude banks and broker-dealers. The v0.35.2 fix (`wdt:P31/wdt:P279*` → `wdt:P31`) wasn't enough — Wikidata directly tags Commerzbank, FXCM, Convergex, KCG Americas, OTP banka etc. as P31 stock exchange. Candidate fixes: add a `MINUS` clause for `Q22687` (bank) / `Q806735` (broker-dealer), or apply a curated blocklist in the mapper. Done in v0.37.1: `MINUS` clauses added; Commerzbank and OTP banka are now excluded. Residual noise (DB ATS, FXCM, Convergex, KCG Americas) tracked below — they're tagged with forex-broker / ATS / market-maker classes that the current MINUS doesn't cover.
- [ ] **LOW / Small** — Preserve Wikidata provenance on snapshot replay. `cli.seed` currently tags all replayed rows with `reason="seed"`, so rebuilding from `data/seed/wikidata/*.json` loses the `reason="wikidata-seed"` signal in `entity_history`. Options: teach `cli.seed` to read a `reason` hint from the snapshot header, or add a dedicated `cli/replay_snapshot.py` that preserves the origin reason.
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
