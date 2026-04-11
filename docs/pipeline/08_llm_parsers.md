# LLM Response Parsing — Design Decisions

## Purpose

`pipeline/llm_parsers.py` parses the raw JSON strings
returned by the LLM for both entity resolution (pass 1)
and relationship extraction (pass 2), validating against
the rules from [03_llm_interface.md](03_llm_interface.md).
Valid entries are converted into typed pipeline models for
downstream stages.

For the response schemas and validation rules, see
[03_llm_interface.md](03_llm_interface.md).
This document covers implementation-level decisions.


## Public API

| Symbol                    | Type      | Pass | Purpose                                              |
|---------------------------|-----------|------|------------------------------------------------------|
| `Pass1ValidationError`    | exception | 1    | Schema validation failure with human-readable message|
| `parse_pass1_response()`  | function  | 1    | Parse + validate -> (resolved, proposals)            |
| `Pass2ValidationError`    | exception | 2    | Structural validation failure for retry              |
| `parse_pass2_response()`  | function  | 2    | Parse + validate -> extracted relationships          |


## Fail-fast validation

### Why fail on the first error?

The parser raises `Pass1ValidationError` on the first
rule violation rather than collecting all errors. This is
simpler and sufficient because:

- The retry mechanism (backlog item 2e) appends the error
  message to the prompt. Sending one clear error is more
  effective than a list of cascading failures.
- A single structural error (e.g. missing `entities` key)
  invalidates the entire response anyway — collecting
  per-entry errors adds complexity for no benefit.

### Error messages are LLM-readable

The `Pass1ValidationError` message is phrased to be
useful in a retry prompt: it names the specific field
and entry index (e.g. `Entity [2]: "entity_type" is not
a valid entity type`). This follows
`03_llm_interface.md` § "Retry and error feedback" — the
error is appended to the user prompt so the LLM can
self-correct.


## Separation into ResolvedMention and EntityProposal

`parse_pass1_response()` returns a tuple of two tuples:
resolved mentions and entity proposals. These have
different downstream paths:

- **ResolvedMention** → provenance records (direct write).
- **EntityProposal** → validation → entity creation →
  then provenance.

This separation happens at parse time rather than later
because the parser already inspects the `entity_id` /
`new_entity` fields for rule 3. Emitting the correct
type immediately avoids a second classification pass.


## EntityProposal model

### Why a separate model, not Entity?

`EntityProposal` is deliberately lighter than `Entity`:
no `entity_id` (assigned at creation), no `status`,
no `valid_from/until`, no `created_at`. The proposal
carries only what the LLM provided plus
`source_chunk` for cross-chunk conflict resolution.

See [02_models.md](02_models.md) § "EntityProposal" for the
field table and rationale.

### source_chunk field

Set from the `chunk_index` parameter, not from the LLM
response. The LLM does not know which chunk it is
processing — chunk tracking is the orchestrator's
responsibility.


## Candidate ID validation (rule 5)

### Why a set, not a list?

`candidate_ids` is typed as `Set[str]` for O(1) lookup.
The typical candidate set is 20-50 IDs, so the
performance difference is negligible, but sets also
express the intent: order does not matter, uniqueness
is guaranteed.

### Why reject hallucinated IDs?

Local models sometimes generate plausible-looking hex
strings that do not correspond to any candidate. Without
this check, the pipeline would create provenance records
linking mentions to non-existent entities — corrupt data
that is hard to detect after the fact.


## EntityType validation (rule 4)

### Case-insensitive matching

The LLM may return `"Person"`, `"PERSON"`, or
`"person"`. The parser lowercases and strips before
matching against `EntityType`. This is more robust than
requiring exact case in the prompt — the prompt already
lists the types in lowercase, but models occasionally
capitalise.


## Pass 2: Relationship extraction parser

### parse_pass2_response()

```python
def parse_pass2_response(
    raw: str,
    known_ids: Set[str],
    name_to_id: Mapping[str, str],
) -> tuple[ExtractedRelationship, ...]:
```

Returns a flat tuple (not a two-tuple like pass 1)
because pass 2 has only one output type.

### Hard vs soft validation

Unlike pass 1 (which is entirely fail-fast), pass 2
splits validation into hard and soft rules:

**Hard** (raise `Pass2ValidationError`):
- Rule 1: `relationships` must exist and be an array.
- Rule 2: each entry must have `source`, `target`,
  `relation_type`, `context_snippet`.

**Soft** (drop individual relationship, log warning):
- Rule 3: unresolvable source/target references.
- Rule 4: unparseable dates (set to `None`).
- Rule 5: self-referential relationships.

This split exists because hard rules indicate the LLM
misunderstood the output format (retrying helps), while
soft rules indicate valid output with individual data
issues (retrying the entire prompt for one bad reference
is wasteful).

### Entity reference resolution

`parse_pass2_response()` accepts `known_ids` (set of
valid entity IDs) and `name_to_id` (canonical name to
ID mapping). References are resolved in order:

1. Direct ID match in `known_ids`.
2. Canonical name match in `name_to_id`.

This differs from pass 1's rule 5 (which only checks
against candidate IDs) because pass 2 allows canonical
name references per `03_llm_interface.md` § "Why allow
canonical names, not just IDs?".

### Date parsing

Dates are parsed at extraction time into `datetime`
objects, supporting three formats: `YYYY-MM-DD`,
`YYYY-MM`, `YYYY`. Unparseable values are set to `None`
with a warning log — the relationship is kept, only the
temporal bound is dropped.

### Qualifier resolution

The `qualifier` field follows the same resolution logic
as source/target (ID or name lookup). Unresolvable
qualifiers are silently set to `None` — a missing
qualifier is less critical than a missing source/target.


## What was deferred

- **Partial acceptance for pass 1** — currently the
  entire pass 1 response is rejected on any error. A
  future enhancement could accept valid entries and
  reject only the invalid ones, but this adds complexity
  for marginal benefit at current scale.
- **Cross-relationship validation** — e.g. detecting
  contradictory relationships in the same response.
  Deferred until real-world extraction quality is
  assessed.
