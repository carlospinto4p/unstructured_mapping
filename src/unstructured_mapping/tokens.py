"""Shared token-estimation constants.

The ``ceil(chars / 4)`` approximation is used in two places that
cannot share a code path without creating a circular dependency:

- :mod:`.pipeline.budget` — enforces context-window budgets when
  constructing LLM prompts.
- :mod:`.knowledge_graph._audit_mixin` — scores provenance snippet
  length so short contexts are flagged by audit queries.

Both previously kept a local copy of the constant with cross-
references in comments. Centralising it here eliminates the drift
risk while keeping the KG layer free of a reverse dependency on
``pipeline``.
"""

#: Characters per token for the budget approximation. Conservative
#: default; providers and scripts differ, so the value is close but
#: not exact. Response headroom elsewhere absorbs the estimation
#: error.
_CHARS_PER_TOKEN: int = 4
