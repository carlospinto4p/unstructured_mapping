"""LLM response parsing and validation for pass 1.

Parses the raw JSON string returned by the LLM for
entity resolution (pass 1) and validates it against the
five rules from ``docs/pipeline/llm_interface.md``:

1. ``entities`` must be an array (may be empty).
2. Each entry must have ``surface_form`` and
   ``context_snippet``.
3. Exactly one of: ``entity_id`` is non-null, or
   ``new_entity`` is non-null.
4. If ``new_entity`` is present, ``entity_type`` must
   be a valid :class:`EntityType` value
   (case-insensitive).
5. ``entity_id``, when non-null, must match a candidate
   ID from the prompt's KG context.

Why a separate module?
    Parsing and validation are complex enough to warrant
    their own module (not inlined in the resolver). They
    are also independently testable — the resolver tests
    can feed pre-validated data, and the parser tests can
    cover edge cases without needing an LLM fake.
"""

import json
from collections.abc import Set

from unstructured_mapping.knowledge_graph.models import (
    EntityType,
)
from unstructured_mapping.pipeline.models import (
    EntityProposal,
    ResolvedMention,
)


class Pass1ValidationError(ValueError):
    """The LLM response failed schema validation.

    The ``message`` describes which rule was violated,
    suitable for inclusion in a retry prompt so the LLM
    can correct its output. See
    ``docs/pipeline/llm_interface.md`` § "Retry and error
    feedback".
    """


def _parse_json(raw: str) -> dict:
    """Parse raw LLM output as JSON.

    :param raw: Raw text from the LLM.
    :return: Parsed JSON object.
    :raises Pass1ValidationError: If the text is not
        valid JSON or is not a JSON object.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Pass1ValidationError(
            f"Invalid JSON: {exc.args[0]}"
        ) from exc

    if not isinstance(data, dict):
        raise Pass1ValidationError(
            "Expected a JSON object, got "
            f"{type(data).__name__}."
        )
    return data


def _validate_entities_array(data: dict) -> list[dict]:
    """Rule 1: ``entities`` must be an array.

    :param data: Parsed JSON object.
    :return: The entities array.
    :raises Pass1ValidationError: If ``entities`` is
        missing or not an array.
    """
    entities = data.get("entities")
    if entities is None:
        raise Pass1ValidationError(
            'Missing required key "entities".'
        )
    if not isinstance(entities, list):
        raise Pass1ValidationError(
            '"entities" must be an array, got '
            f"{type(entities).__name__}."
        )
    return entities


def _validate_required_fields(
    entry: dict, index: int
) -> None:
    """Rule 2: each entry needs surface_form + snippet.

    :param entry: A single entity entry.
    :param index: Zero-based position for error messages.
    :raises Pass1ValidationError: If required fields are
        missing or not strings.
    """
    for field in ("surface_form", "context_snippet"):
        val = entry.get(field)
        if not val or not isinstance(val, str):
            raise Pass1ValidationError(
                f'Entity [{index}]: "{field}" is '
                f"required and must be a non-empty "
                f"string."
            )


def _validate_exactly_one_of(
    entry: dict, index: int
) -> None:
    """Rule 3: exactly one of entity_id or new_entity.

    :param entry: A single entity entry.
    :param index: Zero-based position for error messages.
    :raises Pass1ValidationError: If both or neither are
        present.
    """
    has_id = (
        entry.get("entity_id") is not None
        and entry.get("entity_id") != ""
    )
    has_new = (
        entry.get("new_entity") is not None
        and entry.get("new_entity") != {}
    )

    if has_id and has_new:
        raise Pass1ValidationError(
            f"Entity [{index}]: must have exactly one "
            f'of "entity_id" or "new_entity", got both.'
        )
    if not has_id and not has_new:
        raise Pass1ValidationError(
            f"Entity [{index}]: must have exactly one "
            f'of "entity_id" or "new_entity", got '
            f"neither."
        )


def _validate_new_entity(
    new_entity: dict, index: int
) -> EntityType:
    """Rule 4: new_entity fields + valid EntityType.

    :param new_entity: The ``new_entity`` object.
    :param index: Zero-based position for error messages.
    :return: The validated :class:`EntityType`.
    :raises Pass1ValidationError: If required fields are
        missing or ``entity_type`` is invalid.
    """
    for field in (
        "canonical_name",
        "entity_type",
        "description",
    ):
        val = new_entity.get(field)
        if not val or not isinstance(val, str):
            raise Pass1ValidationError(
                f"Entity [{index}].new_entity: "
                f'"{field}" is required and must be '
                f"a non-empty string."
            )

    aliases = new_entity.get("aliases")
    if not isinstance(aliases, list):
        raise Pass1ValidationError(
            f"Entity [{index}].new_entity: "
            f'"aliases" must be an array.'
        )

    raw_type = new_entity["entity_type"].strip().lower()
    try:
        return EntityType(raw_type)
    except ValueError:
        valid = ", ".join(et.value for et in EntityType)
        raise Pass1ValidationError(
            f"Entity [{index}].new_entity: "
            f'"{new_entity["entity_type"]}" is not a '
            f"valid entity type. Valid types: {valid}."
        ) from None


def _validate_entity_id(
    entity_id: str,
    candidate_ids: Set[str],
    index: int,
) -> None:
    """Rule 5: entity_id must match a candidate.

    :param entity_id: The entity ID from the response.
    :param candidate_ids: Set of valid candidate IDs.
    :param index: Zero-based position for error messages.
    :raises Pass1ValidationError: If the ID is not in the
        candidate set.
    """
    if entity_id not in candidate_ids:
        raise Pass1ValidationError(
            f"Entity [{index}]: entity_id "
            f'"{entity_id}" is not in the candidate '
            f"set. The LLM may have hallucinated this "
            f"ID."
        )


def parse_pass1_response(
    raw: str,
    candidate_ids: Set[str],
    chunk_index: int = 0,
) -> tuple[
    tuple[ResolvedMention, ...],
    tuple[EntityProposal, ...],
]:
    """Parse and validate a pass 1 LLM response.

    Applies the five validation rules from
    ``llm_interface.md`` and separates the response into
    resolved mentions (matched to existing KG entities)
    and entity proposals (new entities to create).

    Validation is fail-fast: the first rule violation
    raises :class:`Pass1ValidationError`. The caller
    (``LLMEntityResolver``) decides whether to retry.

    :param raw: Raw JSON string from the LLM.
    :param candidate_ids: Set of valid candidate entity
        IDs that were included in the prompt's KG context
        block. Used for rule 5 (hallucination check).
    :param chunk_index: Zero-based chunk position, set on
        :attr:`EntityProposal.source_chunk`.
    :return: A tuple of (resolved mentions, entity
        proposals).
    :raises Pass1ValidationError: If any validation rule
        is violated.
    """
    data = _parse_json(raw)
    entities = _validate_entities_array(data)

    resolved: list[ResolvedMention] = []
    proposals: list[EntityProposal] = []

    for idx, entry in enumerate(entities):
        if not isinstance(entry, dict):
            raise Pass1ValidationError(
                f"Entity [{idx}]: expected an object, "
                f"got {type(entry).__name__}."
            )

        _validate_required_fields(entry, idx)
        _validate_exactly_one_of(entry, idx)

        entity_id = entry.get("entity_id")
        new_entity = entry.get("new_entity")
        surface_form = entry["surface_form"]
        context_snippet = entry["context_snippet"]

        if entity_id is not None and entity_id != "":
            _validate_entity_id(
                entity_id, candidate_ids, idx
            )
            resolved.append(
                ResolvedMention(
                    entity_id=entity_id,
                    surface_form=surface_form,
                    context_snippet=context_snippet,
                )
            )
        else:
            entity_type = _validate_new_entity(
                new_entity, idx
            )
            subtype = new_entity.get("subtype")
            if subtype is not None and not isinstance(
                subtype, str
            ):
                subtype = None
            aliases = tuple(
                a
                for a in new_entity.get("aliases", [])
                if isinstance(a, str) and a
            )
            proposals.append(
                EntityProposal(
                    canonical_name=new_entity[
                        "canonical_name"
                    ],
                    entity_type=entity_type,
                    description=new_entity["description"],
                    subtype=subtype if subtype else None,
                    aliases=aliases,
                    source_chunk=chunk_index,
                    context_snippet=context_snippet,
                )
            )

    return tuple(resolved), tuple(proposals)
