# Performance optimization

## When to suggest

- Every 6-7 versions.
- During long sessions with multiple changes.
- When spotting performance issues.

## What to look for

- Memory: unbounded caches, large object retention.
- I/O: redundant reads, missing batching.
- Data structures: inefficient lookups, repeated serialization.
- Algorithm complexity: quadratic loops on large KGs/texts.

## Output

List by HIGH/MEDIUM/LOW impact, added to `backlog.md`.
