# Testing Guidelines

## Style

- **No test classes.** Use plain functions with `test_` prefix.
- Use `pytest` idioms: fixtures, parametrize, `pytest.raises`.
- Keep test files named `test_<module>.py` mirroring the source.

## Fixtures

- Define fixtures in the test file when used by that file only.
- Move shared fixtures to `tests/conftest.py` when used across
  files.
- Prefer `tmp_path` (built-in) for temporary files/databases.
- Use `@pytest.fixture` without parentheses for consistency.

## Assertions

- One logical assertion per test when possible.
- Use plain `assert` — avoid `unittest`-style methods.

## Naming

- Test functions: `test_<what>_<scenario>` in snake_case.
- Fixture functions: descriptive nouns (`sample_project`,
  `mock_registry`).

## What to Test

- **Do test:** public functions, edge cases, error paths, data
  roundtrips.
- **Don't test:** private helpers directly (test through public
  API), trivial getters/setters.
