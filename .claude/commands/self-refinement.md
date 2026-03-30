Review all configuration (`CLAUDE.md`, `.claude/rules/`, `.claude/commands/`) against the actual project state.

Checks:

- **Accuracy**: do rules match the codebase? Flag stale/wrong entries.
- **Minimalism**: remove unnecessary lines.
- **Consistency**: do rules agree across files?
- **Completeness**: missing patterns?
- **Overlap**: anything repeated?

Output: numbered list by file, classified as Fix / Simplify / Add / Question.
