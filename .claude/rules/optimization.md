# Periodic Optimization

Proactively suggest performance optimization opportunities in the
following situations:

## When to Suggest

1. **Every 6-7 versions released**: Same cadence as `/refactor` —
   suggest an optimization pass alongside refactoring reviews.

2. **During long sessions**: When a session involves multiple features
   or changes across several files, suggest optimizations before
   wrapping up.

3. **When noticing performance issues**: If you spot perf
   issues while working, flag them. Check
   `.claude/rules/optimization-areas.md` (if it exists)
   for project-specific areas to watch for.

## How to Suggest

- Present findings as a prioritized list with file, line, and rationale
- Classify impact as HIGH / MEDIUM / LOW
- Don't auto-apply — always propose and let the user decide
- Group related findings
- After each optimization proposal, add the items to `backlog.md`
  under a new section with the current date as the title (see
  `.claude/rules/backlog.md` for format)
