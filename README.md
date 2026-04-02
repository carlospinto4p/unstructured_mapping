
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
from unstructured_mapping import Pipeline

pipeline = Pipeline(kg=my_knowledge_graph)
result = pipeline.run("Some unstructured text mentioning entities.")

for mention in result.mentions:
    print(f"{mention.text} -> {mention.entity}")
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

## Project Status

This is an early-stage proof of concept. The API, data models, and
supported strategies are all subject to change.
