## Changelog

### v0.58.1 - 25th April 2026

- Refactored `KnowledgeStore` lookup naming to a single rule — `get_*` returns at most one record (or a dict keyed by exact id), `find_*` returns a filtered list/set. Added the convention to `KnowledgeStore`'s docstring.
  - Renamed methods (canonical names → old names kept as class-level aliases):
    - `find_relationships_for_entity` ← `get_relationships`.
    - `find_relationships_between` ← `get_relationships_between`.
    - `find_relationship_history` ← `get_relationship_history`.
    - `find_provenance_for_entity` ← `get_provenance`.
    - `find_entity_history` ← `get_entity_history`.
    - `find_entities_touched_by_run` ← `get_entities_touched_by_run`.
    - `find_failed_document_ids` ← `get_failed_document_ids`.
    - `find_relationship_keys_for_run` ← `get_relationship_keys_for_run`.
- Migrated internal callers to the canonical names:
  - `cli/export.py`, `cli/ingest.py`, `cli/run_diff.py`, `cli/run_report.py`, `cli/subgraph.py`, `pipeline/orchestrator.py`, plus `:meth:` references in `_provenance_mixin`, `_relationship_mixin`, and `_run_mixin` docstrings.
- Added `tests/unit/test_kg_runs_and_history.py::test_back_compat_aliases_resolve_to_find_methods`: pins each legacy `get_*` to its canonical `find_*` so future refactors can't accidentally diverge their behaviour.


### v0.58.0 - 25th April 2026

- Added `pipeline/llm_fallback.py`: two-provider fallback chain.
  - `FallbackLLMProvider(primary, secondary, ambiguity_threshold, ambiguity_fn)`: conforms to `LLMProvider`, escalates to the secondary on any `LLMProviderError` or when the scorer exceeds the threshold. Exposes `last_served_by` and `escalations` for per-run monitoring.
  - `default_ambiguity_score()`: scores a raw response on `[0, 1]` — malformed JSON / missing or empty `entities` → 1.0, otherwise the proposal-to-resolution ratio for pass-1 shapes; pass-2 responses score 0.0.
  - Metadata composition: `provider_name` and `model_name` are composite strings (so run scorecards distinguish fallback chains from bare providers), `context_window` is the min of the two sides, and `supports_json_mode` is the AND (safe because the secondary is called on escalation).
  - `last_token_usage` sums primary + secondary usage when escalation fires, so pipeline run totals capture the true cost.
- Exported `FallbackLLMProvider`, `default_ambiguity_score`, and `DEFAULT_AMBIGUITY_THRESHOLD` from `pipeline/__init__.py`.
- Added `tests/unit/test_llm_fallback.py`: 20 tests covering the scorer across every response shape, routing matrix (primary-succeeds / ambiguous / hard-failure), token summing, threshold-validation, composite metadata derivation, and the custom-scorer escape hatch.


### v0.57.0 - 24th April 2026

- Added content-hash deduplication in `web_scraping/storage.py`:
  - `compute_content_hash()`: SHA-256 over a normalised body (lower-cased, whitespace-collapsed) so minor formatting drift across newswire copies still collides.
  - `content_hash` column on `articles` plus `idx_content_hash` for O(log n) collision lookups.
  - Migration step `_migrate_add_content_hash()` adds the column and backfills hashes for every pre-existing row so the collision check has a populated baseline on legacy DBs.
  - `ArticleStore.save(skip_content_dupes=True)`: batched collision check that drops duplicates already in the DB and duplicates within the same batch, logging each at INFO. `skip_content_dupes=False` preserves every non-URL duplicate for archival runs.
- Updated `cli/scrape.py`: added `--no-dedup` flag that forwards `skip_content_dupes=False` to the store.
- Added tests in `tests/unit/test_web_scraping.py`:
  - `compute_content_hash` case/whitespace invariance and collision behaviour.
  - Cross-URL dedup, in-batch dedup, and the `--no-dedup` opt-out.
  - `content_hash` column persistence and migration backfill.


### v0.56.0 - 24th April 2026

- Added `cli/subgraph.py`: entity-centric k-hop subgraph extraction.
  - `build_subgraph()`: BFS from a root entity through `find_relationships` in both directions; emits root, entities, relationships, and the distinct document ids that justify each edge.
  - Root resolution via `--entity-id` or `--name` (ambiguous names fail fast with a candidate list).
  - `--min-confidence` threshold drops weak edges before the BFS expands through them, so unreliable relationships don't pull in distant neighbours.
  - `--hops 0` returns just the root; stable ordering (root first, entities by canonical name, edges by source/target/type/valid_from) so the payload diffs cleanly between runs.
- Added `tests/unit/test_cli_subgraph.py`: 13 tests covering hop depths (0/1/2), the min-confidence filter, name/id resolution, ambiguity + not-found errors, `main` stdout / file-output contracts, negative-hops guard, and payload determinism.


### v0.55.0 - 24th April 2026

- Added `cli/ingest.py`: user-facing batch-ingest CLI that runs the orchestrator over scraped articles. Supports `--source` / `--limit` filters, cold-start / no-LLM / full-pipeline modes, and both Ollama and Claude providers.
- Added `--resume-run <run_id>` to `cli/ingest.py`: loads the failed document ids from `article_failures`, fetches just those articles from the articles DB, and forwards the run id to `Pipeline.run` so the retry is filtered on both sides. Bridges the v0.54.0 plumbing to a real user entry point.
- Updated `ArticleStore.load()` in `web_scraping/storage.py`: added a `document_ids=` keyword filter that accepts both canonical UUID and 32-char hex forms. Needed because `Pipeline` stores failure ids as `UUID.hex` but the articles table uses `str(UUID)`.
- Added `tests/unit/test_cli_ingest.py`: 13 tests covering article loading (filter + resume), pipeline-assembly modes, alias-only ingestion, the resume workflow end-to-end, stdout contract, cold-start guardrails, and the new `document_ids=` filter on `ArticleStore.load`.


### v0.54.0 - 24th April 2026

- Added per-article failure tracking + `Pipeline.run()` resume support:
  - `article_failures` table in `knowledge_graph/storage.py`: `(run_id, document_id, error_message, failed_at)` with composite PK on `(run_id, document_id)` and FK to `ingestion_runs`.
  - Index `idx_article_failures_run` for fast per-run lookup.
  - `KnowledgeStore.save_article_failure()`: `INSERT OR REPLACE` upsert so a resumed article that fails again refreshes the prior row.
  - `KnowledgeStore.get_failed_document_ids()`: returns the failed set, sorted, for a given run_id.
- Updated `pipeline/orchestrator.py`:
  - `Pipeline._process_article()`: the per-article `except` now calls `save_article_failure` so a crashed batch leaves behind the exact re-queue list.
  - `Pipeline.run(articles, *, resume_run_id=None)`: when set, filters `articles` down to the failed ids from the prior run before allocating the new run_id.
- Added tests:
  - `tests/unit/test_kg_runs_and_history.py`: `save_article_failure` / `get_failed_document_ids` roundtrip, upsert semantics, per-run scoping, empty-run behaviour.
  - `tests/unit/test_pipeline.py`: orchestrator records a failure row, `resume_run_id` filters to failed docs, resuming a clean run is a no-op.
- Deferred: a user-facing `--resume-run` CLI flag. The backlog item specified it live on `cli/populate.py`, which is currently a seed loader (curated JSON + Wikidata snapshots) and does not drive the LLM pipeline; wiring the flag there would be inert. Left as a follow-up to land alongside a canonical batch-ingest CLI.


### v0.53.0 - 24th April 2026

- Added `cli/validate_snapshot.py`: golden-snapshot KG quality gate.
  - `--record PATH`: capture a structured KG summary (counts by type / subtype, top-K alias collisions, provenance density, totals) and persist as JSON.
  - `--check BASELINE`: capture the current KG, compare against a baseline, print the diff, and exit non-zero when thresholds are breached.
  - Thresholds: `--max-entity-drop-pct` (default 10) and `--max-collision-increase` (default 0).
  - Exports `Snapshot`, `CollisionSummary`, `CheckResult`, `capture_snapshot`, `compare_snapshots`, `load_snapshot`, `write_snapshot` for programmatic use.
- Added `tests/unit/test_cli_validate_snapshot.py`: 17 tests covering snapshot totals, per-type/subtype counts, collision capture, JSON roundtrip, schema-version guard, threshold gates (drop + collisions), and `main` record/check paths.


### v0.52.0 - 24th April 2026

- Added Parquet export to `cli/export.py`:
  - `SUPPORTED_FORMATS` now includes `parquet` alongside `jsonl` and `json-ld`.
  - `_write_parquet()`: uses `pyarrow.Table.from_pylist` + `pyarrow.parquet.write_table` so list columns (e.g. `aliases`) land as native Parquet `LIST` types.
  - Raises a clear `ImportError` pointing at `pip install 'unstructured-mapping[export]'` when `pyarrow` is missing.
- Added `export` optional extra in `pyproject.toml` (`pyarrow>=15`); mirrored into `dev` so developer envs keep full test coverage.
- Added tests in `tests/unit/test_cli_export.py`: parquet roundtrip, type filter, `main` parquet path, and missing-pyarrow error surface.


### v0.51.1 - 23rd April 2026

- Added `cli/run_report.py`: per-run ingestion scorecard. Renders lifecycle (status, timestamps, wall time, error), aggregate counts (documents / provenance rows / relationships / distinct entities / distinct relationships), and the `RunMetrics` LLM scorecard (provider / model / calls / tokens). Distinct counts reuse `get_entities_touched_by_run` / `get_relationship_keys_for_run` added in v0.50.0. Flags failed runs with a top-of-report banner; falls back gracefully when no `RunMetrics` row exists.
- Added unit test `tests/unit/test_cli_run_report.py`: 5 tests covering the populated-run happy path, the no-metrics fallback, the failed-run banner, the missing-run error, and the `main` stdout contract.


### v0.51.0 - 23rd April 2026

- Added `cli/export.py`: portable KG export with `--format {jsonl,json-ld}`, optional `--type` / `--subtype` / `--since` filters, and `--with-relationships` / `--with-provenance` opt-ins. Emits one file per stream into `--output-dir`. JSON-LD wraps each stream in a minimal `@context` so downstream tools treat it as a well-formed JSON-LD document. Parquet was deliberately deferred so the default install stays free of `pyarrow`; tracked on the backlog.
- Added unit test `tests/unit/test_cli_export.py`: 11 tests covering both formats, all three filter branches, the opt-in streams, the `--subtype` requires `--type` guard, and the `main` stdout contract.


### v0.50.0 - 23rd April 2026

- Added `cli/run_diff.py`: diff two ingestion runs. Produces per-run headline blocks (status, tokens, LLM calls, wall time) plus entity / relationship set deltas — which entity IDs and which `(source, target, relation_type)` keys appear only in the base run, only in the head run, or in both. Supports `--deltas-only` to skip the headline blocks. Read-only; never mutates the KG.
- Added `knowledge_graph/_run_mixin.py`:
  - `KnowledgeStore.get_entities_touched_by_run()`: distinct entity IDs with provenance for a run.
  - `KnowledgeStore.get_relationship_keys_for_run()`: `(source_id, target_id, relation_type)` identity set for a run; drops `valid_from` so "same edge, new temporal bound" still matches across runs.
- Added unit tests:
  - `tests/unit/test_kg_runs_and_history.py`: 2 tests for the new store helpers.
  - `tests/unit/test_cli_run_diff.py`: 4 tests covering the delta report, `--deltas-only`, missing-run error, and the `main` stdout contract.


### v0.49.20 - 23rd April 2026

- Updated `wikidata/mapper.py::dedupe_mapped_by_qid()`: carries the per-QID dedup set in a parallel `dict[qid, set[str]]` so the set is seeded once on first-seen and amended on subsequent duplicates, instead of being rebuilt from the alias list every time a QID is re-encountered. Matters for QIDs that appear in hundreds of SPARQL bindings (STOXX Europe 600 × 289).


### v0.49.19 - 23rd April 2026

- Updated `knowledge_graph/_entity_helpers.py::_load_aliases_batch()`: chunks the `WHERE entity_id IN (...)` clause into 500-id slices so bulk reads on large KGs stay under SQLite's default `SQLITE_MAX_VARIABLE_NUMBER = 999`. Fixes the latent `OperationalError: too many SQL variables` that would surface on `find_entities_by_status(limit=100_000)` or similar after the Wikidata import.
- Added unit test `tests/unit/test_kg_entities.py::test_store_get_entities_chunks_large_id_list`: inserts 1200 entities with aliases, pulls them all in a single `get_entities()` call, and verifies aliases from every chunk boundary round-trip correctly.


### v0.49.18 - 23rd April 2026

- Added `pipeline/_batch_lookup.py::resolve_batch()`: centralises the "batch lookup when wired, per-id fallback otherwise" pattern. Logs a debug line on every fallback so a missing `entity_batch_lookup` is visible instead of silent.
- Updated `pipeline/`:
  - `resolution.py::LLMEntityResolver._collect_candidates()`: swapped the inline conditional for `resolve_batch`.
  - `extraction.py::LLMRelationshipExtractor._build_lookup_maps()`: same swap, so the two LLM stages now share one source of truth for the fallback shape.


### v0.49.17 - 23rd April 2026

- Updated `pipeline/orchestrator.py::_persist_proposals()`: accumulates provenance rows in a list and calls `save_provenances()` once after the proposal loop instead of once per proposal, trading N single-row executemany calls for one bulk insert.


### v0.49.16 - 23rd April 2026

- Updated `pipeline/orchestrator.py`:
  - `_persist_aggregated()`: wrapped the provenance + proposal + relationship writes in `store.transaction()` so one article commits once. Previously fired up to 2N+2 COMMITs (save_entity + save_provenances per proposal, plus the relationship batch).
  - `_process_cold_start()`: wrapped the per-proposal persistence loop in `store.transaction()` for the same reason.


### v0.49.15 - 23rd April 2026

- Updated `pipeline/extraction.py::LLMRelationshipExtractor`:
  - Added optional `entity_batch_lookup` parameter. When provided, `_build_lookup_maps` runs one batch query instead of one SQL round-trip per resolved mention. 20-entity chunks now fire one query before the LLM call instead of 20.
  - Falls back to the per-id `entity_lookup` when `entity_batch_lookup` is omitted so existing tests/callers keep working.
- Updated call sites:
  - `pipeline/orchestrator.py`: wires `entity_batch_lookup=store.get_entities` alongside the resolver's existing batch lookup.
  - `cli/preview.py`: same wiring for the dry-run preview CLI.


### v0.49.14 - 23rd April 2026

- Updated `data/seed/financial_entities.json`: expanded curated coverage for thin categories flagged by the Wikidata overlap review (91 → 110 entries):
  - Regulators (+4): Single Supervisory Mechanism, China Securities Regulatory Commission, Federal Financial Supervisory Authority (BaFin), Monetary Authority of Singapore.
  - Currencies (+9): AUD, CAD, HKD, SGD, SEK, KRW, NOK, NZD, INR (brings total to the top 15 by FX turnover).
  - Indices (+6): Nifty 50, KOSPI, S&P/TSX Composite, S&P/ASX 200, FTSE MIB, Ibovespa.


### v0.49.13 - 23rd April 2026

- Updated `wikidata/queries.py::EXCHANGES_QUERY`:
  - Added three class-based `MINUS` clauses: alternative trading system (`Q438711`), market maker (`Q1137319`), and foreign exchange company (`Q5468383`). Catches KCG Americas and similar ATSs that inherit from a class the bank/brokerage `MINUS` did not cover.
  - Added `_EXCHANGE_BLOCKLIST_QIDS` constant and a `FILTER(?item NOT IN ...)` clause for firms that are mis-tagged on Wikidata with only `Q11691` and no class hierarchy the subclass walk can catch. Bootstrap set covers FXCM (`Q5973741`) and Convergex (`Q93355333`).
- Added unit tests in `tests/unit/test_wikidata_seed.py`:
  - `test_exchange_query_excludes_ats_and_market_makers`: pins the three new class-based `MINUS` QIDs.
  - `test_exchange_query_applies_curated_blocklist`: pins the `FILTER` blocklist and its bootstrap QIDs.


### v0.49.12 - 23rd April 2026

- Updated `knowledge_graph/`:
  - Split `_entity_mixin.py` (639 lines) along its four internal mixin classes:
    - `_entity_crud_mixin.py`: `EntityCRUDMixin` (save / get / name + alias lookup).
    - `_entity_search_mixin.py`: `EntitySearchMixin` (type/subtype/status/prefix filters, counts, recency).
    - `_entity_merge_mixin.py`: `EntityMergeMixin` (FK redirection + audit trail).
    - `_entity_history_mixin.py`: `EntityHistoryMixin` (revisions, point-in-time, revert).
  - `_entity_mixin.py`: now a thin composite that re-exports the four sub-mixins and defines `EntityMixin`; `storage.py`'s import site is unchanged.


### v0.49.11 - 23rd April 2026

- Updated `tests/unit/`:
  - `test_kg_provenance.py`: trimmed to provenance CRUD, `find_recent_mentions`, and the co-mention query (14 tests).
  - `test_kg_runs_and_history.py`: new file covering ingestion run CRUD, `run_id` provenance/relationship linkage, the legacy-DB `run_id` migration, and the `count_mentions_*` / `find_mentions_with_entities` helpers (13 tests).


### v0.49.10 - 23rd April 2026

- Added `cli/_argparse_helpers.py::require_db_unless()`: shared post-`parse_args` validator for "DB flag required unless bypass flag is set". Argparse cannot express the conditional natively, so the helper standardises the error message and call pattern.
- Updated `cli/`:
  - `preview.py::main()`: replaced the inline `--kg-db` / `--cold-start` check with a call to `require_db_unless(args)`; the last CLI-specific validation noted in the `_argparse_helpers` docstring is now gone.
  - `_argparse_helpers.py`: module docstring updated to point at the new helper instead of flagging `preview` as the lone exception.


### v0.49.9 - 23rd April 2026

- Updated `web_scraping/`:
  - `base.py::Scraper._fetch_page()`: new base-class method that fetches raw HTML bytes via the shared `httpx.Client`, returning `b""` on failure instead of raising. Gives future scrapers a predictable fetch contract.
  - `bbc.py::BBCScraper`: dropped the subclass `_fetch_page()` override (moved to base) and switched its `_extract_body()` check from `is None` to `if not html` to match the new empty-bytes sentinel.


### v0.49.8 - 23rd April 2026

- Added `tokens.py`: centralises the `_CHARS_PER_TOKEN = 4` constant shared by the budget estimator and the KG audit mixin.
- Updated `src/`:
  - `pipeline/budget.py`: imports `_CHARS_PER_TOKEN` from `tokens.py` instead of defining its own copy.
  - `knowledge_graph/_audit_mixin.py`: imports `_CHARS_PER_TOKEN` from `tokens.py`; module docstring updated to reference the shared module.


### v0.49.7 - 23rd April 2026

- Added `web_scraping/_gnews.py`:
  - `_has_scraping_deps()`: dep check for googlenewsdecoder + trafilatura.
  - `_resolve_gnews_url()`: decode a Google News redirect URL.
  - `_extract_text()`: fetch and extract article text with trafilatura.
  - `_DECODE_ERRORS` / `_EXTRACT_ERRORS`: shared exception tuples.
- Updated `web_scraping/`:
  - `ap.py`: dropped the duplicated `_has_scraping_deps()` and the `APScraper._resolve_url` / `_fetch_page` static methods; `_extract_body` now calls the shared `_gnews` helpers.
  - `backfill.py`: dropped the duplicated `_has_scraping_deps()`, `_resolve_gnews_url()`, `_extract_text()`, and error-tuple constants; imports them from `_gnews`. Module docstring updated to describe the new split instead of the old duplication trade-off.


### v0.49.6 - 22nd April 2026

- Deduplicated within-snapshot Wikidata rows:
  - Added `wikidata/mapper.py::dedupe_mapped_by_qid()`: collapses multiple `MappedEntity` records sharing a QID. First-seen row wins on description/subtype; aliases from every later duplicate are unioned so all ticker/ISIN/MIC values survive on a single entity.
  - Exported `dedupe_mapped_by_qid` from `wikidata/__init__.py`.
  - Updated `cli/wikidata_seed.py::_fetch_mapped()`: calls the dedup step before returning — both snapshot writes and KG imports now see one entity per QID. The v0.35.2 subquery-LIMIT idiom only deduped QIDs inside the inner subquery; OPTIONAL joins (ticker, exchange, country, ISIN, MIC) still fanned items out. Expected to roughly halve snapshot file size for list-heavy types (index, currency, company).
- Added unit tests:
  - `tests/unit/test_wikidata_seed.py`: dedup merges aliases across duplicates, preserves single rows untouched, and handles empty input.


### v0.49.5 - 22nd April 2026

- Updated `wikidata/queries.py::_LISTED_COMPANIES_TEMPLATE`: added `MINUS { ?item wdt:P31/wdt:P279* wd:Q66344 . }` (central bank) inside the inner subquery. Without this, Bank of Japan and Swiss National Bank leaked into `company.json` because they hold P414 listing entries for currency/reserve-asset assertions.
- Added unit test:
  - `tests/unit/test_wikidata_seed.py::test_company_query_excludes_central_banks`: asserts the company query references `Q66344` inside a `MINUS` clause.


### v0.49.4 - 22nd April 2026

- Added `idx_rel_document` in `knowledge_graph/storage.py::_CREATE_INDEXES`: `find_relationships_by_document` previously fell back to a full table scan on every call from the preview CLI. `CREATE INDEX IF NOT EXISTS` makes the migration a no-op; existing DBs pick up the new index on next open.
- Added unit test:
  - `tests/unit/test_kg_relationships.py::test_relationships_document_index_is_installed`: guards against the index being accidentally dropped from `_CREATE_INDEXES`.


### v0.49.3 - 22nd April 2026

- Pushed the token-length filter into SQL for the short-snippet audit:
  - Updated `knowledge_graph/_audit_mixin.py::find_short_snippets()`: adds `WHERE LENGTH(context_snippet) < min_tokens * _CHARS_PER_TOKEN` so SQLite prunes long rows before the join hydrates them. Python still applies the exact `ceil(len/4)` estimate as a post-filter — the SQL bound is a conservative superset so the Python check stays the source of truth.
- Added unit test:
  - `tests/unit/test_cli_audit_provenance.py::test_find_short_snippets_sql_boundary_agrees_with_python`: boundary case at `len ∈ {16, 19, 20}` for `min_tokens=5`, guarding that the SQL pre-filter never drops a row the Python check would have flagged.


### v0.49.2 - 22nd April 2026

- Batched duplicate checks in the Wikidata seed loader:
  - Added `KnowledgeStore.wikidata_qids()` on `EntityCRUDMixin`: returns the set of bare QIDs carried as `wikidata:Q…` aliases.
  - Added `KnowledgeStore.name_type_pairs()` on `EntityCRUDMixin`: returns `{(name.lower(), entity_type_value), …}` for every entity.
  - Updated `cli/wikidata_seed.py`: replaced per-candidate `_already_imported()` (2 queries × N candidates) with `_build_dedup_check()` — one prefetch each, then O(1) Python `in` checks inside the loop.
- Added unit tests:
  - `tests/unit/test_kg_entities.py`: `wikidata_qids()` strips the prefix and returns an empty set when no Wikidata aliases exist; `name_type_pairs()` lowercases names and uses `entity_type.value`.


### v0.49.1 - 22nd April 2026

- Batched mention-count lookups in the alias-collision audit:
  - Added `KnowledgeStore.count_mentions_for_entities(ids)` on `ProvenanceMixin`: single grouped `GROUP BY entity_id` query, zero-fills ids with no provenance.
  - Updated `cli/audit_aliases.py::score_collisions()`: prefetches all sides in one call instead of one query per collision side (was O(collisions × sides)).
- Added unit tests:
  - `tests/unit/test_kg_provenance.py`: batch counter returns correct counts, zero-fills unseen ids, and short-circuits on empty input.


### v0.49.0 - 22nd April 2026

- Added `src/unstructured_mapping/web_scraping/backfill.py`:
  - `ARCHIVE_SOURCES`: mapping of source label to site domain for Google News `site:` filter.
  - `build_archive_query_url()`: single-day Google News RSS URL builder using `after:`/`before:` operators.
  - `ArchiveScraper`: one-day, one-source backfill scraper; decodes Google News redirects with `googlenewsdecoder`, extracts body text with `trafilatura`, and post-filters by `pubDate` to drop day-after leakage from the approximate `before:` bound.
  - `fetch_range()`: iterates day-by-day across a closed range, stays within Google News' ~100-results-per-query cap, and deduplicates across days by URL.
- Added `src/unstructured_mapping/cli/backfill.py`: `uv run python -m unstructured_mapping.cli.backfill --from YYYY-MM-DD --until YYYY-MM-DD [--source ap|bbc|reuters|all]` for backfilling missed days into the live articles database.
- Updated `src/unstructured_mapping/cli/db_health.py`:
  - `_section_daily_coverage()`: groups by `published` instead of `scraped_at` so the metric reflects content coverage rather than ingestion activity. Without this, backfilled articles bunched into the day they were scraped, hiding the very gaps the backfill was meant to fill.
- Added unit tests:
  - `tests/unit/test_backfill.py`: 7 tests covering query URL, post-filter, per-day iteration, URL dedup across days, and source validation.
  - `tests/unit/test_cli_backfill.py`: 5 tests covering source fan-out, single-source mode, reversed/invalid date rejection, and date pass-through.


### v0.48.13 - 22nd April 2026

- Updated `src/unstructured_mapping/cli/db_health.py`:
  - `_section_daily_coverage()`: fills in zero-count days in the 7-day window and flags past days with no articles as `<- GAP`, followed by an `ALERT:` summary line. Today is never flagged since the scraper may not have run yet.
- Added `tests/unit/test_cli_db_health.py`: coverage for gap detection, all-filled window, and today-not-flagged behaviour.


### v0.48.12 - 20th April 2026

- Synced canonical `.gitignore` from programme (direnv block).


### v0.48.11 - 20th April 2026

- Synced canonical `.claude/rules/*.md` from programme.


### v0.48.10 - 17th April 2026

- `.gitattributes`: Added LF line ending normalization.

### v0.48.9 - 16th April 2026

- Consolidated import summary logging:
  - `cli/_seed_helpers.py`: new `log_import_summary(logger, created, skipped, counts, *, header, suffix)` emits the "N created, M skipped" line plus a sorted counter breakdown.
  - Migrated callers: `cli/seed.py`, `cli/wikidata_seed.py`, and the multi-stage summary in `cli/populate.py`. The populate total line now reads "Total across N stages: X created, Y skipped" (wording adjusted to reuse the shared helper).
- Extracted throwaway-KG setup:
  - `cli/_db_helpers.py`: new `prepare_throwaway_kg(workdir, name, *, source=None)` centralises the "unlink stale copy, optionally copyfile from source" shape. Missing-source paths now raise `FileNotFoundError` uniformly.
  - Migrated `cli/preview.py` and `cli/benchmark_cold_start.py` onto the helper; dropped local `shutil.copyfile` / `unlink` sites.
- Added unit tests:
  - `tests/unit/test_cli_db_helpers.py`: 4 new tests covering empty-scratch setup, seed copy, stale-target overwrite, and missing-source error path.
- Hoisted shared LLM provider defaults:
  - `pipeline/llm_provider.py`: exports `DEFAULT_TIMEOUT = 120.0`; concrete providers now import it rather than redeclaring.
  - `pipeline/llm_ollama.py` and `pipeline/llm_claude.py`: dropped the local `DEFAULT_TIMEOUT` constants. Provider-specific defaults (context window, max tokens) stay in their respective modules.
- Dropped the backwards-compat `_TYPE_HANDLERS` alias:
  - `cli/wikidata_seed.py`: references `TYPE_REGISTRY` directly; the alias and its rationale comment are gone.
  - `tests/unit/test_wikidata_seed.py`: tests import `TYPE_REGISTRY` from `unstructured_mapping.wikidata`.
  - `docs/seed/wikidata.md`: updated the "new types" instructions to point at `wikidata/registry.py::TYPE_REGISTRY`.


### v0.48.8 - 16th April 2026

- Removed unused `ConstraintWarning` re-export from `knowledge_graph/__init__.py`. No production module imports it; the dataclass lives on as an internal detail of `validation.py` and can be referenced as `validation.ConstraintWarning` when needed.


### v0.48.7 - 16th April 2026

- Added `cli/_db_helpers.py::open_kg_store(path, *, create_if_missing=False)`: opens `KnowledgeStore` with explicit control over the "missing file" failure mode.
- Migrated read-only audit CLIs onto the helper so typo'd database paths fail loudly rather than silently creating an empty DB:
  - `cli/audit_aliases.py`.
  - `cli/audit_provenance.py`.
- Added unit tests:
  - `tests/unit/test_cli_db_helpers.py`: 3 tests covering missing-path exit, create-if-missing, and opening an existing file.


### v0.48.6 - 16th April 2026

- Promoted shared provenance fixtures into `tests/unit/conftest.py`:
  - `make_provenance()`: builds a single `Provenance` row with sensible test defaults.
  - `add_mentions_to_store()`: saves N synthetic mentions for an entity.
- Migrated `test_cli_audit_provenance.py` and `test_cli_audit_aliases.py` off their local `_mention` / `_add_mentions` helpers.


### v0.48.5 - 16th April 2026

- Added `KnowledgeStore.find_relationships_by_document()` on `RelationshipMixin`: returns every relationship row persisted under the given `document_id`.
- Refactored `cli/preview.py`: `_collect_preview` projects the new store method instead of running its own relationships join, removing the last `# noqa: SLF001` from the file.
- Added unit test:
  - `tests/unit/test_kg_relationships.py::test_find_relationships_by_document`: filters by document, empty lookups return `[]`.


### v0.48.4 - 16th April 2026

- Added `cli/_argparse_helpers.py`:
  - `add_db_argument()`: standardizes `--db` flag name, type, and help wording; `required=True` or default-path idiom.
  - `add_dry_run_argument()`: standardizes `--dry-run`.
  - `add_csv_output_argument()`: standardizes `--csv`.
  - `KG_DEFAULT_DB` / `ARTICLES_DEFAULT_DB` constants.
- Migrated CLIs onto the helpers:
  - `cli/audit_aliases.py`: `--db` via helper (required).
  - `cli/audit_provenance.py`: `--db` and `--csv` via helpers.
  - `cli/populate.py`, `cli/seed.py`, `cli/wikidata_seed.py`: `--db` and `--dry-run` via helpers.
  - `cli/db_health.py`, `cli/scrape.py`: `--db` via helper with articles default.


### v0.48.3 - 16th April 2026

- Refactored audit queries into a new `AuditMixin`:
  - `knowledge_graph/_audit_mixin.py`: `find_short_snippets`, `find_thin_mentions`, `find_narrow_spread` plus their finding dataclasses (`ShortSnippetFinding`, `ThinMentionFinding`, `NarrowSpreadFinding`). Token estimate inlined as `ceil(chars / 4)` so the KG layer does not import `pipeline`.
  - `knowledge_graph/storage.py`: `KnowledgeStore` composes `AuditMixin`.
  - `cli/audit_provenance.py`: three `# noqa: SLF001` SQL helpers dropped in favour of store methods; the module now keeps thin free-function wrappers for backward-compatible test imports.


### v0.48.2 - 16th April 2026

- Refactored provenance reads out of CLIs:
  - `knowledge_graph/_provenance_mixin.py`: new `count_mentions_for_entity(entity_id)` and `find_mentions_with_entities(document_id)` methods. The latter returns `(Entity, Provenance)` pairs hydrated via the existing alias batch loader.
  - `cli/audit_aliases.py`: dropped the local `_score_entity` SQL helper in favour of `store.count_mentions_for_entity`.
  - `cli/benchmark_cold_start.py`: `_discovered_for_document` now projects `(Entity, Provenance)` pairs from the store instead of executing its own join.
  - `cli/preview.py`: `_collect_preview` uses `store.find_mentions_with_entities` for the mentions side of the payload.
  - Removed three `# noqa: SLF001` annotations; the only remaining `store._conn` access in the CLIs is the relationships query in `preview.py` (tracked separately in the backlog).
- Added unit tests:
  - `tests/unit/test_kg_provenance.py`: `count_mentions_for_entity` roundtrip, `find_mentions_with_entities` ordering + document scoping, empty-document short-circuit.


### v0.48.1 - 16th April 2026

- Added `docs/examples/queries.sql`: a ten-query cookbook for analysts — top mentions this week, top mentions by type, entity merge history, relationship types with average confidence, currently-active high-confidence edges, provenance timeline, co-mentioned entities, per-run scorecard summary, alias-collision report, and entities proposed by a specific run.
- Added `tests/unit/test_docs_queries.py`: parses the cookbook, enforces the ten-query count, and smoke-tests each statement against a fresh `KnowledgeStore` so schema drift breaks the docs fast.


### v0.48.0 - 16th April 2026

- Added provenance quality audit CLI:
  - `cli/audit_provenance.py`: three-way audit over the KG's provenance table. Flags short context snippets (`--min-tokens`, via the existing token-estimate heuristic), thin mention coverage (`--min-mentions`, counting distinct `(document_id, mention_text)` pairs and including zero-mention orphans), and narrow temporal spread (`--min-days`, skipping single-mention rows so the signal is not dominated by zero-second spans). Emits a text report or a combined CSV via `--csv`.
- Added unit tests:
  - `tests/unit/test_cli_audit_provenance.py`: 6 tests covering each heuristic, zero-mention inclusion via LEFT JOIN, single-mention exclusion from the spread report, and end-to-end CSV export with all three finding types.


### v0.47.0 - 15th April 2026

- Added alias-collision audit CLI:
  - `cli/audit_aliases.py`: wraps `validation.find_alias_collisions`, enriches each collision with per-entity mention counts, and ranks collisions by total prevalence. `--apply` merges same-type collisions into the most-mentioned entity with a per-collision `[y/N]` confirm prompt; `--auto-confirm` skips the prompt (requires `--apply`). Cross-type collisions are reported but never auto-proposed. `--min-mentions` filters out low-signal cases.
- Added unit tests:
  - `tests/unit/test_cli_audit_aliases.py`: 6 tests covering prevalence ranking, same-type vs cross-type merge-target selection, auto-confirm merges, interactive skip when the operator declines, and the `--auto-confirm requires --apply` guard.


### v0.46.0 - 15th April 2026

- Added pipeline dry-run preview CLI:
  - `cli/preview.py`: runs detection + (optional) LLM resolution + relationship extraction on a single article against a throwaway copy of the target KG. Emits mentions / proposals / relationships / token usage as JSON (stdout or `--output`). Supports `--article-file` (JSON) or `--text` (inline body), `--cold-start` mode, and `--no-llm` for alias-only debugging. Never mutates the source KG.
- Added unit tests:
  - `tests/unit/test_cli_preview.py`: 7 tests covering article loading (file / text / guards), KG-driven preview without an LLM, cold-start provider guard, and isolation of the source KG.


### v0.45.0 - 15th April 2026

- Added `confidence` qualifier on relationships:
  - `knowledge_graph/models.py`: `Relationship.confidence: float | None`.
  - `knowledge_graph/storage.py`: `relationships` table gained a nullable `confidence REAL` column; `_migrate_relationships` backfills older DBs.
  - `knowledge_graph/_helpers.py`: `REL_SELECT` and `row_to_relationship` propagate the new column.
  - `knowledge_graph/_relationship_mixin.py`: `save_relationship` / `save_relationships` persist `confidence`.
  - `pipeline/models.py`: `ExtractedRelationship.confidence` surfaces the LLM-reported score.
  - `pipeline/prompts.py`: `PASS2_SYSTEM_PROMPT` asks for optional `confidence` (0–1) per relationship.
  - `pipeline/llm_parsers.py`: new `_parse_confidence` helper clamps to `[0, 1]`; non-numeric or missing values become `None`.
  - `pipeline/orchestrator.py`: `_persist_relationships` threads `confidence` into persisted `Relationship` rows.
- Added temporal + confidence query API:
  - `knowledge_graph/_relationship_mixin.py`: new `find_relationships(entity_id, *, as_source, as_target, at=None, min_confidence=None)` combines a point-in-time filter with a confidence floor. `min_confidence` drops rows whose score is `NULL`.
- Added unit tests:
  - `tests/unit/test_kg_relationships.py`: `find_relationships` at-date filter, `min_confidence` drops unscored / low rows, `confidence` round-trips through save / get.
  - `tests/unit/test_llm_parsers.py`: confidence in range, missing, out-of-range clamp, non-numeric → None.
  - `tests/unit/test_prompts.py`: Pass 2 prompt mentions `confidence`.
  - `tests/unit/test_extraction.py`: confidence passthrough from LLM response to `ExtractedRelationship`.


### v0.44.0 - 15th April 2026

- Added cold-start benchmarking CLI:
  - `cli/benchmark_cold_start.py`: runs a labelled article set through cold-start and/or KG-driven pipelines and reports per-mode precision / recall / F1 plus token spend. Labelled file format is JSON with `document_id`, `body`, and an `entities` list of `{canonical_name, entity_type}`. Matching is strict — case-insensitive `(canonical_name, entity_type)` joins on provenance. `--mode` accepts `cold-start`, `kg-driven`, or `both`; `kg-driven` copies `--seed-db` to a throwaway file to keep the live KG untouched.
- Added unit tests:
  - `tests/unit/test_cli_benchmark_cold_start.py`: 9 tests covering label parsing, enum validation, per-article TP/FP/FN, aggregate precision/recall/F1, end-to-end cold-start scoring via a fake discoverer, and argument guards.


### v0.43.0 - 15th April 2026

- Added LLM token usage reporting on the provider contract:
  - `pipeline/llm_provider.py`: new `TokenUsage` dataclass (`input_tokens`, `output_tokens`, `total_tokens`, `__add__`) and non-abstract `LLMProvider.last_token_usage` property defaulting to `None`.
  - `pipeline/llm_ollama.py`: `OllamaProvider.last_token_usage` reads `prompt_eval_count` / `eval_count` from each `generate` response.
  - `pipeline/llm_claude.py`: `ClaudeProvider.last_token_usage` reads `response.usage.input_tokens` / `output_tokens` from the Messages API.
  - `pipeline/_llm_retry.py`: `retry_llm_call` now returns `(result, TokenUsage)` summed across attempts.
- Plumbed usage through pipeline stages:
  - `pipeline/resolution.py`: `LLMEntityResolver.last_token_usage` captures the usage reported by the last `resolve` call.
  - `pipeline/extraction.py`: `LLMRelationshipExtractor.last_token_usage` captures extract-call usage.
  - `pipeline/cold_start.py`: `ColdStartEntityDiscoverer.last_token_usage` captures discover-call usage.
  - `pipeline/orchestrator.py`: `_MetricsAccumulator` sums `input_tokens` / `output_tokens` from resolver, extractor, and cold-start stages per article.
- Extended run scorecard with token counters:
  - `knowledge_graph/models.py`: `RunMetrics` gained `input_tokens`, `output_tokens`, and a `total_tokens` derived property.
  - `knowledge_graph/storage.py`: `run_metrics` table gained `input_tokens` / `output_tokens` columns; added `_migrate_run_metrics` to upgrade existing databases.
  - `knowledge_graph/_run_mixin.py`: `save_run_metrics` / `get_run_metrics` persist and hydrate the new columns.
- Exported `TokenUsage` from `unstructured_mapping.pipeline`.
- Added unit tests:
  - `tests/unit/test_llm_provider.py`: `TokenUsage` arithmetic, Ollama usage surfacing, None when fields missing.
  - `tests/unit/test_llm_claude.py`: Claude usage surfacing and None-on-missing.
  - `tests/unit/test_resolution.py`: resolver propagates provider usage.
  - `tests/unit/test_pipeline.py`: run metrics accumulate token counts across articles.


### v0.42.1 - 15th April 2026

- `.claude/`: cross-project migration landed today:
  - Removed `.claude/hooks/block-raw-python.sh`; now provided globally at `~/.claude/hooks/` (PreToolUse Bash guard).


### v0.42.0 - 15th April 2026

- Added running entity header across chunks:
  - `pipeline/resolution.py`: `LLMEntityResolver.resolve` gained a `prev_entities` keyword argument that overrides the constructor-time list for that call. The prompt builder receives whichever is provided.
  - `pipeline/orchestrator.py`: `_process_article` accumulates `resolution.resolved` across chunks and passes the running tuple into each subsequent `_process_chunk` → `_llm_resolver.resolve` call. Later chunks' prompts now carry every entity earlier chunks resolved to — including LLM proposals that haven't landed in the KG yet, so the pre-scan gap is closed.
- Added run scorecard:
  - `knowledge_graph/models.py`: new `RunMetrics` dataclass capturing chunks_processed, mentions_detected, mentions_resolved_alias, mentions_resolved_llm, llm_resolver_calls, llm_extractor_calls, proposals_saved, relationships_saved, provider_name, model_name, wall_clock_seconds.
  - `knowledge_graph/storage.py`: `run_metrics` table keyed on `run_id` (FK to `ingestion_runs`). Split from the main run table so future metric additions don't churn existing rows.
  - `knowledge_graph/_run_mixin.py`: `save_run_metrics()` (upsert) and `get_run_metrics(run_id)`.
  - `pipeline/orchestrator.py`: `_MetricsAccumulator` tracks counters throughout a run; `Pipeline.run` finalises and persists the scorecard on both success and failure.
  - `Pipeline` reads `provider_name` / `model_name` from whichever configured LLM stage (`_llm_resolver`, `_extractor`, `_cold_start_discoverer`) has a provider attached. Token counts deliberately excluded — the `LLMProvider` contract does not expose usage yet; tracked as a follow-up.
- Added unit tests:
  - `tests/unit/test_pipeline.py`: `test_pipeline_threads_running_entity_header_across_chunks`, `test_pipeline_saves_run_metrics`, `test_pipeline_metrics_count_llm_calls_and_provider`.


### v0.41.0 - 14th April 2026

- Added `src/unstructured_mapping/pipeline/aggregation.py`: cross-chunk aggregator designed in `docs/pipeline/09_chunking.md` §"Aggregation".
  - `ChunkAggregator.aggregate(outcomes)`: dedupes proposals on lowercased `canonical_name` + `entity_type` (keeps the longest description), dedupes relationships on `(source_id, target_id, relation_type)` (keeps the richest `context_snippet`), flags same-name-different-type collisions as `ProposalConflict` records and drops both sides rather than guess.
  - `ChunkOutcome` / `AggregatedOutcome` / `ProposalConflict` dataclasses for the in-memory handoff between per-chunk processing and persistence.
- `src/unstructured_mapping/pipeline/orchestrator.py`:
  - Refactored `_process_chunk` to return a `ChunkOutcome` *without* KG writes. Renamed `_save_proposals`/`_extract_relationships` to `_persist_proposals`/`_persist_relationships` (pure persistence); extraction now runs inside `_process_chunk`, persistence runs once per article after aggregation.
  - `_process_article` drives the new flow: chunks → per-chunk outcomes → aggregator → single `store.transaction()` that writes provenance + proposal entities + relationships in one batch. Per-chunk duplicate proposals (two chunks both proposing "NewCo") now collapse to a single KG entity.
  - Added `_document_prescan(article, doc_id)`: runs the rule-based detector over the whole article body, batch-fetches candidate entities via `store.get_entities`, returns them as a tuple. Fired only when the segmenter produces >1 chunk.
  - Pre-scan candidates ride into every chunk's `LLMEntityResolver.resolve(..., extra_candidates=...)` call so long-range coreference ("the company" in chunk 5 referring to Apple from chunk 1) has a candidate in the KG context window.
- `src/unstructured_mapping/pipeline/resolution.py`:
  - `LLMEntityResolver.resolve` gained an `extra_candidates` keyword argument; `_collect_candidates` appends them after the mention-derived candidates, deduplicated by `entity_id`. Chunk-local candidates retain priority so budget clipping preserves the most locally-relevant entities.
- Added unit tests:
  - `tests/unit/test_aggregation.py`: 10 tests covering proposal dedup, case-insensitive name match, type-conflict handling, relationship dedup (same vs different relation types), provenance pass-through, degenerate inputs.
  - `tests/unit/test_pipeline.py`: `test_pipeline_aggregator_dedupes_duplicate_proposals` and `test_pipeline_alias_prescan_pulls_full_body_matches`.


### v0.40.0 - 14th April 2026

- `src/unstructured_mapping/pipeline/segmentation/`:
  - Added `_sub_chunk.py` with `estimate_tokens`, `sub_chunk_by_paragraph`, and `expand_section`. Provides the hybrid-fallback paragraph splitter designed in `docs/pipeline/09_chunking.md` §"Segmentation strategy": oversized sections split at paragraph boundaries with configurable 10–20% overlap; oversized single paragraphs pass through untouched rather than risk a mid-sentence cut.
  - `ResearchSegmenter`, `TranscriptSegmenter`, `FilingSegmenter` gained `max_tokens` + `overlap_ratio` constructor kwargs. Default behaviour (no sub-chunking) is unchanged.
- `src/unstructured_mapping/pipeline/orchestrator.py`:
  - `Pipeline(segmenter=...)`: optional `DocumentSegmenter` injected at construction. When set, each article is split into chunks and every chunk flows through the existing detection / resolution / extraction stages in turn. When unset the legacy single-chunk behaviour is preserved.
  - Extracted `_process_chunk` + `_ChunkOutcome`: per-chunk logic refactored out of `_process_article` so the per-chunk loop can accumulate counts and resolution results cleanly.
  - Per-article writes now share one `store.transaction()` — an N-chunk research report writes N chunks' provenance / proposals / relationships with one fsync.
  - Cold-start mode continues to see the full article body by design; segmenter is ignored in that path.
- Added unit tests:
  - `tests/unit/test_segmentation.py`: sub-chunk helper tests (paragraph boundary, overlap, oversized paragraph, empty input, token estimate) plus per-segmenter oversized-section tests.
  - `tests/unit/test_pipeline.py`: `test_pipeline_with_segmenter_processes_each_chunk` and `test_pipeline_without_segmenter_preserves_legacy_behaviour`.


### v0.39.0 - 14th April 2026

- Added `src/unstructured_mapping/pipeline/segmentation/`: document-aware chunking module following `docs/pipeline/09_chunking.md`.
  - `base.py`: `DocumentSegmenter` ABC and `DocumentType` enum (`news` / `research` / `transcript` / `filing`).
  - `news.py`: `NewsSegmenter` emits one chunk per article (preserves inverted-pyramid behaviour).
  - `research.py`: `ResearchSegmenter` splits on ATX (`## Title`) and setext (`Title`/`=====`) markdown headings; drops preamble before the first heading.
  - `transcript.py`: `TranscriptSegmenter` splits on speaker labels (`Tim Cook - CEO:`) and emits a dedicated `Q&A` divider chunk.
  - `filing.py`: `FilingSegmenter` splits on `Item N.` / `Item NA.` headings (case-insensitive) with long-line guards against in-body mentions.
- Added `tests/unit/test_segmentation.py`: 19 tests covering all four segmenters, the enum, ABC instantiation guard, and edge cases (empty text, no headings, multi-line turns, oversized false-positive lines).
- Sub-chunking of oversized sections (hybrid fallback) and pipeline wiring (document-level alias pre-scan, running entity header, aggregation) are deferred — tracked as follow-up backlog items.


### v0.38.2 - 14th April 2026

- Optimization batch from the v0.38.1 review. Behaviour preserved; 465 unit tests pass.
- `src/unstructured_mapping/storage_base.py`:
  - Added `SQLiteStore._commit()` and reentrant `transaction()` context manager. Write helpers now defer the actual COMMIT to the enclosing transaction block; rollback on exception.
- `src/unstructured_mapping/knowledge_graph/`:
  - Replaced every direct `self._conn.commit()` in `_entity_mixin.py`, `_provenance_mixin.py`, `_relationship_mixin.py`, and `_run_mixin.py` with `self._commit()` so the transaction wrapper is honoured everywhere.
  - `storage.py`: added composite index `idx_entity_name_type` on `(canonical_name COLLATE NOCASE, entity_type)`.
  - `_entity_mixin.py`:
    - `get_entities(ids)`: batch-load by id with a single `WHERE IN (...)` query.
    - `exists_by_name_and_type(name, type)`: direct SQL existence check using the new composite index.
    - `alias_exists(alias)`: lightweight `SELECT 1` existence probe — no JOIN, no entity hydration.
  - `_provenance_mixin.py`: `documents_with_provenance(ids) -> set[str]` batch idempotency lookup.
- `src/unstructured_mapping/pipeline/`:
  - `resolution.py`: `LLMEntityResolver` accepts an optional `entity_batch_lookup`; `_collect_candidates` loads every candidate in one query when available.
  - `orchestrator.py`: `run()` pre-fetches `documents_with_provenance` once; `_process_article` takes a pre-computed `already_processed` set via `_is_processed` helper.
  - `detection.py`: `RuleBasedDetector` docstring documents the bounded-fetch contract; example code passes `limit=5000`.
- `src/unstructured_mapping/cli/`:
  - `_seed_helpers.import_with_dedup` wraps its loop in `store.transaction()` — populate-run fsyncs drop from ~2000 to 1.
  - `_seed_helpers.exists_by_name_and_type` is now a thin wrapper over the store method.
  - `wikidata_seed._already_imported` uses `alias_exists` instead of `find_by_alias`.
- `src/unstructured_mapping/web_scraping/storage.py`:
  - Routed article-store commits through `_commit()` so the same `transaction()` wrapper works for batched scrapes.
- Added unit tests in `tests/unit/test_kg_entities.py`:
  - `test_store_get_entities_batch`, `test_store_get_entities_empty_returns_empty_dict`, `test_store_get_entities_deduplicates_ids`.
  - `test_transaction_defers_commit_and_rolls_back_on_error`, `test_transaction_commits_on_exit`.
- `.gitignore`:
  - Ignored `.claude/scheduled_tasks.lock` and `data/seed/wikidata_dryrun/` (runtime/exploratory artefacts accidentally tracked earlier).


### v0.38.1 - 14th April 2026

- Refactor batch from the v0.38.0 review. No behaviour changes; all 460 tests still pass.
- `src/unstructured_mapping/wikidata/`:
  - Collapsed the seven `map_*_row()` functions in `mapper.py` through a single `_make_row_mapper()` factory. Each type is now an entity-type/subtype pair plus a small ``build(label, row) -> (description, extras)`` function; the shared boilerplate (`_extract_item`, wikidata-description append, `_make_mapped`) lives in one place. Public names unchanged.
  - Added `registry.py` with `TYPE_REGISTRY` and `TypeHandler` dataclass. Exposed via `wikidata/__init__.py` so non-CLI consumers can enumerate supported categories without importing a CLI internal.
- `src/unstructured_mapping/cli/`:
  - Added `_seed_helpers.py` with `import_with_dedup()` and `exists_by_name_and_type()`. Both `cli/seed.py::load_seed` and `cli/wikidata_seed.py::import_entities` now delegate to the shared loop — the loaders only declare the per-source callbacks (entity extraction, duplicate check, counter key, reason).
  - `cli/wikidata_seed.py`: replaced the inlined `_TYPE_HANDLERS` with an alias pointing at `wikidata.TYPE_REGISTRY`.
  - `cli/db_health.py`: extracted `_build_parser()` to match the CLI pattern used by the other modules.
- `tests/unit/`:
  - Moved the duplicated `_write_seed()` helper from `test_cli_seed.py` and `test_cli_populate.py` into `conftest.write_seed_file()`.


### v0.38.0 - 14th April 2026

- Preserved Wikidata provenance on snapshot replay:
  - `cli/seed.py`: `load_seed()` now honours a top-level `"reason"` string in the seed payload, defaulting to `"seed"` when absent. Snapshots carrying `"reason": "wikidata-seed"` round-trip the origin signal into `entity_history` when `cli.populate` rebuilds the KG.
  - `cli/wikidata_seed.py`: `_write_snapshot()` emits `"reason": "wikidata-seed"` in the header.
  - Refreshed all 7 Wikidata snapshots under `data/seed/wikidata/` to carry the new `reason` field.
- Added unit tests:
  - `tests/unit/test_cli_seed.py`: `test_load_seed_honours_reason_hint_in_payload`.
  - `tests/unit/test_wikidata_seed.py`: extended `test_write_snapshot_produces_seed_compatible_file` to assert the reason is written.
- Updated `docs/seed/reproducibility.md` to document the reason-hint round-trip and drop the outdated caveat about provenance loss.


### v0.37.1 - 14th April 2026

- Tightened `EXCHANGES_QUERY` in `wikidata/queries.py`:
  - Added `MINUS` clauses for `Q22687` (bank) and `Q806735` (brokerage firm) in the inner subquery so banks and broker-dealers that Wikidata directly tags as P31 stock exchange no longer land in the import. Commerzbank and OTP banka are now filtered out. Residual noise (FXCM, Convergex, KCG Americas, Deutsche Bank ATS) is tracked in `backlog.md` — those entities are classed under forex-broker / ATS / market-maker, which need separate MINUS entries.
  - Added `_Q_BANK` and `_Q_BROKERAGE` module constants alongside the existing class QIDs for consistency.
- Added `test_exchange_query_excludes_banks_and_brokerages` in `tests/unit/test_wikidata_seed.py` to pin the MINUS clauses.
- Refreshed `data/seed/wikidata/exchange.json` snapshot with the new query (511 rows, down from 513).


### v0.37.0 - 14th April 2026

- Added `cli/populate.py`: one-command orchestrator that replays the curated seed then every Wikidata snapshot under `data/seed/wikidata/` against the KG. Supports `--seed-dir`, `--db`, `--dry-run`. Exposes `populate()` and `StageReport` for programmatic use.
- Added unit tests in `tests/unit/test_cli_populate.py`: 9 tests covering stage ordering (curated first), idempotence, dry-run, curated-wins-on-conflict, empty-seed-dir error, and missing-curated-file fallback.
- Updated `docs/seed/reproducibility.md`: replaced the shell-loop rebuild recipe with the single `cli.populate` invocation.


### v0.36.0 - 14th April 2026

- Committed Wikidata seed snapshots as the reproducibility source of truth:
  - Added `data/seed/wikidata/`:
    - `currency.json`, `central_bank.json`, `exchange.json`, `regulator.json`, `index.json`, `crypto.json`, `company.json`.
  - The populated `data/knowledge.db` stays gitignored; a fresh clone rebuilds the KG by replaying the curated seed then each Wikidata snapshot via `cli.seed`.
- Added `docs/seed/reproducibility.md`: documents the hybrid strategy (seeds committed, DB local), the alternatives considered (commit `.db`, rebuild live from Wikidata), and the accepted trade-offs.
- Updated `docs/seed/wikidata.md`:
  - Fixed stale class QIDs in the type matrix to reflect the v0.35.2 corrections (`Q66344` central bank, `Q105062392` regulator, `Q223371` stock index).
  - Cross-linked the snapshot section to `reproducibility.md`.


### v0.35.2 - 14th April 2026

- Fixed Wikidata SPARQL query templates in `wikidata/queries.py`:
  - Corrected three wrong class QIDs shipped in v0.33.0:
    - Central bank: `Q46825` → `Q66344`. The old value matched religious-art entities, not central banks.
    - Financial regulator: `Q17278032` → `Q105062392`. The old value matched nothing.
    - Stock market index: `Q167270` → `Q223371`. The old value matched record labels.
  - Rewrote every template to use the subquery `LIMIT` idiom — the `LIMIT` now caps distinct items in an inner `SELECT DISTINCT`, not post-OPTIONAL cartesian rows. Fixes two symptoms: the `index` query returning only 2 rows (labels dropping to bare QIDs when the label service ran out of budget), and the `company` query timing out at HTTP 502 after ~112 seconds (now 0.9s).
  - Dropped `ORDER BY DESC(?marketCap)` from the company query — Wikidata can't sort the intermediate result set at any reasonable limit without timing out.
  - Tightened `exchange` and `crypto` filters from `wdt:P31/wdt:P279*` to direct `wdt:P31` — excludes clearing houses and crypto-exchange entities that the subclass tree previously pulled in.
- Added unit tests in `tests/unit/test_wikidata_seed.py`:
  - `test_queries_reference_expected_class_qids` — pins the class QIDs so a typo fails CI.
  - `test_queries_use_subquery_limit_pattern` — enforces the subquery `LIMIT` idiom across all templates.


### v0.35.1 - 14th April 2026

- Updated `docs/knowledge_graph/schema.md`: added one-line clarifications under `entity_history` and `relationship_history` headers explaining that each row is a *revision* identified by `history_id` (a global counter, not a per-entity revision number) — closes a terminology gap between the row-level "revision" wording and the renamed column.


### v0.35.0 - 14th April 2026

- Renamed `revision_id` to `history_id` throughout the `knowledge_graph/` module to better reflect that the column is a global audit-log sequence, not a per-entity revision number:
  - `storage.py`: `entity_history.revision_id` and `relationship_history.revision_id` columns renamed.
  - `models.py`: `EntityRevision.revision_id` and `RelationshipRevision.revision_id` fields renamed.
  - `_entity_mixin.py`: `revert_entity()` parameter renamed; SQL queries updated.
  - `_relationship_mixin.py`: SQL queries updated.
  - `_helpers.py`: row-to-dataclass converters updated.
  - `exceptions.py`: `RevisionNotFound.revision_id` attribute and constructor parameter renamed.
- Updated documentation:
  - `docs/knowledge_graph/schema.md`: column names and purpose descriptions updated.
  - `docs/knowledge_graph/design.md`: `revert_entity` signature reference updated.
- Existing databases need a one-off `ALTER TABLE ... RENAME COLUMN revision_id TO history_id` on both `entity_history` and `relationship_history`.


### v0.34.0 - 14th April 2026

- Fixed entity timestamp handling in `knowledge_graph/`:
  - `_entity_mixin.py`: `save_entity()` now owns `created_at` and `updated_at` — stamps both on create, preserves `created_at` across updates, and bumps `updated_at` on every save. A caller-provided `created_at` on a brand-new entity is still respected (useful for backfills and history-preserving imports).
  - `_entity_mixin.py`: added `backfill_entity_timestamps()` — one-shot helper that pulls authoritative create times from `entity_history` onto rows with NULL timestamps. Safe to re-run.
- Updated unit tests in `tests/unit/test_kg_entities.py`:
  - Replaced `test_entity_updated_at_round_trip` with three behavioural tests (`test_save_entity_stamps_timestamps_on_create`, `test_save_entity_respects_explicit_created_at`, `test_save_entity_advances_updated_at_on_update`).
  - Added `test_backfill_entity_timestamps_populates_nulls`.


### v0.33.0 - 13th April 2026

- Extended Wikidata seed pipeline to six additional types:
  - `wikidata/queries.py`: added `CENTRAL_BANKS_QUERY`, `REGULATORS_QUERY`, `EXCHANGES_QUERY`, `CURRENCIES_QUERY`, `INDICES_QUERY`, `CRYPTO_QUERY`.
  - `wikidata/mapper.py`: added `map_central_bank_row()`, `map_regulator_row()`, `map_exchange_row()`, `map_currency_row()`, `map_index_row()`, `map_crypto_row()`; factored out `_extract_item()` and `_make_mapped()` helpers.
  - `cli/wikidata_seed.py`: registered the new types in `_TYPE_HANDLERS`; CLI `--type` now accepts `company`, `central_bank`, `regulator`, `exchange`, `currency`, `index`, `crypto`.
- Extended external-identifier alias prefixes:
  - `mic:` for Market Identifier Codes (exchanges, P2283).
  - `iso:` for ISO 4217 currency codes (P498).
  - `symbol:` for cryptocurrency symbols (P498).
- Added unit tests: 13 new mapper tests + 2 new CLI registry tests in `tests/unit/test_wikidata_mapper.py` and `tests/unit/test_wikidata_seed.py`.
- Updated `docs/seed/wikidata.md` with the full type matrix and explicit rationale for deliberately-excluded populations (rating agencies, commodities, legislation, persons).


### v0.32.0 - 13th April 2026

- Added `wikidata/` module for KG bootstrap from Wikidata:
  - `client.py`: `SparqlClient` with retry/backoff on 429 and 5xx.
  - `queries.py`: `LISTED_COMPANIES_QUERY` and `build_query()`.
  - `mapper.py`: `map_company_row()` and `MappedEntity`.
- Added `cli/wikidata_seed.py`: fetches companies from Wikidata, dedups by `wikidata:Qxxx` alias then by `canonical_name`+type, tags history with `reason="wikidata-seed"`. Supports `--type`, `--limit`, `--dry-run`, and `--snapshot` for reproducibility.
- Added external-identifier alias convention: `wikidata:Qxxx`, `ticker:AAPL`, `isin:US0378331005` — documented in `docs/seed/wikidata.md`.
- Added unit tests:
  - `tests/unit/test_wikidata_client.py`: 4 tests using `httpx.MockTransport`.
  - `tests/unit/test_wikidata_mapper.py`: 9 tests.
  - `tests/unit/test_wikidata_seed.py`: 8 tests.


### v0.31.5 - 12th April 2026

- Refactored `knowledge_graph/`:
  - Added `EntityHelpersMixin._find_entities_where()`:
    shared query-assembly helper.
  - Rewrote `EntitySearchMixin.find_entities_by_type`,
    `find_entities_by_subtype`,
    `find_entities_by_status`, `find_by_name_prefix`,
    and `find_entities_since` as thin wrappers around
    it.
- Refactored `pipeline/`:
  - Added `_optional_import.py`:
    - `try_import()`: lazy SDK loader.
    - `require_llm_extra()`: standard ImportError
      raiser for missing `llm` extras.
  - Updated `llm_claude.py` and `llm_ollama.py` to use
    the helpers instead of duplicated try/except and
    inline ImportError messages.
  - Replaced stale "backlog item 2e" reference in
    `LLMEntityResolver` docstring with a direct link
    to `retry_llm_call`.
- Refactored `web_scraping/`:
  - Added `Scraper.default_feed_urls` and
    `Scraper.default_fetch_full_text` class attributes.
  - Removed redundant pass-through `__init__` from
    `BBCScraper` and `ReutersScraper`; they now declare
    only the class-level defaults that differ from the
    base.
  - Simplified `APScraper.__init__` to resolve
    `fetch_full_text` via the new class attribute while
    keeping the optional-dependency check.
- Chore:
  - Removed stray `*.tmp.*` temp files under `src/`
    and `tests/`; added `*.tmp.*` to `.gitignore`.


### v0.31.4 - 12th April 2026

- Updated `.claude/hooks/block-chained-commands.sh`:
  propagated newline-chaining block from the
  programme canonical.


### v0.31.2 - 12th April 2026

- Refactored `tests/unit/`:
  - Consolidated fixture factories in `conftest.py`:
    added `make_org`, `make_chunk`, `make_mention`,
    `make_resolved`, and `make_article`. Removed
    duplicated copies from `test_detection.py`,
    `test_extraction.py`, `test_pipeline.py`,
    `test_resolution.py`, and `test_cold_start.py`.
- Refactored `knowledge_graph/`:
  - Added `TYPE_CHECKING`-guarded cross-mixin method
    declarations on `EntityHelpersMixin`
    (`save_entity`, `get_entity`) and `ProvenanceMixin`
    (`_load_aliases_batch`). Removed seven
    `# type: ignore[attr-defined]` / `[arg-type]`
    comments from `_entity_mixin.py` and
    `_provenance_mixin.py` and narrowed the None-checks
    in `merge_entities`.


### v0.31.1 - 12th April 2026

- `pipeline/orchestrator.py`: documented cold-start mode
  alongside the normal path — module docstring,
  `Pipeline` example block, and `ArticleResult` field
  descriptions now cover both modes.


### v0.31.0 - 12th April 2026

- Added cold-start LLM mode for bootstrapping an empty KG:
  - `pipeline/cold_start.py`: new
    `ColdStartEntityDiscoverer` that asks the LLM to
    propose entities straight from raw article text,
    reusing the pass 1 prompt with an empty candidate
    set so every returned entity becomes a proposal.
  - `pipeline/detection.py`: added `NoopDetector`
    utility that always returns zero mentions.
  - `pipeline/orchestrator.py`: new
    `cold_start_discoverer` kwarg on `Pipeline`; when
    set, the orchestrator skips detection, resolution,
    and relationship extraction for each article and
    persists proposals via the existing
    `_save_proposals` path.
- Added unit tests:
  - `tests/unit/test_cold_start.py`: 8 tests covering
    discovery, prompt shape, hallucination rejection,
    pipeline integration, detector bypass, and
    idempotency.
- Added `docs/pipeline/13_cold_start.md`; updated
  `12_kg_population.md` to reference the shipped mode.


### v0.30.1 - 12th April 2026

- Updated `docs/pipeline/12_kg_population.md`: replaced
  the pre-implementation bootstrap snippet with the actual
  shipped seed file path, JSON schema, and CLI usage.


### v0.30.0 - 12th April 2026

- Added KG bootstrap seed:
  - `data/seed/financial_entities.json`: curated seed of
    ~90 core financial/market-moving entities (central
    banks, regulators, exchanges, top companies,
    policymakers, indices, currencies, commodities,
    macro metrics).
  - `cli/seed.py`: idempotent loader that reads the seed
    JSON, skips existing entities (case-insensitive match
    on canonical name + type), and tags new rows with
    `reason="seed"` in the entity history. Supports
    `--seed`, `--db`, and `--dry-run` flags.
- Added unit tests:
  - `tests/unit/test_cli_seed.py`: 14 tests covering
    parsing, idempotency, dry-run, history tagging, and
    curated file validity.


### v0.29.0 - 12th April 2026

- `pipeline/orchestrator.py`:
  - Wired `RelationshipExtractor` into the `Pipeline`:
    optional `extractor` parameter runs pass 2 after
    resolution, converts `ExtractedRelationship` to
    `Relationship`, and persists via
    `save_relationships()`.
  - Added `relationships_saved` field to `ArticleResult`
    and `PipelineResult`.
  - Updated `_compute_run_stats()`: now returns 4-tuple
    including relationship count.
  - Updated `finish_run()` calls: `relationship_count`
    is now populated in `IngestionRun`.
  - Updated run completion log: includes
    `"%d relationships"`.
  - Removed "intentionally out of scope" note from
    module docstring.
- `docs/pipeline/`:
  - Rewrote `10_orchestration.md`: documents all 4
    stages (detection, resolution, extraction,
    persistence), field mapping table, updated diagrams
    and interface docs.
- `tests/unit/`:
  - Added 5 tests to `test_pipeline.py`: extraction
    integration, no-extractor default, error isolation,
    run relationship_count, extractor receives resolved
    entities.


### v0.28.3 - 12th April 2026

- `pipeline/orchestrator.py`:
  - Added `proposals_saved` field to `PipelineResult`:
    aggregates new entities created from LLM proposals
    across all articles.
  - Updated `_compute_run_stats()`: now returns
    `(doc_count, prov_count, proposal_count)` tuple.
  - Updated run completion log: now includes
    `"%d new entities"` alongside provenances.
- `knowledge_graph/`:
  - Updated `IngestionRun.entity_count` docstring:
    clarified it tracks provenance records (entity
    mention count), not distinct entities created.
  - Updated `finish_run()` docstring: same clarification.


### v0.28.2 - 12th April 2026

- `docs/pipeline/`:
  - Added `12_kg_population.md`: KG population strategy
    covering the bootstrap problem, two-phase approach
    (curated seed + organic LLM growth), seed
    implementation guide, cold-start LLM mode (future),
    Wikidata as alternative seed source, and operational
    considerations.


### v0.28.1 - 12th April 2026

- `pipeline/`:
  - Added `_llm_retry.py`: shared `retry_llm_call()`
    helper and `append_error()` function, extracted from
    duplicate implementations in `resolution.py` and
    `extraction.py`.
  - Refactored `resolution.py`: replaced inline retry
    loop and `_append_error` static method with shared
    `retry_llm_call()`.
  - Refactored `extraction.py`: replaced inline retry
    loop and `_append_error` function with shared
    `retry_llm_call()`.
  - Refactored `llm_parsers.py`: unified `_parse_json()`
    and `_parse_json_pass2()` into a single function
    parameterized by exception class.
  - Refactored `__init__.py`: sorted `__all__` and
    imports fully alphabetically.
- `tests/unit/`:
  - Added `FakeProvider` to `conftest.py`: shared fake
    LLM provider replacing 3 duplicate implementations.
  - Refactored `test_extraction.py`,
    `test_resolution.py`, `test_llm_provider.py`:
    replaced local `_FakeProvider` with shared
    `FakeProvider`.


### v0.28.0 - 11th April 2026

- `knowledge_graph/`:
  - Added `validation.py`:
    - `validate_temporal()`: enforced at save time,
      raises `ValidationError` if `valid_until <
      valid_from`.
    - `find_alias_collisions()`: advisory audit for
      aliases shared across entities.
    - `AliasCollision` dataclass for structured results.
    - `check_relationship_constraints()`: check a
      relationship against canonical patterns from
      `relationships.md`.
    - `audit_relationship_constraints()`: scan all KG
      relationships for constraint warnings.
    - `ConstraintWarning` dataclass for audit results.
    - `RELATIONSHIP_CONSTRAINTS` dict with 22 canonical
      entity-type pair patterns.
  - Updated `_entity_mixin.py`: `save_entity()` calls
    `validate_temporal()` before INSERT.
  - Updated `_relationship_mixin.py`:
    `save_relationship()` and `save_relationships()`
    call `validate_temporal()`.
  - Updated `__init__.py`: exports all new public names.
- `docs/knowledge_graph/`:
  - Added `validation.md`: design rationale for
    save-time vs advisory validation, temporal checks,
    alias collisions, relationship constraints.
- `tests/unit/`:
  - Added `test_kg_validation.py`: 22 tests covering
    temporal consistency (entity + relationship), alias
    collision detection, relationship constraint
    checking, and save-time integration.


### v0.27.1 - 11th April 2026

- `docs/pipeline/`:
  - Added `11_extraction.md`: extraction stage design
    doc covering architecture, extract flow, validation
    strategy (hard vs soft), name resolution, date
    parsing, and design decisions.
  - Updated `02_models.md`: `ExtractedRelationship`
    fields now match implementation (`_id` not `_ref`,
    `datetime` not strings), added `ExtractionResult`.
  - Updated `06_prompts.md`: added Pass 2 prompt
    documentation (`PASS2_SYSTEM_PROMPT`,
    `build_entity_list_block()`,
    `build_pass2_user_prompt()`).
  - Updated `08_llm_parsers.md`: added Pass 2 parser
    documentation (hard/soft validation split, entity
    reference resolution, date parsing, qualifier
    handling).


### v0.27.0 - 11th April 2026

- `pipeline/`:
  - Added `extraction.py`:
    - `RelationshipExtractor` ABC with `extract()` method.
    - `LLMRelationshipExtractor`: LLM-based pass 2
      implementation with retry logic, name-to-ID
      resolution, and proposal entity support.
  - Added `models.py`:
    - `ExtractedRelationship`: intermediate model for
      LLM-extracted relationships (before KG persistence).
    - `ExtractionResult`: extraction stage output.
  - Added `prompts.py`:
    - `PASS2_SYSTEM_PROMPT`: system prompt for
      relationship extraction.
    - `build_entity_list_block()`: formats "ENTITIES IN
      THIS TEXT" block for pass 2.
    - `build_pass2_user_prompt()`: assembles pass 2
      user prompt.
  - Added `llm_parsers.py`:
    - `Pass2ValidationError`: structural validation
      errors for retry.
    - `parse_pass2_response()`: validates pass 2 rules
      with soft drops for unresolvable refs, bad dates,
      and self-refs.
  - Updated `__init__.py`: exports all new public names.
- `tests/unit/`:
  - Added `test_extraction.py`: 18 tests covering ABC
    contract, happy path, name resolution, self-ref
    drops, retry logic, proposals, qualifier handling.
  - Updated `test_llm_parsers.py`: 25 tests for pass 2
    parsing, date handling, soft drops, structural
    errors, qualifier resolution.
  - Updated `test_prompts.py`: 11 tests for pass 2
    system prompt, entity list block, user prompt.


### v0.26.0 - 11th April 2026

- `pipeline/`:
  - Added `ClaudeProvider`: Anthropic Messages API
    provider for quality/cost benchmarking against the
    Ollama baseline.
  - Added `llm_claude.py`: guarded `anthropic` import,
    error translation
    (`APITimeoutError` -> `LLMTimeoutError`,
    `APIConnectionError` -> `LLMConnectionError`),
    configurable `max_tokens` and `context_window`.
  - Updated `llm_provider.py`: docstring lists
    `llm_claude` as a concrete provider.
  - Updated `__init__.py`: exports `ClaudeProvider`.
- `pyproject.toml`:
  - Added `anthropic>=0.42.0` to `llm` and `dev` extras.
- `tests/unit/`:
  - Added `test_llm_claude.py`: 12 tests covering happy
    path, error translation, metadata, json_mode guard,
    dependency guard, and edge cases.


### v0.25.1 - 11th April 2026

- `.claude/rules/`:
  - Decoupled `/refactor` rule: canonical
    `refactoring.md` is now procedural only.
  - Added `refactoring-areas.md` with
    project-specific code smells to watch.
- `.claude/skills/refactor/`:
  - Updated `SKILL.md` to read both canonical
    procedure and per-project areas.


### v0.25.0 - 11th April 2026

- Updated `pipeline/orchestrator.py`:
  - `Pipeline` accepts optional `llm_resolver` parameter for LLM cascade after the primary resolver
  - Unresolved mentions from the alias resolver are automatically passed to the LLM resolver
  - Added `_save_proposals()`: persists `EntityProposal`s as new `Entity` objects (status=ACTIVE) with provenance linked to the run
  - `ArticleResult` gains `proposals_saved` field tracking new entities created per article
- Added 5 unit tests for LLM cascade:
  - Ambiguous mentions resolved by LLM cascade
  - LLM proposals persisted as new entities in KG
  - Proposal provenance linked to ingestion run
  - No-LLM fallback leaves unresolved mentions
  - LLM resolver skipped when all mentions already resolved


### v0.24.2 - 11th April 2026

- `.claude/rules/`:
  - Decoupled `/optimize` rule: canonical
    `optimization.md` is now procedural only.
  - Added `optimization-areas.md` with
    project-specific performance areas.
- `.claude/skills/optimize/`:
  - Updated `SKILL.md` to read both canonical
    procedure and per-project areas.


### v0.24.1 - 11th April 2026

- Updated `pipeline/resolution.py`:
  - `LLMEntityResolver.resolve()`: added retry with error feedback per `03_llm_interface.md` § "Retry and error feedback"
  - On `Pass1ValidationError`, appends error message to user prompt and retries once (max 2 attempts)
  - After two failures, raises `LLMProviderError` so the orchestrator can skip the chunk
  - Added `_append_error()` static method for retry prompt formatting
  - Added `MAX_ATTEMPTS` class constant
- Added 3 unit tests for retry behavior:
  - Two failures raise `LLMProviderError` with 2 LLM calls
  - Retry succeeds on second attempt
  - Retry prompt contains error feedback text


### v0.24.0 - 10th April 2026

- Added `pipeline/resolution.py`:
  - `LLMEntityResolver`: LLM-based entity resolver composing prompt builder, token budget manager, and response parser into a single `resolve()` call
  - Accepts injectable `entity_lookup` callable to decouple from storage layer
  - Supports `prev_entities` for running entity header across multi-chunk documents
  - Exposes `proposals` property for new entity proposals from the LLM
- Added 12 unit tests for `LLMEntityResolver`:
  - Resolved entities, new entity proposals, mixed responses
  - Candidate deduplication, missing candidate handling
  - Validation error propagation, section name propagation
  - Previous entities in prompt, proposals reset between calls
- Exported `LLMEntityResolver` from `pipeline/__init__.py`


### v0.23.4 - 10th April 2026

- Refactored `pipeline/llm_ollama.py`:
  - Extracted `_ctx_from_model_info()` and `_ctx_from_parameters()` from `_find_num_ctx()` to reduce cyclomatic complexity
- Refactored `knowledge_graph/_entity_mixin.py`:
  - Split 616-line `EntityMixin` into four focused sub-mixins:
    - `EntityCRUDMixin`: save, get, find by name/alias
    - `EntitySearchMixin`: filtered queries and aggregate counts
    - `EntityMergeMixin`: merge with FK redirection
    - `EntityHistoryMixin`: revision history, point-in-time, revert
  - Extracted shared helpers into `_entity_helpers.py`
  - `EntityMixin` now composes all four via multiple inheritance
- Standardized test helper naming:
  - Adopted `make_*` convention across all test files
  - `conftest.py`: `_make_entity` → `make_entity`
  - File-local helpers: `_chunk` → `make_chunk`, `_mention` → `make_mention`, `_org` → `make_org`, etc.


### v0.23.3 - 10th April 2026

- `.claude/rules/`:
  - Decoupled `/improvements` rule: canonical
    `improvements.md` is now procedural only.
  - Added `improvement-areas.md` with
    project-specific areas to watch.
- `.claude/skills/improvements/`:
  - Updated `SKILL.md` to read both canonical
    procedure and per-project areas.


### v0.23.2 - 10th April 2026

- Refactored `pipeline/budget.py`:
  - Extracted `_count_occurrences()` helper to eliminate duplicated while-True substring-counting loops in `_count_alias_matches()`
- Refactored `pipeline/orchestrator.py`:
  - Extracted `_compute_run_stats()` helper to deduplicate result filtering in error and success paths
  - Added missing `# noqa: BLE001` on broad `except Exception` for consistency


### v0.23.1 - 10th April 2026

- Renamed `docs/pipeline/` files with numerical prefixes for reading order:
  - `design.md` → `01_design.md`
  - `models.md` → `02_models.md`
  - `llm_interface.md` → `03_llm_interface.md`
  - `detection.md` → `04_detection.md`
  - `resolution.md` → `05_resolution.md`
  - `prompts.md` → `06_prompts.md`
  - `budget.md` → `07_budget.md`
  - `llm_parsers.md` → `08_llm_parsers.md`
  - `chunking.md` → `09_chunking.md`
  - `orchestration.md` → `10_orchestration.md`
- Updated all cross-references in docs, source docstrings, and `README.md`.


### v0.23.0 - 10th April 2026

- Added `pipeline/llm_parsers.py`:
  - `Pass1ValidationError`: exception for schema validation failures, message suitable for retry prompts.
  - `parse_pass1_response()`: parse raw LLM JSON and validate against the 5 rules from `llm_interface.md`, returning `(ResolvedMention, ...), (EntityProposal, ...)`.
- Added `EntityProposal` dataclass to `pipeline/models.py`: intermediate representation for LLM-proposed new entities before persistence validation.
- Added `docs/pipeline/llm_parsers.md`: design decisions for parsing and validation.
- Added `tests/unit/test_llm_parsers.py`: 31 tests covering valid responses, all 5 validation rules, edge cases, and the `EntityProposal` model.


### v0.22.0 - 10th April 2026

- Added `pipeline/budget.py`:
  - `estimate_tokens()`: character-based token estimator (`ceil(chars / 4)`).
  - `PromptBudget`: frozen dataclass with budget breakdown (system, response headroom, flexible).
  - `compute_budget()`: compute flexible budget from context window, system prompt, and response headroom.
  - `fit_candidates()`: rank candidates by alias match count, truncate KG context to fit budget, truncate chunk text as last resort.
- Added `tests/unit/test_budget.py`: 27 tests covering token estimation, budget computation, alias ranking, candidate truncation, and paragraph-level text truncation.


### v0.21.1 - 10th April 2026

- Added `docs/pipeline/prompts.md`: design decisions for prompt construction (system prompt wording, KG context format, running entity header, deferred items).
- Updated `README.md`: added prompt construction usage example under LLM Providers.


### v0.21.0 - 10th April 2026

- Added `pipeline/prompts.py`:
  - `PASS1_SYSTEM_PROMPT`: system prompt for LLM entity resolution pass.
  - `build_kg_context_block()`: format candidate entities as numbered text blocks.
  - `build_pass1_user_prompt()`: assemble user prompt with KG context, running entity header, and chunk text.
- Added `tests/unit/test_prompts.py`: 20 tests covering system prompt, KG block, running entity header, and user prompt assembly.


### v0.20.0 - 9th April 2026

- Added `pipeline/llm_provider.py`:
  - `LLMProvider` ABC: `generate()`, `model_name`,
    `provider_name`, `context_window`,
    `supports_json_mode`. Contract matches
    `docs/pipeline/llm_interface.md`.
  - Exception hierarchy: `LLMProviderError`,
    `LLMConnectionError`, `LLMTimeoutError`,
    `LLMEmptyResponseError`.
- Added `pipeline/llm_ollama.py`:
  - `OllamaProvider`: Ollama-first concrete
    implementation. Uses the `ollama` Python package,
    wraps `httpx.ConnectError`/`ConnectTimeout` as
    `LLMConnectionError`, `httpx.TimeoutException` as
    `LLMTimeoutError`, and empty responses as
    `LLMEmptyResponseError`. Auto-detects
    `context_window` via `/api/show` with a 4096-token
    fallback; explicit override skips the lookup.
    Optional import of `ollama` so the ABC module
    stays slim.
- Added `pyproject.toml`:
  - `llm` optional dependency group pinning
    `ollama>=0.4.0`. Added to `dev` too for tests.
- Added `tests/unit/test_llm_provider.py`: 18 tests
  covering the ABC contract, exception hierarchy,
  OllamaProvider happy path (dict and attribute
  response shapes), error translation
  (connection/timeout/empty/generic), and context
  window auto-detection.
- Updated `README.md`: new "LLM Providers" section
  with the OllamaProvider usage example.
- Updated `pipeline/__init__.py`: export
  `LLMProvider`, `OllamaProvider`, and the LLM
  exception hierarchy.
- Updated `backlog.md`: added `ClaudeProvider`
  follow-up item so a second concrete provider can be
  implemented once the baseline is exercised.


### v0.19.0 - 9th April 2026

- Added `pipeline/orchestrator.py`:
  - `Pipeline`: wires detection, resolution, and
    provenance persistence into a single callable.
    `run(articles)` opens an `IngestionRun`, processes
    each article in isolation (per-article failures
    are recorded, run continues), and finalizes the
    run with aggregated counts. `process_article()`
    exposed as a lower-level entry point for callers
    that don't need run tracking. `skip_processed`
    constructor flag controls idempotency.
  - `ArticleResult`: per-article outcome exposing the
    raw `ResolutionResult`, provenance count, skip
    flag, and error message.
  - `PipelineResult`: aggregate outcome with the run
    ID, per-article results, and totals.
- Added `knowledge_graph/_provenance_mixin.py`:
  - `KnowledgeStore.has_document_provenance()`: O(log
    n) point lookup backing pipeline idempotency.
- Added `tests/unit/`:
  - `test_pipeline.py`: 11 tests (happy path, skip,
    reprocess, per-article isolation, stub wiring).
  - `test_kg_provenance.py::test_has_document_provenance`
- Added `docs/pipeline/orchestration.md`: design notes
  for the orchestrator (single-chunk articles,
  per-article isolation, provenance-based idempotency,
  constructor injection, deferred extraction stage).
- Updated `README.md`: Quick Start and new
  "Pipeline Orchestration" section use the real API.


### v0.18.3 - 9th April 2026

- Updated `knowledge_graph/_entity_mixin.py`:
  `_log_entity()` now passes `entity.aliases` directly
  to `json.dumps()` instead of converting the tuple to
  a list first — `json.dumps()` accepts tuples, so the
  intermediate allocation was wasted on every entity
  save and history write.


### v0.18.2 - 9th April 2026

- Updated `web_scraping/`:
  - `base.py`: split parsing from enrichment.
    `Scraper._parse_feed()` now returns unenriched
    articles; `Scraper.fetch()` dedupes URLs across
    feeds first and calls `_enrich()` exactly once on
    the deduped list, so a URL appearing in multiple
    feeds triggers at most one full-text extraction.
  - `bbc.py`: `BBCScraper._parse_feed()` matches the
    new contract (drops `_SKIP_URL_RE` entries but no
    longer enriches).
- Added `tests/unit/test_web_scraping.py`:
  - `test_fetch_enriches_duplicate_url_once`


### v0.18.1 - 9th April 2026

- Updated `knowledge_graph/_entity_mixin.py`: added
  optional `limit` parameter to entity search methods:
  - `find_entities_by_type()`
  - `find_entities_by_subtype()`
  - `find_entities_by_status()`
  - `find_by_name_prefix()`
  - `find_entities_since()`
- Updated `knowledge_graph/_provenance_mixin.py`: added
  optional `limit` parameter to `find_co_mentioned()`.
  Caps the result set before alias batch-loading,
  avoiding unbounded memory use on large KGs.
- Added `tests/unit/`:
  - `test_kg_entities.py::test_entity_search_limit`
  - `test_kg_provenance.py::test_find_co_mentioned_limit`


### v0.18.0 - 9th April 2026

- Added `knowledge_graph/_relationship_mixin.py`:
  - `RelationshipMixin.save_relationships()`: bulk insert
    method mirroring `save_provenances()`. Dedupes input
    against itself and the existing rows (by PK
    `source_id, target_id, relation_type, valid_from`),
    then uses `executemany` for a single batched INSERT
    and logs only newly inserted rows to
    `relationship_history`.
- Added `tests/unit/test_kg_relationships.py`:
  - `test_save_relationships_bulk_insert`
  - `test_save_relationships_skips_duplicates`
  - `test_save_relationships_empty`


### v0.17.5 - 8th April 2026

- Refactored `knowledge_graph/_helpers.py`:
  - Replaced 6 fragile tuple-index row converters with `sqlite3.Row`-based named column access
  - Set `row_factory = sqlite3.Row` in `storage_base.py` for all stores
  - Fixed `find_co_mentioned()` row slicing to use named access
- Refactored `web_scraping/base.py`:
  - Simplified nested comprehension in `Scraper._enrich()` to a plain loop
- Fixed `cli/scheduler.py`:
  - Narrowed exception handling from `ValueError` to `sqlite3.Error`


### v0.17.4 - 8th April 2026

- Refactored `knowledge_graph/storage.py` (1482 lines) into domain-focused mixins:
  - `_helpers.py`: shared SQL fragments, datetime utilities, row converters
  - `_entity_mixin.py`: entity CRUD, search, merge, audit history
  - `_provenance_mixin.py`: provenance CRUD, co-mention queries
  - `_relationship_mixin.py`: relationship CRUD, qualifiers, history
  - `_run_mixin.py`: ingestion run tracking
  - `storage.py`: DDL, migrations, and `KnowledgeStore` class composing all mixins


### v0.17.3 - 8th April 2026

- Refactored `tests/unit/`:
  - Split `test_knowledge_graph.py` (1796 lines) into 4 focused modules:
    - `test_kg_models.py`: data model and enum tests
    - `test_kg_entities.py`: entity CRUD, search, merge, subtypes, history
    - `test_kg_provenance.py`: provenance, co-mentions, ingestion runs, migration
    - `test_kg_relationships.py`: relationship CRUD, qualifiers, history
  - Moved shared `_make_entity()` helper to `conftest.py`


### v0.17.2 - 7th April 2026

- Updated `docs/pipeline/`: replaced ASCII art diagrams with
  Mermaid across all pipeline documentation:
  - `chunking.md`: pipeline flow diagram.
  - `detection.md`: pipeline position diagram.
  - `llm_interface.md`: token budget allocation diagram.
  - `models.md`: data flow summary diagram.
  - `resolution.md`: pipeline position and resolution
    decision flow diagrams.


### v0.17.1 - 7th April 2026

- Added `docs/pipeline/resolution.md`: two-tier resolution
  strategy, AliasResolver decision logic, context snippet
  extraction algorithm, data flow diagram, design decisions
  (conservative resolution, section_name propagation,
  configurable context window), and future extensions.


### v0.17.0 - 7th April 2026

- Added `pipeline/resolution.py`:
  - `EntityResolver` ABC with `resolve(chunk, mentions)`
    interface.
  - `AliasResolver`: baseline resolver that resolves
    single-candidate mentions directly and leaves
    zero/multi-candidate mentions for LLM disambiguation.
  - `_extract_snippet()`: context window extraction with
    word-boundary trimming and ellipsis indicators.
- Added `pipeline/models.py`:
  - `ResolvedMention`: mention matched to a KG entity.
  - `ResolutionResult`: separates resolved from unresolved
    mentions.
- Added `tests/unit/test_resolution.py`: 24 tests covering
  models, snippet extraction, and resolver logic.


### v0.16.1 - 7th April 2026

- Added `docs/pipeline/detection.md`: Aho-Corasick algorithm
  explanation, complexity analysis, design decisions
  (case-insensitive matching, word-boundary enforcement,
  canonical name indexing, output ordering), and future
  extensions.


### v0.16.0 - 7th April 2026

- Added `pipeline` package:
  - `models.py`: `Chunk` and `Mention` dataclasses for
    pipeline stage communication.
  - `detection.py`: `EntityDetector` ABC and
    `RuleBasedDetector` using Aho-Corasick trie for
    O(n) alias matching with word-boundary enforcement.
- Added `tests/unit/test_detection.py`: 33 tests covering
  models, trie construction, scanning, word boundaries,
  and detector integration.


### v0.15.0 - 6th April 2026

- `knowledge_graph/models.py`:
  - Added `IngestionRun` dataclass with `RunStatus` enum for tracking pipeline executions
  - Added `run_id` field to `Provenance` and `Relationship` dataclasses
- `knowledge_graph/storage.py`:
  - Added `ingestion_runs` table with status, counters, and error tracking
  - Added `run_id` column to `provenance` and `relationships` tables (nullable, with migration for existing DBs)
  - Added `save_run()`, `finish_run()`, `get_run()` methods to `KnowledgeStore`
  - Added `run_id` indexes on `provenance` and `relationships`
- `knowledge_graph/__init__.py`:
  - Exported `IngestionRun` and `RunStatus`
- `docs/knowledge_graph/schema.md`:
  - Documented `ingestion_runs` table and `run_id` columns
- `tests/unit/test_knowledge_graph.py`:
  - Added 10 tests: model defaults, CRUD operations, run_id round-trips, migration


### v0.14.9 - 6th April 2026

- `web_scraping/bbc.py`:
  - Added `_SKIP_URL_RE` filter to skip non-article URLs (BBC Sounds podcasts) during feed parsing, before full-text enrichment
  - Overrode `_parse_feed()` to apply URL filtering
- `tests/unit/test_web_scraping.py`:
  - Added `test_bbc_skips_podcast_urls` test
- `backlog.md`:
  - Added podcast transcription pipeline as future enhancement


### v0.14.8 - 5th April 2026

- `.claude/rules/`:
  - Updated `versioning.md`: added changelog
    rotation section (30-version limit, yearly
    archives in `changelog/YYYY.md`).


### v0.14.7 - 5th April 2026

- `.claude/rules/`:
  - Updated `versioning.md`: added changelog
    rotation section (30-version limit, yearly
    archives in `changelog/YYYY.md`).


### v0.14.6 - 5th April 2026

- Rotated changelog: archived 62 old
  entries to `changelog/` yearly files.


### v0.14.5 - 5th April 2026

- `.claude/`:
  - Updated `backlog` skill (v1.4.0): tables now
    always include Priority and Effort columns.


### v0.14.4 - 5th April 2026

- `.claude/hooks/`:
  - Fixed stdin consumption: all hooks now
    capture stdin before piping to python.


### v0.14.3 - 5th April 2026

- `.claude/`:
  - Updated `backlog` skill (v1.3.0): auto-cleans
    completed items before display, shows per-section
    tables when backlog has multiple sections.
  - Updated `backlog` rule: added auto-cleanup
    section.


### v0.14.2 - 5th April 2026

- `.claude/`:
  - Updated `backlog` skill (v1.1.0): auto-cleans
    completed items when 5+ accumulate.
  - Updated `backlog` rule: added auto-cleanup
    section.


### v0.14.1 - 4th April 2026

- `.claude/`:
  - Added `hooks/block-raw-python.sh`: enforces `uv run python` over bare `python`.


### v0.14.0 - 4th April 2026

- `docs/pipeline/`:
  - Added `models.md`: pipeline data models design — stage
    contracts for `IngestionRun`, `Chunk`, `Mention`,
    `EntityProposal`, `ResolvedMention`,
    `ExtractedRelationship`, `ChunkResult`, and
    `DocumentResult`, plus ingestion run table schema.
  - Added `llm_interface.md`: LLM interface design — JSON
    response schemas for entity resolution (pass 1) and
    relationship extraction (pass 2), prompt architecture,
    token budget allocation, retry strategy, and
    `LLMProvider` ABC contract.
  - Updated `design.md`: added cross-references to
    `models.md` and `llm_interface.md`.
- `docs/knowledge_graph/`:
  - Updated `schema.md`: added `section_name` column to
    `provenance` and `relationships` tables for
    section-level queries on long-form documents.


### v0.13.0 - 4th April 2026

- `docs/pipeline/`:
  - Added `chunking.md`: document chunking design covering
    segmentation strategies, cross-chunk entity tracking,
    aggregation, provenance granularity, and cost
    mitigations for long-form documents (research reports,
    earnings transcripts, regulatory filings).
  - Updated `design.md`:
    - Replaced truncation-only "Long articles" section
      with "Long documents" referencing chunking design.
    - Added `segmentation` and `aggregation` to module
      structure.
    - Added chunking to "What this design does NOT cover"
      with cross-reference.


### v0.12.5 - 4th April 2026

- `.claude/rules/`:
  - Normalized `versioning.md` to enhanced canonical
    with detailed sub-bullet guidance.


### v0.12.4 - 4th April 2026

- `.claude/rules/`:
  - Normalized `versioning.md` to canonical template.


### v0.12.3 - 3rd April 2026

- `.claude/rules/`:
  - Normalized `committing.md` to canonical template.


### v0.12.2 - 3rd April 2026

- Removed dead `Null document_ids` check from `db_health`
  — `document_id` has a NOT NULL constraint after
  migration, so the check always returns 0


### v0.12.1 - 3rd April 2026

- Fixed `Null document_ids` showing `None` instead of `0`
  in `db_health` — `SUM(CASE)` returns NULL over empty
  result sets; split into separate `COUNT(*)` queries


### v0.12.0 - 3rd April 2026

- Added `docs/pipeline/design.md` — ingestion pipeline
  design covering architecture, design decisions, and
  trade-offs for each major concern:
  - Two-pass extraction (entities → relationships)
  - Ingestion run tracking with metadata
  - LLM provider abstraction (Ollama first)
  - Auto-create entity policy with quality controls
  - Relevant-entity windowing for context budget
  - Structured output with validation and retry
  - Provenance-based idempotency
  - Per-article error isolation
  - Module structure and dependencies


### v0.11.43 - 3rd April 2026

- `CLAUDE.md`:
  - Normalized to canonical template: added missing
    shared sections, removed low-value sections.


### v0.11.42 - 3rd April 2026

- Added `KnowledgeStore.find_entities_since()` — returns
  entities created after a given datetime, newest first;
  indexed on `created_at` for fast new-entity alerting
- Updated `schema.md` intro to reference `SQLiteStore`
  base class instead of stale `ArticleStore` pattern
- Updated `design.md` with `find_entities_since`
  documentation


### v0.11.41 - 3rd April 2026

- `docs/knowledge_graph/relationships.md`:
  - Added index composition pattern: `ASSET/equity →
    component_of → ASSET/index` with temporal bounds
  - Added delisting pattern: `ORGANIZATION/company →
    delisted_from → ORGANIZATION/exchange`
  - Added `component_of`, `delisted_from` to
    `market_structure` RELATION_KIND
  - Added `runs_on` to `product` RELATION_KIND
- Added `KnowledgeStore.find_by_name_prefix()` — case-
  insensitive prefix search with `canonical_name` index
- Added `KnowledgeStore.count_entities_by_type()` — single
  `GROUP BY` query for dashboard stats
- Updated `design.md` and `schema.md` with new query
  methods and index


### v0.11.40 - 3rd April 2026

- Performance pass (v0.11.39 review):
  - Combined data quality checks in `db_health.py` into
    a single `SUM(CASE)` query — 6 full-table scans → 1
  - Eliminated redundant `get_entity()` call in
    `merge_entities()` — constructs merged entity
    in-memory with `dataclasses.replace` instead of
    re-fetching from DB
  - Cached `results.get()` lookup in `Scraper._enrich()`
    — removed duplicate dict access per article


### v0.11.39 - 3rd April 2026

- Refactoring pass (v0.11.37 review):
  - Extracted `SQLiteStore` base class in `storage_base.py`
    — both `ArticleStore` and `KnowledgeStore` now inherit
    shared init/lifecycle logic (mkdir, connect, DDL,
    migrate, indexes, commit, close, context manager)
  - Extracted `_data_quality_count()` helper and
    `_QUALITY_CHECKS` table in `db_health.py` — five
    near-identical COUNT queries replaced with a loop
  - Replaced `source` property boilerplate in scrapers
    with class variable + `__init_subclass__` validation


### v0.11.38 - 3rd April 2026

- `.claude/`:
  - Migrated `/db-health` from command to skill (v1.0.0)
    for version tracking.


### v0.11.37 - 3rd April 2026

- Removed duplicate `spun_off` pattern from Corporate
  structure section in `relationships.md` — kept in
  Corporate actions, added cross-reference
- Added doc note for `measures` in `classification`
  RELATION_KIND explaining the semantic stretch


### v0.11.36 - 3rd April 2026

- Fixed `triggers` alias overlap — removed `triggered` from
  `causality` RELATION_KIND; `triggers` now only in
  `event_trigger`
- Added `KnowledgeStore.find_active_relationships()` — returns
  relationships where `valid_until` is unbounded or in the
  future, for current-state queries
- Updated `docs/knowledge_graph/design.md` with
  `find_active_relationships` documentation


### v0.11.35 - 3rd April 2026

- `.claude/`:
  - Migrated `/self-refinement` from command to skill
    (v1.0.0) for version tracking.


### v0.11.34 - 3rd April 2026

- Added PRODUCT relationship patterns to `relationships.md`:
  - `manufactured_by`, `approved`, `grounded`,
    `competes_with`, `runs_on`
  - New `product` RELATION_KIND with aliases
- Added IPO/listing event pattern:
  - `ORGANIZATION/company → ipo_on → ORGANIZATION/exchange`
  - Added `ipo_on` alias to `market_structure` RELATION_KIND
- Added KG design review backlog items (v0.11.33)


### v0.11.33 - 3rd April 2026

- Added scope warning to ownership/investment patterns in
  `relationships.md` — clarifies that stake sizes and
  percentages belong in external tables, not the KG


### v0.11.32 - 3rd April 2026

- `.claude/`:
  - Migrated `/improvements` from command to skill (v1.0.0)
    for version tracking.


### v0.11.31 - 3rd April 2026

- Fixed sentinel inconsistency in `_log_relationship()` —
  `valid_from` now uses `""` sentinel in
  `relationship_history` matching `relationships` table
- Fixed RELATION_KIND semantic groupings in
  `docs/knowledge_graph/relationships.md`:
  - Moved `belongs_to` from `membership` to
    `classification` (sector grouping ≠ membership)
  - Moved `spun_off`, `merged_with`, `founded` from
    `causality`/`governance` to `corporate_structure`
  - `causality` now only contains macro-signal patterns
    (`affects`, `triggered`)
  - `governance` now only contains active leadership
    (`leads`, `governs`)
- Updated `docs/knowledge_graph/schema.md` with `""`
  sentinel documentation on `valid_from` column


### v0.11.30 - 3rd April 2026

- `.claude/`:
  - Migrated `/optimize` from command to skill (v1.0.0)
    for version tracking.


### v0.11.29 - 3rd April 2026

- Fixed NULL `valid_from` in relationship PK — SQLite
  `NULL != NULL` allowed silent duplicate unbounded
  relationships. Now stores `""` sentinel instead of
  NULL; migration backfills existing rows
- Added `KnowledgeStore.get_relationships_between()` —
  fetches all relationships between two specific entities
  without Python-side filtering
- Added relationship pattern sections in
  `docs/knowledge_graph/relationships.md`:
  - Analyst coverage: `covers` pattern for
    PERSON/analyst → ASSET/equity
  - Sector events: `triggers`, `affects`, `hosts`
    patterns for TOPIC/sector_event
- Added `analyst_coverage` and `event_trigger`
  RELATION_KIND entries
- Updated `docs/knowledge_graph/design.md` with
  valid_from sentinel rationale


### v0.11.28 - 3rd April 2026

- `.claude/`:
  - Migrated `/refactor` from command to skill (v1.0.0)
    for version tracking.


### v0.11.27 - 3rd April 2026

- Added 6 RELATION_KIND entries in
  `docs/knowledge_graph/relationships.md`:
  governance, market_structure, policy, classification,
  causality, partnership — covers 11 previously unmapped
  relation_types across documented patterns
- Added PLACE/city subtype in
  `docs/knowledge_graph/subtypes.md` — financial hubs
  (Tokyo, Frankfurt, Hong Kong, Singapore) distinct from
  markets and regions
- Updated `docs/knowledge_graph/design.md` query section
  with `find_relationships_by_type` and
  `find_entities_by_status` (added in v0.11.23–v0.11.25)


