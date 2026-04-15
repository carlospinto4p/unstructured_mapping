"""LLM response parsing and validation.

Parses the raw JSON strings returned by the LLM for
entity resolution (pass 1) and relationship extraction
(pass 2), validating against the rules from
``docs/pipeline/03_llm_interface.md``.

Pass 1 validation rules:

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
import logging
from collections.abc import Mapping, Set
from datetime import datetime

from unstructured_mapping.knowledge_graph.models import (
    EntityType,
)
from unstructured_mapping.pipeline.models import (
    EntityProposal,
    ExtractedRelationship,
    ResolvedMention,
)

logger = logging.getLogger(__name__)


class Pass1ValidationError(ValueError):
    """The LLM response failed schema validation.

    The ``message`` describes which rule was violated,
    suitable for inclusion in a retry prompt so the LLM
    can correct its output. See
    ``docs/pipeline/03_llm_interface.md`` § "Retry and error
    feedback".
    """


def _parse_json(
    raw: str,
    error_cls: type[ValueError] = Pass1ValidationError,
) -> dict:
    """Parse raw LLM output as JSON.

    :param raw: Raw text from the LLM.
    :param error_cls: Exception class to raise on
        failure. Defaults to ``Pass1ValidationError``;
        pass 2 uses ``Pass2ValidationError``.
    :return: Parsed JSON object.
    :raises ValueError: (subclass) If the text is not
        valid JSON or is not a JSON object.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise error_cls(f"Invalid JSON: {exc.args[0]}") from exc

    if not isinstance(data, dict):
        raise error_cls(f"Expected a JSON object, got {type(data).__name__}.")
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
        raise Pass1ValidationError('Missing required key "entities".')
    if not isinstance(entities, list):
        raise Pass1ValidationError(
            f'"entities" must be an array, got {type(entities).__name__}.'
        )
    return entities


def _validate_required_fields(entry: dict, index: int) -> None:
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


def _validate_exactly_one_of(entry: dict, index: int) -> None:
    """Rule 3: exactly one of entity_id or new_entity.

    :param entry: A single entity entry.
    :param index: Zero-based position for error messages.
    :raises Pass1ValidationError: If both or neither are
        present.
    """
    has_id = (
        entry.get("entity_id") is not None and entry.get("entity_id") != ""
    )
    has_new = (
        entry.get("new_entity") is not None and entry.get("new_entity") != {}
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


def _validate_new_entity(new_entity: dict, index: int) -> EntityType:
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
            f'Entity [{index}].new_entity: "aliases" must be an array.'
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
    ``03_llm_interface.md`` and separates the response into
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
            _validate_entity_id(entity_id, candidate_ids, idx)
            resolved.append(
                ResolvedMention(
                    entity_id=entity_id,
                    surface_form=surface_form,
                    context_snippet=context_snippet,
                )
            )
        else:
            entity_type = _validate_new_entity(new_entity, idx)
            subtype = new_entity.get("subtype")
            if subtype is not None and not isinstance(subtype, str):
                subtype = None
            aliases = tuple(
                a
                for a in new_entity.get("aliases", [])
                if isinstance(a, str) and a
            )
            proposals.append(
                EntityProposal(
                    canonical_name=new_entity["canonical_name"],
                    entity_type=entity_type,
                    description=new_entity["description"],
                    subtype=subtype if subtype else None,
                    aliases=aliases,
                    source_chunk=chunk_index,
                    context_snippet=context_snippet,
                )
            )

    return tuple(resolved), tuple(proposals)


# -- Pass 2: Relationship extraction ---------------------


class Pass2ValidationError(ValueError):
    """The LLM response for pass 2 failed validation.

    Raised for structural issues (missing ``relationships``
    key, non-array value, missing required fields). Soft
    issues (unresolvable references, bad dates, self-refs)
    are handled by dropping the individual relationship
    with a warning, not by raising.
    """


def _parse_date(value: object) -> datetime | None:
    """Parse an ISO 8601 date string, or return None.

    Handles full dates (``2024-03-20``), year-month
    (``2024-03``), and year-only (``2024``). Returns
    ``None`` for non-string, empty, or unparseable
    values — the relationship is kept, only the
    temporal bound is dropped.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    logger.warning("Unparseable date %r, setting None", text)
    return None


def _parse_confidence(value: object) -> float | None:
    """Clamp an LLM-reported confidence to ``[0, 1]``.

    Returns ``None`` for missing, null, or non-numeric
    values — the relationship survives, only the score
    is dropped. Out-of-range numbers are clamped rather
    than rejected because the field is advisory; a
    relationship the LLM flagged as "1.2 confident"
    clearly means "as confident as possible" and dropping
    it would lose signal.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int; reject explicitly so
        # `True` / `False` don't silently become 1.0 / 0.0.
        return None
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _resolve_ref(
    ref: str,
    known_ids: Set[str],
    name_to_id: Mapping[str, str],
) -> str | None:
    """Resolve an entity reference to an ID.

    The LLM may return an entity ID or a canonical name.
    Returns the resolved ID, or ``None`` if unresolvable.
    """
    if ref in known_ids:
        return ref
    return name_to_id.get(ref)


def parse_pass2_response(
    raw: str,
    known_ids: Set[str],
    name_to_id: Mapping[str, str],
) -> tuple[ExtractedRelationship, ...]:
    """Parse and validate a pass 2 LLM response.

    Applies the five validation rules from
    ``03_llm_interface.md`` § "Pass 2 — Relationship
    extraction":

    1. ``relationships`` must be an array.
    2. Each entry must have ``source``, ``target``,
       ``relation_type``, ``context_snippet``.
    3. Source/target must resolve to a known ID or
       canonical name — unresolvable refs are dropped.
    4. Dates are parsed gracefully — unparseable values
       become ``None``.
    5. Self-referential relationships are dropped.

    Rules 1-2 are structural and raise
    :class:`Pass2ValidationError` for retry. Rules 3-5
    are soft: individual relationships are dropped with
    a warning.

    :param raw: Raw JSON string from the LLM.
    :param known_ids: Set of entity IDs present in the
        entity list (both KG entities and proposals with
        generated IDs).
    :param name_to_id: Mapping of canonical names to
        entity IDs, for resolving name references.
    :return: Validated extracted relationships.
    :raises Pass2ValidationError: If rules 1-2 are
        violated.
    """
    data = _parse_json(raw, Pass2ValidationError)
    entries = _validate_relationships_array(data)

    results: list[ExtractedRelationship] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise Pass2ValidationError(
                f"Relationship [{idx}]: expected an "
                f"object, got {type(entry).__name__}."
            )
        _validate_pass2_required(entry, idx)

        source_ref = entry["source"]
        target_ref = entry["target"]

        source_id = _resolve_ref(source_ref, known_ids, name_to_id)
        if source_id is None:
            logger.warning(
                "Relationship [%d]: unresolvable source %r, dropping",
                idx,
                source_ref,
            )
            continue

        target_id = _resolve_ref(target_ref, known_ids, name_to_id)
        if target_id is None:
            logger.warning(
                "Relationship [%d]: unresolvable target %r, dropping",
                idx,
                target_ref,
            )
            continue

        if source_id == target_id:
            logger.warning(
                "Relationship [%d]: self-referential "
                "(source == target == %r), dropping",
                idx,
                source_id,
            )
            continue

        qualifier = entry.get("qualifier")
        qualifier_id: str | None = None
        if qualifier is not None and isinstance(qualifier, str):
            qualifier_id = _resolve_ref(qualifier, known_ids, name_to_id)

        results.append(
            ExtractedRelationship(
                source_id=source_id,
                target_id=target_id,
                relation_type=entry["relation_type"],
                qualifier_id=qualifier_id,
                valid_from=_parse_date(entry.get("valid_from")),
                valid_until=_parse_date(entry.get("valid_until")),
                context_snippet=entry["context_snippet"],
                confidence=_parse_confidence(entry.get("confidence")),
            )
        )

    return tuple(results)


def _validate_relationships_array(
    data: dict,
) -> list[dict]:
    """Rule 1: ``relationships`` must be an array.

    :raises Pass2ValidationError: If missing or not an
        array.
    """
    rels = data.get("relationships")
    if rels is None:
        raise Pass2ValidationError('Missing required key "relationships".')
    if not isinstance(rels, list):
        raise Pass2ValidationError(
            f'"relationships" must be an array, got {type(rels).__name__}.'
        )
    return rels


def _validate_pass2_required(entry: dict, index: int) -> None:
    """Rule 2: required fields on each relationship.

    :raises Pass2ValidationError: If required fields
        are missing or not strings.
    """
    for field in (
        "source",
        "target",
        "relation_type",
        "context_snippet",
    ):
        val = entry.get(field)
        if not val or not isinstance(val, str):
            raise Pass2ValidationError(
                f'Relationship [{index}]: "{field}" '
                f"is required and must be a non-empty "
                f"string."
            )
