---
name: db-health
version: 1.0.0
description: >-
  Run db_health CLI and highlight any issues found.
---

Run `uv run python -m unstructured_mapping.cli.db_health` and present the output to the user. If any issues are found (empty bodies, missing dates, gaps in daily coverage, stale data), highlight them and suggest next steps.
