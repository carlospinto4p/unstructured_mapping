# Periodic Refactor Suggestions

Proactively suggest refactoring opportunities in the following situations:

## When to Suggest

1. **Every 6-7 versions released**: After approximately 6-7 version
   bumps (major, minor, or patch all count), suggest a combined
   `/refactor`, `/optimize`, and `/improvements` pass. Track the
   version count from the changelog to determine when it's time.

2. **During long sessions**: When a session involves multiple features, fixes, or changes across several files, suggest refactors before wrapping up.

3. **When noticing code smells**: If you spot code smells
   while working, flag them. Check
   `.claude/rules/refactoring-areas.md` (if it exists)
   for project-specific areas to watch for.

## How to Suggest

- Present refactor suggestions as a concise list with clear rationale
- Prioritize by impact: consistency and maintainability first
- Don’t auto-apply — always propose and let the user decide
- Group related suggestions together
- After each refactor proposal, add the items to `backlog.md` under a new
  section with the current date as the title (see `backlog.md` rules for format)
