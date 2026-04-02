# Post-change workflow (MANDATORY)

After every change:

1. Fix tests if needed.
2. Update version and `changelog.md` (follow `versioning.md`).
3. Update `README.md` if the change affects public API or usage.
4. Update `CLAUDE.md` if rules changed.
5. Sync environment: `uv sync --all-extras` then
   `uv pip install -e ".[dev]"`.
6. Commit with a descriptive message (conventional commit style).
7. Push to remote with `git push`.

## Commit message format

```
<type>: <description>

[optional body]
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

## Rules

- Always include `uv.lock` in commits.
- One command per Bash call (no `&&` chains).
- 72-character subject line max.
- Imperative mood.
- Doc-only changes (`docs/`, `backlog.md`) still require a
  patch version bump, changelog entry, and automatic commit.
