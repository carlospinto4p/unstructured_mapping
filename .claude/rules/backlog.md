# Backlog Management

The `backlog.md` file tracks all improvements, fixes, and refactoring proposals.

## Format

- **Use checkboxes** (`- [ ]` / `- [x]`) for every item
- **Organize by date/version**, not by priority — each section header is a
  date with an optional version reference (e.g., `### 2026.02.09 (v1.10.3 refactor review)`)
- **Do not split by priority categories** (no "High/Medium/Low" subsections)
- Mark items as done (`- [x]`) when completed
- **Always mark backlog items as done** (`- [x]`) immediately after
  completing the corresponding task — do not wait for the user to ask

## Displaying the Backlog

- **Only show open items** (`- [ ]`) — never list completed (`- [x]`) or
  cancelled (`~~`) items. If all items are done, just say the backlog is empty.
- **When showing the backlog to the user** (e.g., to choose tasks), display
  each item with a sequential number to make it easy to pick tasks by number
- **When there are fewer than 10 open items**, show them in a table with
  columns: #, Description, Priority, Effort

## Auto-Cleanup

When displaying the backlog (via `/backlog`), if there are **5 or more
completed items** (`- [x]`), remove all completed and cancelled items
from `backlog.md`. Also remove any date section headers that become
empty after cleanup. Previous versions are in git history.

## Workflow Rules

When the user says 'implement items X, Y, Z' or 'do backlog items N-M', implement them sequentially — commit each one, run tests, then move to the next. Do not plan all of them upfront.
