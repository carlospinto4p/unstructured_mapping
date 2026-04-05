---
name: backlog
version: 1.3.0
description: >-
  Display open backlog items and periodic pass
  reminders. Use when the user wants to see pending
  tasks, pick items to implement, or check review
  cadence.
---

## Step 1 — Prep (silent, no output to user)

Read `backlog.md`. If it has **5 or more completed
items** (`- [x]`):

1. Remove all completed (`- [x]`) and cancelled
   (`~~`) items from `backlog.md`.
2. Remove any date section headers that become empty
   after the cleanup (no remaining `- [ ]` items).
3. Keep the `# Programme Backlog` title.
4. Commit the cleanup (no version bump needed).

Previous versions are preserved in git history.

## Step 2 — Display the backlog

Show only open items (`- [ ]`). Never show completed
or cancelled items. If all items are done, say the
backlog is empty.

1. **Number each item sequentially** (1, 2, 3...) across
   all sections so the user can pick by number.
2. **If fewer than 8 open items** in the entire backlog,
   use tables; otherwise, use numbered lists.
3. **If the backlog has multiple sections** (`###`
   headers), show one table (or list) per section with
   the section header above it. This helps the user
   distinguish different batches of tasks.
   If there is only one section, omit the header and
   show a single table.

## Step 3 — Periodic passes reminder

Count how many version bumps have occurred since the
last `/refactor`, `/optimize`, or `/improvements` pass
by reading `changelog.md`. The cadence is every 6-7
versions. Show a short status line like:

> **Periodic passes:** 4 versions since last review
> -- due in ~2-3 versions (`/refactor`, `/optimize`,
> `/improvements`).

If a pass is overdue (7+ versions), flag it clearly:

> **Periodic passes:** 8 versions since last review
> -- **overdue**. Consider running `/refactor`,
> `/optimize`, `/improvements`.

To determine "last review", look for changelog entries
whose description mentions refactoring, optimization,
or improvement scans (e.g., entries tagged as
`refactor:` or referencing review/cleanup batches).
