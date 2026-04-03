# Ingestion Pipeline — Design Decisions

## Purpose

The ingestion pipeline processes articles from the
`ArticleStore` and populates the `KnowledgeStore` with
entities, relationships, and provenance records. It is the
bridge between unstructured news text and the structured
knowledge graph.


## Architecture overview

The pipeline processes each article through four stages:

1. **Detection** — find entity mentions in text using
   rule-based alias matching against the KG.
2. **Resolution** — resolve mentions to existing KG
   entities, or identify new entity candidates.
3. **Extraction** — extract relationships between
   resolved entities from the article text.
4. **Persistence** — write provenance, new entities, and
   relationships to the KnowledgeStore.

Each stage has an ABC so implementations can be swapped
(rule-based vs LLM, local vs API provider, etc.).


## Ingestion run tracking

### Why

Financial workflows require auditability: "which model
produced this entity?", "when was this article processed?",
"what changed between yesterday's run and today's?".
Without run metadata, the KG is a black box — you can't
reproduce results, debug bad entities, or compare model
versions.

### What is tracked

Each pipeline execution creates an **ingestion run** record
with fields for timing (start/end), status (running,
completed, failed), model identity (name, provider,
parameters), article counts (total, succeeded, failed),
KG mutation counts (entities created, entities resolved,
relationships extracted), and a config snapshot.

This table lives in the KG database (same SQLite file)
because runs are tightly coupled to KG mutations. A
separate database would require cross-DB joins or
application-level correlation.

### Linking runs to records

Provenance records have `detected_at` and relationships
have `discovered_at`, which correlate with the run's
timestamp range. Adding explicit `run_id` FKs would be
cleaner but couples provenance to the pipeline module —
deferred until the need becomes concrete. New entities
get `created_at` set to the run's timestamp.


## LLM provider abstraction

### Why an abstraction layer?

The pipeline needs to call an LLM for entity resolution
and relationship extraction. The specific model and
provider will change over time — local models for
development, API providers for production, different
model sizes for cost/quality tradeoffs. An abstraction
decouples the pipeline from any specific provider:

- **Swappable**: switch from Ollama to an API provider
  without touching pipeline code.
- **Testable**: mock the provider in unit tests without
  running a model.
- **Trackable**: the provider reports its model name and
  provider identity, which feeds into run metadata.

### Provider options considered

| Provider  | Pros                              | Cons                          |
|-----------|-----------------------------------|-------------------------------|
| Ollama    | Free, local, no API keys, fast    | Smaller models, less accurate |
|           | iteration, full data privacy      |                               |
| API (e.g. | Higher quality, larger context    | Cost per call, API key mgmt,  |
| Anthropic,| windows, better structured output | rate limits, data leaves local |
| OpenAI)   |                                   |                               |

### Chosen approach: Ollama first

Start with Ollama for local development. It avoids cost,
latency, and API key management while iterating on
prompts and pipeline logic. API providers can be added
later if local models hit a quality ceiling.

### Deferred: API providers

Adding Anthropic or OpenAI implementations is
straightforward but introduces API key management, rate
limiting, and cost tracking — operational concerns that
add complexity without helping the core pipeline design.


## Entity creation policy

### The problem

When the LLM identifies an entity in an article that
does not exist in the KG, the pipeline must decide what
to do with it.

### Options considered

| Option          | Pros                         | Cons                          |
|-----------------|------------------------------|-------------------------------|
| Auto-create     | KG grows from ingestion,     | Risk of low-quality or        |
|                 | new entities available for   | hallucinated entities         |
|                 | co-mention queries instantly |                               |
| Flag for review | Human quality gate           | Operational overhead, delays  |
|                 |                              | KG growth, bottleneck         |
| Skip unknowns   | No risk of bad entities      | KG never grows from text,    |
|                 |                              | only from manual seeding      |

### Chosen approach: auto-create with quality controls

New entities are created automatically. The KG must grow
from ingestion — if it only contains manually seeded
entities, it cannot discover new companies, people, or
topics that emerge in the news.

Quality is controlled through three mechanisms:

1. **Prompt design** — the LLM is instructed to only
   extract entities that are clearly named and
   distinguishable, not vague references.
2. **Validation rules** — alias collision detection,
   temporal consistency checks, and type constraints
   catch duplicates and malformed entities before
   persistence.
3. **Audit trail** — every entity has `created_at` and
   provenance linking to the originating article and run.
   Bad entities can be found and reverted using the
   existing history system.

### Deferred: confidence thresholds

Local models don't produce calibrated confidence scores.
If we move to API models with logprobs, a creation
threshold could filter low-confidence extractions.


## Single-pass vs multi-pass extraction

### Options considered

| Approach    | Pros                          | Cons                          |
|-------------|-------------------------------|-------------------------------|
| Single-pass | One LLM call per article,     | More hallucination, harder to |
|             | lower cost                    | debug, structural errors      |
| Two-pass    | Focused tasks, better output  | Doubles LLM cost per article  |
|             | quality, independently usable |                               |
| Three-pass  | Maximum separation of         | Triples cost, detection needs |
| (detect →   | concerns                      | KG context anyway, marginal   |
| resolve →   |                               | benefit over two-pass         |
| extract)    |                               |                               |

### Chosen approach: two-pass

1. **Pass 1: Entity detection + resolution** — extract
   entity mentions from the article and resolve them
   against the KG (or create new entities).
2. **Pass 2: Relationship extraction** — given the
   resolved entities and the article text, extract
   relationships between them.

Detection and resolution are combined in one pass because
the LLM needs KG context (descriptions, aliases) to both
find and resolve entities. Splitting them would require
the detection pass to output unresolved mentions, then a
second call to resolve — doubling cost for marginal
benefit.

Two-pass is preferred over single-pass because local
models produce better results when the task is focused,
and each stage can be debugged and tested independently.


## Prompt context budget

### The constraint

Local models typically have 4K-8K context windows. The
prompt must fit system instructions, article text, KG
context (candidate entity descriptions and aliases), and
response format instructions.

### Strategy: relevant-entity windowing

Instead of sending the entire KG (which could be
thousands of entities), the pipeline narrows the context
to relevant candidates:

1. **Alias pre-scan** — a fast text scan (not LLM) finds
   potential alias matches in the article text. This is
   the rule-based detection stage.
2. **Candidate set** — entities whose aliases matched are
   collected with their descriptions. This is the
   "relevant window" of the KG.
3. **Budget check** — if the candidate set exceeds the
   token budget, candidates are ranked by match count and
   truncated.
4. **LLM call** — the article plus candidate entities are
   sent for resolution and new-entity detection.

This keeps prompts compact — typically 20-50 candidate
entities, not thousands.

### Long articles

If the article itself exceeds the budget, it is truncated
to the leading paragraphs. News articles front-load key
information (inverted pyramid structure), so truncation
loses detail but not the core signal.


## Structured output

### The problem

Local models are less reliable at producing structured
JSON than API models. Malformed responses waste compute
and block the pipeline.

### Strategy: constrained output + validation + retry

1. **JSON mode** — Ollama supports constraining output to
   valid JSON. This eliminates most parse errors.
2. **Schema validation** — responses are validated against
   the expected structure. Responses that don't match are
   rejected.
3. **Retry with error feedback** — on validation failure,
   one retry is attempted with the error message included
   in the prompt. Maximum two attempts per article.
4. **Graceful degradation** — if both attempts fail, the
   article is logged as failed and skipped. The pipeline
   does not crash.


## Already-processed tracking

### The problem

Re-running the pipeline should be idempotent — articles
already processed should not be re-ingested (unless
explicitly requested).

### Options considered

| Option              | Pros                    | Cons                      |
|---------------------|-------------------------|---------------------------|
| Provenance-based    | Source of truth, no new | Must query provenance     |
| (check if article   | table, can't drift out | before each run           |
| has provenance)     | of sync                |                           |
| Separate tracking   | Fast lookup, explicit  | Can drift out of sync     |
| table               | "processed" flag       | with provenance after     |
|                     |                        | reverts or deletions      |

### Chosen approach: provenance-based detection

An article is "processed" if it has at least one
provenance record in the KG. The pipeline queries existing
provenance `document_id` values and skips articles that
appear in this set. The existing `document_id` index on
provenance makes this fast.

### Reprocessing

To reprocess an article (e.g. with a better model), its
provenance records are deleted first, then the pipeline
is re-run. This is an explicit, auditable action.


## Error handling

### Per-article isolation

Each article is processed independently. If one fails
(LLM error, parse failure, validation error), the
pipeline logs the error, increments the failure count on
the run record, and continues to the next article.

A run completes with `status = "completed"` even if some
articles failed (partial success). `status = "failed"` is
reserved for pipeline-level errors (database connection
lost, LLM server unreachable).

### LLM-specific errors

- **Server unreachable**: fail the entire run.
- **Timeout**: retry once, then skip the article.
- **Malformed response**: retry with error feedback
  (see Structured output above).
- **Empty response**: skip the article, log as failed.


## Module structure

The pipeline lives in its own top-level package
(`pipeline/`) mirroring the `knowledge_graph/` and
`web_scraping/` structure: models, storage, and domain
logic in separate focused files. Key modules:

- **models** — data classes for ingestion runs, mentions,
  and intermediate pipeline state.
- **detection** — entity detector ABC and rule-based
  implementation.
- **resolution** — entity resolver ABC and alias-based
  implementation.
- **extraction** — relationship extractor ABC.
- **llm_provider** — LLM provider ABC and Ollama
  implementation.
- **orchestrator** — pipeline class wiring the stages.
- **prompts** — prompt templates for LLM calls.
- **storage** — ingestion run persistence.


## Dependencies

The `ollama` Python package is the only new dependency.
It is added as an optional dependency group so the base
library stays lightweight — users who only need scraping
or KG storage don't pull in LLM dependencies.


## What this design does NOT cover

- **Embedding-based detection** — the rule-based alias
  scan + LLM resolution is the baseline. Embeddings can
  be added later as an alternative detector.
- **Batch/parallel processing** — articles are processed
  sequentially. Parallelism adds complexity without
  benefit at the current scale.
- **Streaming** — the pipeline processes a batch of
  articles per run, not a real-time stream.
- **Prompt tuning** — prompt templates are a starting
  point. Expect iteration as we test with real articles
  and different models.
