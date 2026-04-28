## Changelog

### v0.58.9 - 28th April 2026

- Refactored module naming conventions (leading-underscore for internal concrete implementations):
  - `web_scraping/`: renamed `ap.py`, `bbc.py`, `reuters.py` → `_ap.py`, `_bbc.py`, `_reuters.py`; updated `web_scraping/__init__.py` and test patch paths.
  - `pipeline/segmentation/`: renamed `filing.py`, `news.py`, `research.py`, `transcript.py` → `_filing.py`, `_news.py`, `_research.py`, `_transcript.py`; updated `segmentation/__init__.py`.


### v0.58.8 - 28th April 2026

- Refactored `src/unstructured_mapping/pipeline/`:
  - Extracted `pipeline/llm/` subpackage — moved all LLM-related modules out of the flat `pipeline/` namespace:
    - `llm_provider.py` → `llm/provider.py`
    - `llm_claude.py` → `llm/claude.py`
    - `llm_ollama.py` → `llm/ollama.py`
    - `llm_fallback.py` → `llm/fallback.py`
    - `llm_parsers.py` → `llm/parsers.py`
    - `_llm_retry.py` → `llm/_retry.py`
    - `prompts.py` → `llm/prompts.py`
    - `budget.py` → `llm/budget.py`
    - `_optional_import.py` → `llm/_optional_import.py`
  - Updated all internal imports in `resolution.py`, `extraction.py`, `cold_start.py`, and `pipeline/__init__.py`.
  - Updated test imports in `tests/unit/` to reflect new module paths.
  - Fixed Python 2-style `except A, B:` syntax → `except (A, B):` in `llm/fallback.py`.


### v0.58.7 - 27th April 2026

- Refactored `tests/unit/`:
  - Moved `seed_file`, `seed_dir`, `articles_db`, and `kg_db` fixtures from inline test files into `tests/unit/conftest.py` so a new field on `Entity` only needs one update.
  - `log_import_summary` already shared across all seed loaders — no changes needed.
  - Fixed 81-char line in `cli/ingest.py`: wrapped log string literal to fit 78-char limit.


### v0.58.6 - 27th April 2026

- Refactored `pipeline/orchestrator.py`:
  - Added `pipeline/_article_processor.py`: `ArticleProcessor` class — carries all per-article stages (detection, resolution, extraction, persistence) and `_MetricsAccumulator`/`ArticleResult` dataclasses. Metrics are passed as a parameter so one accumulator spans a full batch.
  - Slimmed `Pipeline` to batch/run-bookkeeping only; delegates per-article work to `ArticleProcessor`. `ArticleResult` is re-exported from `orchestrator.py` for backward compatibility.
  - Updated `tests/unit/test_cli_ingest.py`: internal-wiring assertions now reach through `pipeline._processor`.
- Refactored `knowledge_graph/_entity_helpers.py`:
  - Converted `EntityHelpersMixin` to module-level functions taking a `conn` parameter: `rows_to_entities`, `find_entities_where`, `sync_aliases`, `log_entity`, `load_aliases`, `load_aliases_batch`, `redirect_entity_references`.
  - Removed the mixin inheritance pyramid; each sub-mixin (`_entity_crud_mixin`, `_entity_search_mixin`, `_entity_merge_mixin`, `_entity_history_mixin`, `_provenance_mixin`) now calls the helpers directly with `self._conn`.
  - `TYPE_CHECKING` stubs for cross-mixin calls (`get_entity`, `save_entity`) moved to the mixins that actually need them.


### v0.58.5 - 27th April 2026

- Added `cli/_runner.py`: `run_cli_with_kg()` — shared startup helper that
  centralises `setup_logging`, arg parsing, optional arg validation, and the
  `open_kg_store` context manager so CLI `main()` functions stop repeating
  the same three lines.
- Added `cli/_json_output.py`:
  - `emit_json()`: serialises a payload as indented JSON to stdout or a file
    (`datetime`/`UUID`/`Path` coerced via `default=str`).
  - `emit_jsonl()`: serialises rows as newline-delimited JSON to stdout or a
    file; returns row count.
- Migrated to `run_cli_with_kg()`:
  - `cli/run_report.py`
  - `cli/run_diff.py`
  - `cli/audit_provenance.py`
  - `cli/audit_aliases.py`
  - `cli/subgraph.py`
  - `cli/validate_snapshot.py`
  - `cli/export.py`
- Migrated to `emit_json()` / `emit_jsonl()`:
  - `cli/subgraph.py`: replaced inline `json.dumps` + stdout/file write.
  - `cli/preview.py`: replaced inline `json.dumps` + stdout/file write.
  - `cli/export.py`: replaced private `_write_jsonl()` with `emit_jsonl()`.


### v0.58.4 - 26th April 2026

- Updated `.claude/rules/committing.md`: remove SKIP workaround, ruff now runs via `uv run ruff` in all projects.



### v0.58.3 - 26th April 2026

- Updated `.claude/rules/committing.md`: add Windows `SKIP=ruff-format,ruff-fix` pattern for pre-commit hook failures when ruff is not in PATH.



### v0.58.2 - 25th April 2026

- Refactored `cli/validate_snapshot.py` (501 lines) by lifting KG-quality primitives into a new `knowledge_graph/snapshot.py`:
  - Moved: `Snapshot`, `CollisionSummary`, `CheckResult`, `capture_snapshot`, `compare_snapshots`, `load_snapshot`, `write_snapshot`, `DEFAULT_TOP_K_COLLISIONS`, `SCHEMA_VERSION`, plus the small private helpers `_count_by_type_subtype`, `_scalar_count`, `_format_counts_diff`.
  - Why: snapshot capture and comparison are KG-domain concerns. Hosting them in a CLI module forced future tooling (drift checks between two live KGs, dashboards, LLM context blocks) to depend on a CLI surface; they now live next to `validation.py` and `storage.py`.
  - CLI shrank from 501 → 184 lines and only owns argparse plumbing + dispatch.
- Preserved back-compat: `cli/validate_snapshot.py` re-exports every public name so callers and tests importing from it keep working unchanged.


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


