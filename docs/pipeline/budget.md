# Token Budget — Design Decisions

## Purpose

`pipeline/budget.py` manages the token budget for LLM
calls. It estimates token counts, computes how much
space is available for KG context and chunk text, and
truncates content when the budget is exceeded.

For the budget allocation strategy and default values,
see [llm_interface.md](llm_interface.md) § "Token budget".
This document covers implementation-level decisions.


## Public API

| Symbol                      | Type      | Purpose                                            |
|-----------------------------|-----------|----------------------------------------------------|
| `estimate_tokens()`         | function  | Character-based token estimator                    |
| `PromptBudget`              | dataclass | Budget breakdown (system, headroom, flexible)      |
| `compute_budget()`          | function  | Compute flexible budget from context window        |
| `fit_candidates()`          | function  | Fit candidates + chunk text into budget            |
| `DEFAULT_RESPONSE_HEADROOM` | int       | Default response headroom (800 tokens)             |


## Token estimation

### Why `ceil(chars / 4)`?

The approximation from `llm_interface.md` — 1 token per
4 characters for English text. It overestimates slightly
for structured text and underestimates for non-Latin
scripts. Both are acceptable because the response
headroom (500-1000 tokens) absorbs the error.

### Optional tokenizer callback

All functions that count tokens accept an optional
`tokenizer: Callable[[str], int]` parameter. When
provided, it replaces the character-based estimator.
This allows the orchestrator to pass in a model-specific
tokenizer (e.g. from the `LLMProvider`) without the
budget module depending on any tokenizer library.


## Candidate truncation

### Ranking by alias match count

When KG context exceeds its allocation, candidates are
ranked by how many times their aliases (and canonical
name) appear in the chunk text. Candidates with more
matches are more likely to be relevant to the text and
are kept first.

### Why case-insensitive substring search?

The alias match counter uses simple case-insensitive
`str.find()`, not the trie-based word-boundary scanner
from `detection.py`. This is intentional: the counter
is a rough relevance signal for ranking, not a precise
detection pass. The trie is optimised for finding exact
mention spans; the counter just needs to answer "how
relevant is this candidate to this chunk?" quickly.

### Incremental block sizing

When truncating, candidates are added one at a time
(most-matched first) and the KG context block is
rebuilt with `build_kg_context_block()` to check if it
fits. This is slightly wasteful (O(n^2) string builds)
but correct — the block includes headers and formatting
that affect the token count. The candidate count is
typically 20-50, so the cost is negligible.


## Chunk text truncation

### Paragraph-level, not character-level

When chunk text alone exceeds the flexible budget (a
safety net — segmentation should prevent this), the
text is truncated at paragraph boundaries (double
newlines). This preserves sentence integrity. Only if
the first paragraph itself exceeds the budget does a
hard character truncation occur.

### Why truncate to leading paragraphs?

News articles use inverted-pyramid structure — key
information is front-loaded. Keeping leading paragraphs
preserves the most entity-dense content. For long-form
documents, the segmentation stage should prevent this
scenario entirely by producing budget-respecting chunks.


## Default response headroom

`DEFAULT_RESPONSE_HEADROOM` is 800 tokens. This sits
between the 600 (Ollama 4K) and 1000 (API 32K+)
defaults from `llm_interface.md`. The orchestrator
can override this per provider when computing the
budget.


## What was deferred

- **Per-entity token estimates** — currently the full
  KG block is rebuilt on each candidate addition. Caching
  per-entity token costs would avoid the O(n^2) rebuild,
  but the candidate count is small enough that this is
  not a bottleneck.
- **Running entity header budget** — the header is
  compact and unlikely to exhaust the budget. If
  multi-chunk documents produce very large headers,
  a separate budget check may be needed.
