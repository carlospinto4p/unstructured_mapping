# Prompt Construction — Design Decisions

## Purpose

`pipeline/prompts.py` builds the system and user prompts
for both LLM passes (entity resolution and relationship
extraction). It implements the prompt architecture defined
in
[03_llm_interface.md](03_llm_interface.md) — this document
covers the implementation-level decisions not covered
there.


## Public API

| Symbol                      | Type     | Pass | Purpose                                              |
|-----------------------------|----------|------|------------------------------------------------------|
| `PASS1_SYSTEM_PROMPT`       | str      | 1    | Fixed system prompt for entity resolution            |
| `build_kg_context_block()`  | function | 1    | Format `Entity` objects as numbered text blocks      |
| `build_pass1_user_prompt()` | function | 1    | Assemble user prompt from KG block, header, and text |
| `PASS2_SYSTEM_PROMPT`       | str      | 2    | Fixed system prompt for relationship extraction      |
| `build_entity_list_block()` | function | 2    | Format resolved entities + proposals as compact list |
| `build_pass2_user_prompt()` | function | 2    | Assemble user prompt from entity block and text      |

`_build_running_entity_header()` is internal — called by
`build_pass1_user_prompt()` when `prev_entities` is
non-empty.


## System prompt decisions

### Entity type list is hardcoded in the prompt

The system prompt lists all ten `EntityType` values
inline rather than generating the list from the enum at
runtime. This is deliberate: the prompt wording around
the types matters for LLM output quality (e.g. ordering,
formatting), and auto-generating it would couple prompt
wording to enum iteration order. The test suite verifies
that every `EntityType` value appears in the prompt, so
drift between the enum and the prompt is caught.

### No few-shot examples

The system prompt does not include few-shot examples.
`03_llm_interface.md` § "What this design does NOT cover"
defers few-shot examples until baseline quality is
assessed with real articles. The schema example in the
prompt serves as a structural reference, not a few-shot
demonstration.

### Constraint phrasing

The "Rules" section uses imperative short sentences
("Only extract named entities", "Each entity entry must
have exactly one of..."). Local models in the 7B-13B
range follow explicit constraints better than nuanced
prose. The rules mirror the five validation rules from
`03_llm_interface.md` so the LLM is told the same
constraints the validator enforces.


## KG context block decisions

### Input type: `Entity` objects

`build_kg_context_block()` accepts `Sequence[Entity]`
directly rather than a lighter intermediate type. The
`Entity` dataclass already has all needed fields
(`entity_id`, `canonical_name`, `entity_type`, `subtype`,
`aliases`, `description`), and introducing a separate
"candidate" DTO would add a type with no new information.

### Aliases omitted when empty

If an entity has no aliases, the `aliases:` line is
omitted entirely rather than showing `aliases: (none)`.
Fewer lines means fewer tokens, and the absence is
self-evident — the LLM does not need to be told there
are no aliases.

### Subtype shown inline with type

Type and subtype are rendered as `type: organization /
central_bank` on a single line rather than on separate
lines. This mirrors how `EntityType` and subtypes are
conceptually related (subtype refines type) and saves
a line per candidate.


## Running entity header decisions

### Deduplication by entity ID

When the same entity is resolved multiple times across
earlier chunks (e.g. "the Fed" in chunk 1 and "Federal
Reserve" in chunk 2), the header shows it once. The
first `ResolvedMention` encountered for each entity ID
wins — this is arbitrary but deterministic, and the
header is only a recognition aid, not a re-resolution
input.

### Surface form, not canonical name

The header shows the `surface_form` from the
`ResolvedMention`, not the entity's `canonical_name`.
This is because the header's purpose is recognition —
the LLM sees what surface form was used in earlier
chunks, which helps it recognize the same entity under
a different name in the current chunk.

### Entity type omitted

`03_llm_interface.md` shows entity type in the running
entity header (e.g. `Federal Reserve (organization,
id=...)`). The current implementation omits the type
because `ResolvedMention` does not carry `entity_type`
— it only has the entity ID. Adding the type would
require a KG lookup per entity or enriching
`ResolvedMention` with the type field. Deferred until
multi-chunk processing is implemented and we can assess
whether the type aids LLM recognition in practice.


## User prompt assembly

### Section ordering

The user prompt assembles sections in this order:

1. KG context block (candidates)
2. Running entity header (previous entities)
3. Chunk text

KG context comes first because it establishes the
reference frame — the LLM reads the candidate list
before encountering the text. The text comes last
because it is the material to process, and placing it
at the end means the LLM's attention is freshest on it
(recency bias in attention mechanisms).

### Blank-line separation

Sections are joined by double newlines (`\n\n`). This
visual separation helps the LLM distinguish the
structural parts of the prompt. Single newlines are used
within sections (e.g. between candidate entries).


## Pass 2: Relationship extraction prompts

### PASS2_SYSTEM_PROMPT

The pass 2 system prompt follows the same structural
pattern as pass 1: task description, JSON schema with
example, and explicit rules. Key differences:

- **Task**: extract directed relationships, not resolve
  entity mentions.
- **Output schema**: `{"relationships": [...]}` with
  `source`, `target`, `relation_type`, `qualifier`,
  `valid_from`, `valid_until`, `context_snippet`.
- **Entity reference format**: source/target can be
  entity IDs or canonical names (unlike pass 1 where
  only IDs are accepted for existing entities).
- **Self-referential constraint**: explicitly tells the
  LLM not to create relationships where source == target.

### build_entity_list_block()

Formats resolved entities and proposals as the compact
"ENTITIES IN THIS TEXT:" block defined in
`03_llm_interface.md` § "Pass 2 entity list format":

```
ENTITIES IN THIS TEXT:

- Federal Reserve (id=a1b2c3d4)
- Jerome Powell (id=e5f6g7h8)
- CPI (metric, NEW — not yet in KG)
```

Design decisions:

- **Deduplication by entity ID** — same entity resolved
  from multiple surface forms appears once. The first
  `ResolvedMention` encountered wins (same policy as the
  running entity header in pass 1).
- **Proposals marked as NEW** — newly proposed entities
  include their type and a "NEW" label so the LLM knows
  they are not yet in the KG.
- **Compact format** — one line per entity. The LLM only
  needs to recognize entities, not re-resolve them.

### build_pass2_user_prompt()

Simpler than pass 1: just entity block + chunk text,
separated by blank lines. No running entity header
(pass 2 receives the full resolved entity list, not a
subset from earlier chunks).

Section ordering:

1. Entity list block
2. Chunk text

Entity block comes first (same rationale as pass 1: the
reference frame before the source material).


## What was deferred

- **Few-shot examples** — see system prompt section above.
- **Dynamic constraint injection** — e.g. "only extract
  entities of type ORGANIZATION" for filtered runs. Not
  needed until the pipeline supports filtered ingestion.
