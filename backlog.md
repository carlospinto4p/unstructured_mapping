## Backlog

### 2026.04.13 (KG population plan)

- [x] **HIGH / Small** — Run the curated seed first (`cli.seed` against `data/seed/financial_entities.json`) so hand-tuned LLM-facing descriptions define canonical names before any Wikidata import.
- [x] **HIGH / Small** — Dry-run each Wikidata type at `--limit 20` and eyeball the results before committing. The SPARQL class filters (especially `Q17278032` for regulators) are best guesses and may need tuning.
- [x] **HIGH / Medium** — Staged Wikidata imports, smallest/cleanest first, validating between stages (`db_health`, 10-row spot checks, conflict log review):
  1. `currency` (no limit — population is ~180)
  2. `central_bank` (no limit — ~200)
  3. `exchange` (no limit — ~100)
  4. `regulator` (no limit, expect noise from broad class)
  5. `index` (no limit, expect noise)
  6. `crypto --limit 100` (long tail is low-value)
  7. `company --limit 500` (ordered by market cap)
- [ ] **MEDIUM / Small** — Decide: commit the populated `data/knowledge.db`, or keep it local and rely on `--snapshot` JSONs for reproducibility?
- [ ] **MEDIUM / Medium** — Add `cli/populate.py` orchestrator that runs the whole seed + Wikidata sequence with a single command and writes a summary report. Alternative: keep manual per-type invocation so each stage can be inspected before proceeding. Decide before implementing.
- [ ] **MEDIUM / Small** — After population, review the `entity_history` audit log for `reason="wikidata-seed"` conflicts (Wikidata rows skipped because a curated entry covered them) — those are the most interesting signals for improving the curated seed.

### 2026 March 30th

#### KG population (bootstrap + growth)

- [x] **LOW** — Wikidata seed pipeline: query Wikidata SPARQL for financial entities, map to KG schema, bulk-import — heavy but provides broad coverage and external IDs when needed

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
