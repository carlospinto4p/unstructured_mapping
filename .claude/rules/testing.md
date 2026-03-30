# Testing guidelines

## Structure

- Unit tests live in `tests/unit/`.
- Run with `uv run pytest tests/unit -v`.
- Fast, isolated, no external services needed.

## Style

- No test classes, plain functions with `test_` prefix.
- Group tests with comment headers.
- Use `pytest` idioms (fixtures, parametrize, raises).
- Keep test files named `test_<module>.py`.

## Fixtures

- File-local if used by one file only.
- Move to `conftest.py` if shared across files.
- Prefer `tmp_path` for temporary files.

## Assertions

- One logical assertion per test.
- Plain `assert` (no unittest-style).
- Float comparisons: `abs(actual - expected) < 1e-9`.

## What to test

- Data models, pipeline stages, entity resolution logic, KG
  updates, edge cases.
- Don't test: trivial getters/setters, third-party library
  internals.
