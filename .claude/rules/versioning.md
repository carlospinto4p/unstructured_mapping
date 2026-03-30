# Semantic versioning

## Scheme

- `MAJOR.0.0` — Breaking changes.
- `MAJOR.MINOR.0` — New modules, significant features.
- `MAJOR.MINOR.PATCH` — Bug fixes, small improvements, tests, docs.

One feature per version release (don't combine multiple features).

## Files to update

1. `pyproject.toml` — version field.
2. `changelog.md` — entry at top.

## Changelog format

```markdown
### vX.Y.Z - DDth Month YYYY

- Added X in `module_name`
- Updated `Class.method()`: description
- Fixed `issue`
```

## Rules

- Short action verbs: Added, Updated, Fixed, Removed.
- Use sub-bullets for 3+ items (never inline comma-separated).
- Group by file for 3+ changes in same file.
- Group auxiliary dirs (`.claude/rules/`) with sub-bullets.
- Don't group core `src/` files under directory heading.
- Two blank lines between version entries.
