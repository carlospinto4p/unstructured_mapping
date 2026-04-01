# Design documentation

## Rule

Every schema, enum, data model, or architectural choice MUST
be documented with:

1. **What** it is (field, type, table, enum value).
2. **Why** it was chosen over alternatives.
3. **What was deferred** and why.

## Where to document

- Module-level docstrings for new modules.
- Class/field docstrings for data models.
- A file in `docs/` for decisions that span multiple files
  (e.g. `docs/knowledge_graph.md` for the KG data model).

## Audience

Someone reading the database or codebase for the first time,
with no access to conversation history. Every non-obvious
choice should be self-explanatory from the docs alone.

## Applies to

- New database tables and columns.
- Enums and their values.
- Data model fields and their types.
- Deferred features (document what was excluded and why).
- Any future feature — this rule is permanent.
