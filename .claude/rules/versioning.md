# Versioning Workflow

After making significant changes, proactively update the version and changelog as part of the commit workflow. Ask the user which version type (major/minor/patch) if unclear.

**Important: One feature per version release.** Each new feature gets its own version release. Do NOT combine multiple features into a single version, even if implemented in the same session. This keeps the changelog clean and makes it easier to track what changed in each version.

**Exception — refactoring batches**: When running `/refactor` and implementing multiple cleanup items, they can share a single patch version since they are small, related improvements — not independent features.

**Version scheme** (semantic versioning):
- `MAJOR.0.0` - Breaking changes (removed/renamed modules, changed dependencies, API changes that break existing code)
- `MAJOR.MINOR.0` - New modules, significant features, or substantial enhancements (backward compatible)
- `MAJOR.MINOR.PATCH` - Bug fixes, small improvements, tests, documentation

**Minor version indicators** (use MINOR bump when):
- Adding new public methods or classes
- Significantly expanding existing functionality
- Adding new optional features or configuration options
- Structural improvements that enhance usability

**Breaking changes** that require a major version bump:
- Removing or renaming public modules, classes, or functions
- Removing or replacing required dependencies
- Changing method signatures in incompatible ways
- Removing features or changing default behavior

**Files to update:**
1. `pyproject.toml` - Update the `version` field
2. `changelog.md` - Add entry at the top following the format below

**Changelog format — keep it concise:**
```markdown
### vX.Y.Z - DDth Month YYYY

- Added enums in `module_name`:
  - `EnumA`
  - `EnumB`
- Added `ClassName.method_name()`: brief description.
- Updated `ClassName`: brief description of what changed.
```

**Style rules:**
- Use single backticks (`` `name` ``) for inline code — never double backticks.
- Do not add "Breaking change" labels or bold markers — the major version bump already signals that. Just describe what changed.
- Use short action verbs: "Added", "Updated", "Fixed", "Removed".
- Name the class/method/enum directly — no need to repeat the full module path for every sub-item.
- One bullet per logical change. **When listing 3+ items** (enums, methods, files, etc.), **always use sub-bullets** — never inline them in a comma-separated list.
- **Always group by module**: Group items under a parent bullet for each module/directory (e.g., `src/`, `.claude/rules/`). This applies even when all items belong to a single module — the module header makes the scope clear at a glance.

**When to use sub-bullets:**
- Multiple functions/classes added to the same module:
  ```
  - Added `db/utils.py`:
    - `create_db()`: description.
    - `require_db()`: description.
  ```
- Multiple files affected by the same logical change:
  ```
  - Added unit tests:
    - `tests/test_base.py`: 22 tests.
    - `tests/test_tables.py`: 12 tests.
  ```
- Multiple fixes in one version:
  ```
  - Fixed:
    - `module_a.py`: description.
    - `module_b.py`: description.
  ```
- Consequences of a parent change:
  ```
  - Moved `app/` into `src/project/app/`:
    - Updated `Dockerfile` entrypoint.
    - Updated `README.md` run command.
  ```

**When NOT to use sub-bullets:**
- Single-item sublists — fold into the parent bullet instead:
  ```
  - Added `docs/schema.md`: ERD and schema documentation.
  ```
- Unrelated changes — keep as separate top-level bullets.

**IMPORTANT**: Always leave **two blank lines** between version entries in the changelog for readability.

**IMPORTANT**: Always include changes to `.claude/rules/` and `CLAUDE.md` in the changelog. These are project configuration changes that affect development workflow and must be tracked like any other change.
