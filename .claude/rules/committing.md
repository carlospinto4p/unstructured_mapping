# Committing Guidelines

## Post-Change Workflow

**IMPORTANT**: After completing any task that involves code changes, ALWAYS follow this workflow:

1. **Run tests**: Execute `uv run pytest tests/unit -v` and ensure all tests pass
2. **Update tests if needed**: If the changes require test updates, fix them before committing
3. **Update version and changelog**: Follow `versioning.md` rules. Include guideline and tooling changes (`.claude/**`, `CLAUDE.md`) in the changelog too — **any** change under `.claude/` counts (rules, skills, commands, hooks, `settings.json`, etc.).
4. **Update README.md if needed**: When changes affect user-facing functionality:
   - New methods or classes: add usage examples
   - Changed method signatures or behavior: update existing examples
   - New configuration options: document them
5. **Update CLAUDE.md if needed**: When rules change or new important patterns emerge
6. **Sync lock file and reinstall**: Run `uv sync --all-extras` to update `uv.lock`. Only needed when `pyproject.toml` changed (version bumps, dependency changes, etc.). Note: `uv sync` may uninstall the editable install — if `uv run` fails afterwards, run `uv pip install -e ".[dev]"` to restore it.
7. **Sync the registry when defs change**: If this change *added, renamed, or removed* a hook, skill, rule, or command (anywhere — global at `~/.claude/` or per-project under `.claude/`), or if it added new entries to `scripts/seed_config.py`, run the registry sync before committing:
   - `uv run python scripts/seed_config.py` — register new `HookDef` / `SkillDef` / `RuleDef` / `CommandDef` entries (idempotent; existing rows are skipped).
   - `uv run python scripts/sync_registry.py` — ingest the actual file contents (script bodies, `SKILL.md`, rule markdown, etc.) into the registry so the canonical content matches disk.
   This is mandatory for new defs — without it, the registry is the cross-machine source of truth but won't carry the change. An unsynced def is effectively lost when switching machines. Pure edits to existing defs only need step 2 (`sync_registry.py`); seeding is only needed when the def's *identity* (name / hook_type / matcher / command) is new.
8. **Commit changes**: Create a commit with a descriptive message following the format below
   - **Always include uv.lock** in commits when it has changed
9. **Push to remote**: Push the changes with `git push`

This workflow is MANDATORY after every prompt that results in code changes.

**Config/tooling changes** (anything under `.claude/` — rules,
skills, commands, hooks, `settings.json`, `settings.local.json` —
and `CLAUDE.md`): still require a patch version bump and changelog
entry, even when no application code changed. Follow the full
workflow above (skip tests only if no code changed). This applies
per project: if a cross-project migration touches N repos'
`.claude/` files, each repo gets its own patch bump and changelog
entry.

**Pure tracking changes** (`backlog.md` checkboxes only): commit and push,
but skip tests and version bump.

## Commit Message Format

Use conventional commit style:

```
<type>: <description>

[optional body]
```

## Types

- `feat` - New feature or functionality
- `fix` - Bug fix
- `refactor` - Code refactoring without changing behavior
- `docs` - Documentation changes
- `test` - Adding or updating tests
- `chore` - Maintenance tasks, dependency updates

## Best Practices

- Keep the subject line under 72 characters
- Use imperative mood ("Add feature" not "Added feature")
- **Default to subject-only.** Skip the body unless it adds
  something a reader wouldn't get from the subject, the diff,
  and the changelog entry.
- Reference issues when applicable
- **One command per Bash call** — never chain git commands with `&&`,
  `;`, heredocs, or subshells. Each `git add`, `git commit`,
  `git push`, etc. must be its own separate Bash call.

## When to Add a Body

A body is warranted only when the *why* is non-obvious and not
already captured elsewhere. Good reasons:

- A workaround for a specific bug or upstream issue (link it)
- A hidden constraint that explains an unusual choice
- An incident or decision the diff alone won't surface

Do **not** write bodies that:

- Restate what the diff does
- Recap which version this is or how it relates to the previous one
- Describe a new file/skill/function in prose (the changelog does that)
- Add multi-paragraph design rationale that belongs in a PR description

If you do add a body, separate it from the subject with a blank line
and keep it tight — one short paragraph is almost always enough.

## Examples

```
feat: Add project registry with version tracking
```

```
fix: Handle missing changelog in cross-project sync
```

```
docs: Update README with installation options
```
