---
name: self-refinement
version: 1.0.0
description: >-
  Review all Claude settings for congruence, minimalism,
  and correctness.
---

Review all Claude settings for congruence, minimalism,
and correctness.

## Scope

Read every file in the configuration surface:

1. `CLAUDE.md` (project root)
2. All files under `.claude/rules/`
3. All files under `.claude/commands/`
4. All files under `.claude/skills/`

Then cross-reference against the actual project state
(source tree, `pyproject.toml`, test suites, changelog,
README, backlog).

## Checks

For each file, verify:

- **Accuracy**: Do commands, paths, module names, and
  conventions still match the codebase? Flag anything
  stale or wrong.
- **Minimalism**: Is every line necessary? Remove
  duplicated info, rules that restate defaults, or
  content discoverable from the code.
- **Consistency**: Do rules across files agree with each
  other? (e.g., versioning <> committing <> changelog
  format)
- **Completeness**: Are there patterns or conventions the
  project follows that are not documented but should be?
- **Overlap**: Is anything repeated between `CLAUDE.md`
  and the rules files, or between rules files themselves?

## Output

Present findings as a numbered list grouped by file, with
a short rationale for each item. Classify each finding as:

- **Fix** — clearly wrong or outdated, should be
  corrected.
- **Simplify** — redundant or verbose, can be trimmed.
- **Add** — missing rule or convention worth documenting.
- **Question** — ambiguous; needs user decision.

Do NOT apply changes automatically. Show the list and let
the user decide which items to address.
