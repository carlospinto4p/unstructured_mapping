"""Prompt construction for LLM-based pipeline passes.

Builds the system and user prompts for pass 1 (entity
resolution). Prompts follow the architecture defined in
``docs/pipeline/llm_interface.md``:

- **System prompt**: fixed task description, JSON output
  schema, and constraints. Sent once per pass, not
  repeated per chunk.
- **User prompt**: KG context block (candidate entities),
  optional running entity header (for multi-chunk docs),
  and the chunk text.

Why plain string construction?
    Prompt templates (Jinja, etc.) add a dependency for
    minimal benefit — the structure is simple and the
    variable parts are just string interpolation. Keeping
    it as plain Python makes the prompts easy to read,
    test, and iterate on.
"""

from collections.abc import Sequence

from unstructured_mapping.knowledge_graph.models import (
    Entity,
)
from unstructured_mapping.pipeline.models import (
    ResolvedMention,
)

PASS1_SYSTEM_PROMPT: str = """\
You are an entity resolution assistant. Your task is to \
identify entity mentions in the provided text and resolve \
each mention to a candidate entity from the knowledge \
graph, or propose a new entity if no candidate matches.

Output a single JSON object with this schema:

{
  "entities": [
    {
      "surface_form": "<exact text from the article>",
      "entity_id": "<candidate ID or null>",
      "new_entity": null or {
        "canonical_name": "<authoritative name>",
        "entity_type": "<one of: person, organization, \
place, topic, product, legislation, asset, metric, \
role, relation_kind>",
        "subtype": "<finer classification or null>",
        "description": "<natural-language context>",
        "aliases": ["<surface forms observed>"]
      },
      "context_snippet": "<~100 chars of surrounding text>"
    }
  ]
}

Rules:
- Only extract named entities — skip vague references \
like "the company" or "they".
- Each entity entry must have exactly one of: \
`entity_id` (non-null) or `new_entity` (non-null), \
never both.
- When resolving to a candidate, copy the exact \
`entity_id` from the CANDIDATE ENTITIES list.
- `context_snippet` must be a short passage (~100 \
characters) from the text surrounding the mention.
- If no entities are found, return {"entities": []}.
- Output valid JSON only — no commentary or markdown.\
"""


def build_kg_context_block(
    candidates: Sequence[Entity],
) -> str:
    """Format candidate entities as a numbered text block.

    Produces the compact text format defined in
    ``llm_interface.md`` § "KG context block format".
    Smaller models perform better with numbered text
    entries than with nested JSON.

    :param candidates: KG entities to include as
        resolution candidates.
    :return: Formatted text block, or empty string if
        no candidates.
    """
    if not candidates:
        return ""

    lines: list[str] = ["CANDIDATE ENTITIES:", ""]

    for idx, entity in enumerate(candidates, start=1):
        type_label = entity.entity_type.value
        if entity.subtype:
            type_label += f" / {entity.subtype}"

        aliases_str = ", ".join(entity.aliases)

        lines.append(f"[{idx}] entity_id={entity.entity_id}")
        lines.append(
            f"    name: {entity.canonical_name}"
        )
        lines.append(f"    type: {type_label}")
        if aliases_str:
            lines.append(f"    aliases: {aliases_str}")
        lines.append(
            f"    description: {entity.description}"
        )
        lines.append("")

    return "\n".join(lines)


def _build_running_entity_header(
    prev_entities: Sequence[ResolvedMention],
) -> str:
    """Format previously resolved entities as a compact header.

    For chunked documents, chunks after the first receive
    this header so the LLM recognises references to
    already-resolved entities. Deliberately more compact
    than the full KG context block — just enough to
    recognise, not re-resolve.

    :param prev_entities: Resolved mentions from earlier
        chunks in the same document.
    :return: Formatted header, or empty string if no
        previous entities.
    """
    if not prev_entities:
        return ""

    seen: dict[str, ResolvedMention] = {}
    for rm in prev_entities:
        if rm.entity_id not in seen:
            seen[rm.entity_id] = rm

    lines: list[str] = ["PREVIOUSLY RESOLVED ENTITIES:"]
    for rm in seen.values():
        lines.append(
            f"- {rm.surface_form} (id={rm.entity_id})"
        )

    return "\n".join(lines)


def build_pass1_user_prompt(
    kg_block: str,
    chunk_text: str,
    prev_entities: Sequence[ResolvedMention] = (),
) -> str:
    """Assemble the user prompt for pass 1.

    Combines the KG context block, optional running
    entity header, and chunk text into a single user
    prompt. Sections are separated by blank lines for
    readability.

    :param kg_block: Output of :func:`build_kg_context_block`.
    :param chunk_text: The article or chunk text to
        process.
    :param prev_entities: Resolved mentions from earlier
        chunks (empty for the first or only chunk).
    :return: Complete user prompt string.
    """
    parts: list[str] = []

    if kg_block:
        parts.append(kg_block)

    header = _build_running_entity_header(prev_entities)
    if header:
        parts.append(header)

    parts.append(f"TEXT:\n{chunk_text}")

    return "\n\n".join(parts)
