
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

The `web_scraping` module provides a base `Scraper` interface and
concrete implementations for fetching unstructured text from news
sources:

```python
from unstructured_mapping.web_scraping import ReutersScraper

scraper = ReutersScraper()
articles = scraper.fetch()

for article in articles:
    print(f"{article.title} ({article.source})")
```

Available scrapers: `ReutersScraper` (RSS-based).

## Project Status

This is an early-stage proof of concept. The API, data models, and
supported strategies are all subject to change.
