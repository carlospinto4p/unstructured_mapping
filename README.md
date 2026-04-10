
# Unstructured Mapping

A proof-of-concept Python library for mapping well-defined knowledge-graph
entities to unstructured text.

## Overview

Given a knowledge graph (KG) with typed entities and relationships, and a
body of unstructured text, this library:

1. **Detects** entity mentions in free text.
2. **Resolves** each mention against the KG, linking it to the correct
   node.
3. **Extracts** relationships between detected entities.
4. **Updates** the KG with newly discovered entities or relationships
   (optional).

The goal is to explore and benchmark different approaches (rule-based,
embedding-based, LLM-based) for each step of the pipeline.

## Installation

```bash
pip install unstructured-mapping
```

Or for development:

```bash
uv sync --all-extras
```

## Quick Start

```python
from unstructured_mapping.knowledge_graph import (
    EntityStatus,
    KnowledgeStore,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    Pipeline,
    RuleBasedDetector,
)
from unstructured_mapping.web_scraping import BBCScraper

with KnowledgeStore() as store:
    entities = store.find_entities_by_status(
        EntityStatus.ACTIVE
    )
    pipeline = Pipeline(
        detector=RuleBasedDetector(entities),
        resolver=AliasResolver(),
        store=store,
    )
    articles = BBCScraper().fetch()
    result = pipeline.run(articles)

print(
    f"Run {result.run_id}: "
    f"{result.documents_processed} articles, "
    f"{result.provenances_saved} provenance rows"
)
```

*(API is provisional and will evolve as the PoC matures.)*

## Web Scraping

The `web_scraping` module provides a base `Scraper` interface,
concrete scrapers, and SQLite storage:

```python
from unstructured_mapping.web_scraping import (
    BBCScraper,
    ArticleStore,
)

scraper = BBCScraper()
articles = scraper.fetch()

store = ArticleStore()
new = store.save(articles)
print(f"Saved {new} new articles ({store.count()} total)")
```

Available scrapers: `BBCScraper` (RSS + full text),
`ReutersScraper` (RSS headlines),
`APScraper` (RSS + full text with `scraping` extra).

For AP full-text extraction, install optional dependencies:

```bash
pip install unstructured-mapping[scraping]
```

### CLI

```bash
# Scrape all sources (BBC + Reuters), all feeds
uv run python -m unstructured_mapping.cli.scrape

# BBC only, top stories feed
uv run python -m unstructured_mapping.cli.scrape --sources bbc --feeds default

# Show database stats
uv run python -m unstructured_mapping.cli.scrape --stats
```

## Docker Deployment

Run the scraper on a schedule using Docker. The container
automatically restarts when Docker Desktop starts.

```bash
# Build and start (scrapes every 4 hours by default)
docker compose up -d

# Check logs
docker compose logs -f scraper

# Stop
docker compose down
```

Configure via environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|---|---|---|
| `SCRAPE_INTERVAL_HOURS` | `4` | Hours between scrape cycles |
| `SCRAPE_SOURCES` | `bbc reuters` | Space-separated sources |
| `SCRAPE_FEEDS` | `all` | `default` (top stories) or `all` |
| `SCRAPE_FULL_TEXT` | `1` | Set to `0` to skip full-text extraction |

The SQLite database is persisted in `data/articles.db` via a
volume mount.

## Knowledge Graph

The `knowledge_graph` module provides the data model and SQLite
storage for mapping entities to unstructured text:

```python
from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
)

entity = Entity(
    canonical_name="Apple Inc.",
    entity_type=EntityType.ORGANIZATION,
    description="American multinational technology company.",
    aliases=("Apple", "AAPL"),
)

with KnowledgeStore() as store:
    store.save_entity(entity)
    results = store.find_by_alias("Apple")
```

Entity types: `PERSON`, `ORGANIZATION`, `PLACE`, `TOPIC`,
`PRODUCT`, `LEGISLATION`, `ASSET`, `METRIC`.
See `docs/knowledge_graph/` for rationale.

## Entity Detection (Pipeline)

The `pipeline` module provides entity detection against the
knowledge graph using Aho-Corasick trie matching:

```python
from unstructured_mapping.knowledge_graph import (
    EntityStatus,
    KnowledgeStore,
)
from unstructured_mapping.pipeline import (
    Chunk,
    RuleBasedDetector,
)

with KnowledgeStore() as store:
    entities = store.find_entities_by_status(
        EntityStatus.ACTIVE
    )

detector = RuleBasedDetector(entities)
chunk = Chunk(
    document_id="article-1",
    chunk_index=0,
    text="The Fed raised rates as Apple reported earnings.",
)

for mention in detector.detect(chunk):
    print(
        f"{mention.surface_form} "
        f"[{mention.span_start}:{mention.span_end}] "
        f"-> {mention.candidate_ids}"
    )
```

The detector builds a case-insensitive trie from entity
aliases and canonical names, then scans text in O(n) time
with word-boundary enforcement to avoid partial matches.

## Entity Resolution (Pipeline)

The `AliasResolver` resolves unambiguous mentions (single
candidate) directly, leaving ambiguous ones for a future
LLM-based resolver:

```python
from unstructured_mapping.pipeline import (
    AliasResolver,
    Chunk,
    RuleBasedDetector,
)

# Detection (from above)
detector = RuleBasedDetector(entities)
chunk = Chunk(
    document_id="article-1",
    chunk_index=0,
    text="The Fed raised rates as Apple reported earnings.",
)
mentions = detector.detect(chunk)

# Resolution
resolver = AliasResolver()
result = resolver.resolve(chunk, mentions)

for rm in result.resolved:
    print(f"{rm.surface_form} -> {rm.entity_id}")

for um in result.unresolved:
    print(f"{um.surface_form} needs LLM ({um.candidate_ids})")
```

## Pipeline Orchestration

`Pipeline` wires detection, resolution, and provenance
persistence into one call. Each invocation creates an
`IngestionRun`, processes articles in isolation (a
failure in one does not abort the run), and writes
resolved mentions to the knowledge store.

```python
from unstructured_mapping.knowledge_graph import (
    EntityStatus,
    KnowledgeStore,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    Pipeline,
    RuleBasedDetector,
)

with KnowledgeStore() as store:
    entities = store.find_entities_by_status(
        EntityStatus.ACTIVE
    )
    pipeline = Pipeline(
        detector=RuleBasedDetector(entities),
        resolver=AliasResolver(),
        store=store,
    )
    result = pipeline.run(articles)

    for article_result in result.results:
        if article_result.error:
            print(f"Failed: {article_result.error}")
            continue
        if article_result.skipped:
            continue
        unresolved = article_result.resolution.unresolved
        if unresolved:
            print(
                f"{article_result.document_id}: "
                f"{len(unresolved)} ambiguous mentions"
            )
```

Articles whose `document_id` already has provenance are
skipped by default. Pass `skip_processed=False` to the
`Pipeline` constructor to force reprocessing.
See `docs/pipeline/10_orchestration.md` for design notes.

## LLM Providers

The pipeline talks to LLM backends through the
`LLMProvider` ABC so resolvers and extractors are
backend-agnostic. `OllamaProvider` is the first
concrete implementation and is available via the
optional `llm` extras group:

```bash
pip install unstructured-mapping[llm]
```

```python
from unstructured_mapping.pipeline import OllamaProvider

provider = OllamaProvider(
    model="llama3.1:8b",
    context_window=8192,  # or omit to auto-detect
)

text = provider.generate(
    "List the named entities in: Apple reported Q3.",
    system="You extract entity mentions as JSON.",
    json_mode=True,
)
```

Providers report `model_name`, `provider_name`, and
`context_window` for run tracking and token-budget
calculations. See `docs/pipeline/03_llm_interface.md` for
the full contract, JSON schemas, and prompt
architecture.

### Prompt Construction

The `prompts` module builds the system and user prompts
for LLM entity resolution (pass 1):

```python
from unstructured_mapping.pipeline import (
    PASS1_SYSTEM_PROMPT,
    build_kg_context_block,
    build_pass1_user_prompt,
)

# Format candidate entities as numbered text blocks
kg_block = build_kg_context_block(candidates)

# Assemble the user prompt
user_prompt = build_pass1_user_prompt(
    kg_block=kg_block,
    chunk_text=chunk.text,
    prev_entities=earlier_resolved,  # for multi-chunk
)

# Send to the LLM
response = provider.generate(
    user_prompt,
    system=PASS1_SYSTEM_PROMPT,
    json_mode=True,
)
```

See `docs/pipeline/06_prompts.md` for design decisions.

### Token Budget

The budget module ensures prompts fit the model's
context window. Chunk text gets priority; KG context is
truncated by dropping the least-relevant candidates:

```python
from unstructured_mapping.pipeline import (
    PASS1_SYSTEM_PROMPT,
    compute_budget,
    fit_candidates,
)

budget = compute_budget(
    context_window=provider.context_window,
    system_prompt=PASS1_SYSTEM_PROMPT,
)

fitted, chunk_text = fit_candidates(
    candidates=candidates,
    chunk_text=chunk.text,
    flexible_budget=budget.flexible,
)
```

See `docs/pipeline/07_budget.md` for design decisions.

## Project Status

This is an early-stage proof of concept. The API, data models, and
supported strategies are all subject to change.
