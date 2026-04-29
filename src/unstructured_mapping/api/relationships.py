"""Relationship query endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from unstructured_mapping.knowledge_graph import KnowledgeStore

from ._deps import get_kg
from ._serializers import relationship_to_dict

router = APIRouter()


@router.get("/")
def list_relationships(
    entity_id: str | None = None,
    source_id: str | None = None,
    target_id: str | None = None,
    type: str | None = None,
    min_confidence: float | None = None,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Return relationships matching the given filters.

    At least one of ``entity_id``, ``source_id``, or
    ``target_id`` must be provided. ``entity_id`` uses the
    confidence-aware :meth:`KnowledgeStore.find_relationships`
    method. ``source_id`` / ``target_id`` can be combined for
    directed queries.
    """
    if entity_id:
        rels = kg.find_relationships(entity_id, min_confidence=min_confidence)
    elif source_id and target_id:
        rels = kg.find_relationships_between(source_id, target_id)
    elif source_id:
        rels = kg.find_relationships_for_entity(source_id, as_target=False)
    elif target_id:
        rels = kg.find_relationships_for_entity(target_id, as_source=False)
    else:
        raise HTTPException(
            400,
            "Provide at least one of: entity_id, source_id, target_id",
        )

    if type:
        rels = [r for r in rels if r.relation_type == type]

    if min_confidence is not None and not entity_id:
        rels = [
            r
            for r in rels
            if r.confidence is not None and r.confidence >= min_confidence
        ]

    return JSONResponse([relationship_to_dict(r) for r in rels])
