# Optimization Areas

Project-specific performance areas to watch for when
running `/optimize` or noticing issues during normal work.

## What to Look For

- Memory: unbounded caches, large object retention.
- I/O: redundant reads, missing batching.
- Data structures: inefficient lookups, repeated serialization.
- Algorithm complexity: quadratic loops on large KGs/texts.
