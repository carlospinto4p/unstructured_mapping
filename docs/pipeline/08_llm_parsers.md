# LLM Response Parsing — Design Decisions

## Purpose

`pipeline/llm_parsers.py` parses the raw JSON string
returned by the LLM for entity resolution (pass 1) and
validates it against the five rules from
[03_llm_interface.md](03_llm_interface.md). Valid entries are
converted into `ResolvedMention` and `EntityProposal`
objects for downstream stages.

For the response schema and validation rules, see
[03_llm_interface.md](03_llm_interface.md) § "Pass 1".
This document covers implementation-level decisions.


## Public API

| Symbol                    | Type      | Purpose                                              |
|---------------------------|-----------|------------------------------------------------------|
| `Pass1ValidationError`    | exception | Schema validation failure with human-readable message|
| `parse_pass1_response()`  | function  | Parse + validate → (resolved, proposals)             |


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


## What was deferred

- **Pass 2 parser** — relationship extraction parsing
  follows the same pattern but with different fields and
  validation rules. Will be added when the extraction
  stage is built.
- **Partial acceptance** — currently the entire response
  is rejected on any error. A future enhancement could
  accept valid entries and reject only the invalid ones,
  but this adds complexity for marginal benefit at
  current scale.
