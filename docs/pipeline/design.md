# Ingestion Pipeline — Design Decisions

## Purpose

The ingestion pipeline processes articles from the
`ArticleStore` and populates the `KnowledgeStore` with
entities, relationships, and provenance records. It is the
bridge between unstructured news text and the structured
knowledge graph.


## Architecture overview

```
Article (from ArticleStore)
    │
    ▼
┌──────────────┐
│  Detection   │  Find entity mentions in text
│  (rule-based │  using alias trie matching
│   + LLM)     │  against the KG
└──────┬───────┘
       │ Mention(text, span, context)
       ▼
┌──────────────┐
│  Resolution  │  Resolve mentions to KG entities
│  (alias →    │  or flag as new candidates
│   LLM disamb)│
└──────┬───────┘
       │ ResolvedMention(entity_id, mention, confidence)
       ▼
┌──────────────┐
│  Extraction  │  Extract relationships between
│  (LLM)       │  resolved entities from article text
└──────┬───────┘
       │ Relationship(source, target, type, ...)
       ▼
┌──────────────┐
│  Persistence │  Write provenance, entities, and
│              │  relationships to KnowledgeStore
└──────────────┘
```

Each stage has an ABC so implementations can be swapped
(rule-based → LLM, Ollama → API provider, etc.).


## Ingestion run tracking

### Why

Financial workflows require auditability: "which model
produced this entity?", "when was this article processed?",
"what changed between yesterday's run and today's?".
Without run metadata, the KG is a black box — you can't
reproduce results, debug bad entities, or compare model
versions.

### What is tracked

Each pipeline execution creates an **ingestion run** record:

| Field            | Type     | Purpose                          |
|------------------|----------|----------------------------------|
| run_id           | TEXT PK  | UUID hex, auto-generated         |
| started_at       | TEXT     | When the run began (UTC ISO)     |
| finished_at      | TEXT     | When the run ended               |
| status           | TEXT     | running, completed, failed       |
| model_name       | TEXT     | e.g. "llama3.1:8b", "mistral"   |
| model_provider   | TEXT     | e.g. "ollama", "anthropic"       |
| model_params     | TEXT     | JSON: temperature, context, etc. |
| articles_total   | INTEGER  | Articles submitted for ingestion |
| articles_ok      | INTEGER  | Articles successfully processed  |
| articles_failed  | INTEGER  | Articles that errored            |
| entities_created | INTEGER  | New entities added to the KG     |
| entities_resolved| INTEGER  | Mentions linked to existing ents |
| relationships_extracted | INTEGER | Relationships discovered   |
| config           | TEXT     | JSON: pipeline config snapshot   |
| error            | TEXT     | Error message if status=failed   |

This table lives in the KG database (same SQLite file)
because runs are tightly coupled to KG mutations.

### Linking runs to records

- **Provenance**: already has `detected_at` — sufficient
  to correlate with run timestamps. Adding a `run_id` FK
  would be cleaner but couples provenance to the pipeline
  module. Deferred: use timestamp-based correlation for
  now; add `run_id` FK if the need becomes concrete.

- **Relationships**: already has `discovered_at` and
  `document_id`. Same rationale — timestamp correlation
  suffices initially.

- **Entities**: new entities created by the pipeline get
  `created_at` set to the run's timestamp. The run record
  captures aggregate counts.

### Why not a separate database?

The run table is small (one row per execution) and its
queries always join against KG data ("which run created
this entity?"). A separate database would require
cross-DB joins or application-level correlation.


## LLM provider abstraction

### Interface

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Send a prompt and return the response text."""

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for tracking."""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g. 'ollama')."""
```

### Why an ABC?

- **Swap providers** without touching pipeline code.
  Start with Ollama for local development, switch to an
  API provider (Anthropic, OpenAI) for production or
  higher-quality extraction.
- **Testing**: mock the provider in unit tests to test
  pipeline logic without running a model.
- **Tracking**: `model_name()` and `provider_name()` feed
  directly into the ingestion run metadata.

### Ollama implementation

Uses the `ollama` Python package. Requires a running
Ollama server (`ollama serve`).

Configuration:
- `model`: which model to use (default: "llama3.1:8b")
- `base_url`: Ollama server URL (default: localhost:11434)
- `temperature`: 0.0 for deterministic extraction
- `num_ctx`: context window size (model-dependent)

### Deferred: API providers

Anthropic and OpenAI implementations are straightforward
but add API key management, rate limiting, and cost
tracking. Defer until local models hit a quality ceiling.


## Entity creation policy

### The problem

When the LLM finds "Acme Corp" in an article and it does
not exist in the KG, the pipeline must decide: create a
new entity, skip it, or flag it for review.

### Chosen approach: auto-create with review marker

New entities are created automatically with:
- `status = ACTIVE` (usable immediately)
- `description` generated by the LLM from article context
- `created_at` set to the run timestamp
- A provenance record linking to the originating article

**Why auto-create**: the KG must grow from ingestion —
option (c) "skip unknowns" means the graph only contains
manually seeded entities, which defeats the purpose. A
quant researcher discovering a new company in the news
needs it in the KG for co-mention queries to work.

**Quality control**: instead of a separate approval
workflow (which adds operational complexity), quality is
controlled by:

1. **LLM prompt design** — the prompt instructs the LLM
   to only extract entities that are clearly named and
   distinguishable, not vague references.
2. **Validation rules** — `KG validation` (backlog item)
   catches duplicates via alias collision detection,
   temporal inconsistencies, and type constraint
   violations before persistence.
3. **Audit trail** — every entity has `created_at` and
   provenance linking to the article and run. Bad entities
   can be found and reverted using the existing history
   system.

### Deferred: confidence thresholds

Local models don't produce calibrated confidence scores.
If we move to API models with logprobs, we could add a
creation threshold ("only create entities the model is
>90% confident about"). Not worth building until then.


## Single-pass vs multi-pass extraction

### Chosen approach: two-pass

1. **Pass 1: Entity detection + resolution** — extract
   entity mentions from the article and resolve them
   against the KG (or create new entities).

2. **Pass 2: Relationship extraction** — given the
   resolved entities and the article text, extract
   relationships between them.

### Why two-pass?

- **Reliability**: local models produce better results
  when the task is focused. Asking for entities AND
  relationships in one prompt leads to more hallucination
  and structural errors.
- **Reusability**: entity detection can run independently
  (e.g. for co-mention analysis without relationship
  extraction).
- **Debuggability**: when extraction fails, you know which
  stage failed and can inspect the intermediate output.

### Why not three-pass (detect → resolve → extract)?

Detection and resolution are tightly coupled — the LLM
needs KG context (descriptions, aliases) to both find
and resolve entities. Splitting them would require the
detection pass to output unresolved mentions, then a
second LLM call to resolve. This doubles the cost for
marginal benefit. Instead, the first pass does both:
"find entities in this text and match them to these
known entities (or identify new ones)."


## Prompt context budget

### The constraint

Local models (Ollama) typically have 4K-8K context
windows. The prompt must fit:
- System instructions (~500 tokens)
- Article text (variable, 200-2000+ tokens)
- KG context: candidate entity descriptions and aliases
  (variable, depends on KG size)
- Response format instructions (~200 tokens)

### Strategy: relevant-entity windowing

Don't send the entire KG. For each article:

1. **Alias pre-scan**: run a fast text scan (not LLM)
   to find potential alias matches in the article text.
   This is the rule-based detection from the backlog.
2. **Candidate set**: collect entities whose aliases
   matched, plus their descriptions. This is the
   "relevant window" of the KG.
3. **Budget check**: if the candidate set exceeds the
   token budget, rank by alias match count and truncate.
4. **LLM call**: send article + candidate entities to the
   LLM for resolution and new-entity detection.

This keeps the prompt compact — typically 20-50 candidate
entities, not thousands.

### Fallback for long articles

If the article itself exceeds the budget (rare for news),
truncate to the first N paragraphs. News articles front-
load the key information (inverted pyramid structure).


## Structured output

### The problem

Local models are less reliable at producing structured
JSON than API models. Malformed responses waste compute
and block the pipeline.

### Strategy: JSON mode + validation + retry

1. **JSON mode**: Ollama supports `format="json"` which
   constrains output to valid JSON. Use it.
2. **Schema validation**: parse the response against a
   Pydantic model (or dataclass) that defines the expected
   structure. Reject responses that don't match.
3. **Retry with error feedback**: on parse failure, retry
   once with the error message appended to the prompt
   ("your previous response was invalid JSON: {error}").
   Max 2 attempts per article.
4. **Graceful degradation**: if both attempts fail, log
   the failure to the ingestion run and skip the article.
   Don't crash the pipeline.


## Already-processed tracking

### The problem

Re-running the pipeline should be idempotent — articles
already processed should not be re-ingested (unless
explicitly requested for reprocessing).

### Chosen approach: provenance-based detection

An article is "processed" if it has at least one
provenance record in the KG. Before processing, the
pipeline queries:

```sql
SELECT DISTINCT document_id FROM provenance
```

Articles whose `document_id` appears in this set are
skipped.

### Why not a separate `processed_articles` table?

- Provenance is the source of truth — if provenance
  exists, the article was processed.
- A separate table could drift out of sync with
  provenance (e.g. after a revert or manual deletion).
- The query is fast with the existing `document_id` index
  on provenance.

### Reprocessing

To reprocess an article (e.g. with a better model), delete
its provenance records first, then re-run the pipeline.
This is an explicit, auditable action — not something the
pipeline does automatically.


## Error handling

### Per-article isolation

Each article is processed independently. If one fails
(LLM error, parse failure, validation error), the pipeline:
- Logs the error with article `document_id` and stage
- Increments `articles_failed` on the run record
- Continues to the next article

The run completes with `status = "completed"` even if some
articles failed (partial success). `status = "failed"` is
reserved for pipeline-level errors (DB connection lost,
Ollama server unreachable).

### LLM-specific errors

- **Connection refused**: fail the entire run (Ollama not
  running).
- **Timeout**: retry once, then skip the article.
- **Malformed response**: retry with error feedback (see
  Structured output above).
- **Empty response**: skip the article, log as failed.


## Module structure

```
src/unstructured_mapping/pipeline/
    __init__.py
    models.py          # IngestionRun, Mention, etc.
    detection.py       # EntityDetector ABC + RuleBasedDetector
    resolution.py      # EntityResolver ABC + AliasResolver
    extraction.py      # RelationshipExtractor ABC
    llm_provider.py    # LLMProvider ABC + OllamaProvider
    orchestrator.py    # Pipeline class wiring stages
    prompts.py         # Prompt templates for LLM calls
    storage.py         # IngestionRunStore (extends SQLiteStore)
```

This mirrors the `knowledge_graph/` and `web_scraping/`
module structure: models, storage, and domain logic
separated into focused files.


## Dependencies

New dependencies required:
- `ollama` — Python client for Ollama API

Added as an optional dependency group (`[pipeline]`) so
the base library stays lightweight. Users who only need
scraping or KG storage don't pull in LLM dependencies.


## What this design does NOT cover

- **Embedding-based detection**: deferred. The rule-based
  alias scan + LLM resolution is the baseline. Embeddings
  can be added later as an alternative detector.
- **Batch/parallel processing**: articles are processed
  sequentially. Parallelism adds complexity (concurrent
  KG writes, connection pooling) without benefit at the
  current scale.
- **Streaming**: the pipeline processes a batch of
  articles per run, not a real-time stream. The scheduler
  (`cli/scheduler.py`) handles periodic execution.
- **Prompt tuning**: prompt templates are a starting point.
  Expect iteration as we test with real articles and
  different models.
