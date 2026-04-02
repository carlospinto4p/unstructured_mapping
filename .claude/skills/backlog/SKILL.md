---
name: backlog
version: 1.0.0
description: Display open backlog items and periodic pass reminders. Use when the user wants to see pending tasks, pick items to implement, or check review cadence.
---

Read `backlog.md` and display it following these rules:

1. **Only show open items** (`- [ ]`). Never show completed (`- [x]`)
   or cancelled (`~~`) items. If all items are done, say the backlog
   is empty.
2. **Number each item sequentially** (1, 2, 3…) so the user can pick
   by number.
3. **If fewer than 8 open items**, show them in a table:
   `| # | Description | Priority | Effort |`
   Otherwise, show a numbered list.

After the backlog, add a **Periodic passes** reminder. Count how many
version bumps have occurred since the last `/refactor`, `/optimize`,
or `/improvements` pass by reading `changelog.md`. The cadence is
every 6-7 versions. Show a short status line like:

> **Periodic passes:** 4 versions since last review — due in ~2-3
> versions (`/refactor`, `/optimize`, `/improvements`).

If a pass is overdue (7+ versions), flag it clearly:

> **Periodic passes:** 8 versions since last review — **overdue**.
> Consider running `/refactor`, `/optimize`, `/improvements`.

To determine "last review", look for changelog entries whose
description mentions refactoring, optimization, or improvement scans
(e.g., entries tagged as `refactor:` or referencing review/cleanup
batches).
