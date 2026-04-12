# Cold-start entity discovery

## Problem

The normal pipeline runs detection → resolution →
extraction. Detection is driven by the KG: it matches
aliases of entities that already exist in the graph. When
the KG is empty or very small, detection finds nothing,
the LLM is never called, and the pipeline produces no
output. This chicken-and-egg problem blocks the
steady-state pipeline from ever populating a fresh KG.

The curated seed
(`data/seed/financial_entities.json`,
see `12_kg_population.md`) solves most of this: running
`uv run python -m unstructured_mapping.cli.seed` gives
the KG enough starter mass for detection to fire.
Cold-start is the complementary mechanism for cases where
the seed is missing, too narrow, or simply not yet
loaded.

## What cold-start does

In cold-start mode the pipeline **bypasses detection and
resolution entirely** and asks the LLM to propose
entities directly from the raw article text. Every
discovered entity is persisted with
`reason="proposed by LLM"`, identically to how normal
pass-1 proposals are stored. After a cold-start run the
KG holds real entities that subsequent normal runs can
detect and reason over.

## Design

- **Reuses the pass 1 prompt and parser.** The pass 1
  JSON schema already supports entity proposals via the
  `new_entity` field. Cold-start sends the pass 1 prompt
  with an **empty candidates block**, so every returned
  entity is necessarily a proposal. No new prompt, no new
  parser, no new validation rules.
- **Fails loudly on hallucinated IDs.** If the LLM
  ignores the empty candidate set and returns a concrete
  `entity_id`, the existing hallucination check rejects
  it. Retry-with-feedback is identical to pass 1.
- **Skips relationship extraction.** Cold-start focuses
  on entity discovery only. Relationships are extracted
  on the **next** pipeline pass, once the entities exist
  and normal detection can find them. This keeps the
  cold-start code path tiny and avoids synthesising
  `ResolvedMention` objects for entities that were just
  created.

## Usage

```python
from unstructured_mapping.pipeline import (
    AliasResolver,
    ColdStartEntityDiscoverer,
    NoopDetector,
    OllamaProvider,
    Pipeline,
)

provider = OllamaProvider(model="llama3.1:8b")

pipeline = Pipeline(
    detector=NoopDetector(),
    resolver=AliasResolver(),
    store=store,
    cold_start_discoverer=ColdStartEntityDiscoverer(
        provider
    ),
)

result = pipeline.run(articles)
print(result.proposals_saved, "new entities")
```

`NoopDetector` is a small convenience detector that
always returns zero mentions; its job is to document
intent. The orchestrator also ignores the detector
entirely when a cold-start discoverer is configured, so
passing `RuleBasedDetector([])` works too — `NoopDetector`
is just clearer.

## Recommended workflow

1. Seed the KG with `uv run python -m unstructured_mapping.cli.seed`.
2. (Optional) Run cold-start over a batch of articles to
   expand coverage beyond the curated seed.
3. Switch to the normal pipeline
   (`RuleBasedDetector` + `AliasResolver` + optional
   `LLMEntityResolver` and `LLMRelationshipExtractor`)
   for steady-state ingestion. Normal runs will both
   detect the cold-start-discovered entities and extract
   relationships involving them.

## Deferred

- **In-run relationship extraction.** Possible by
  synthesising `ResolvedMention` objects from freshly
  saved proposals and passing them to the extractor, but
  excluded from the MVP to keep the code path small.
- **Cold-start budgets.** Long articles are truncated to
  the provider's flexible context budget; smarter
  chunking could process full long-form content in
  pieces (see `09_chunking.md`).
