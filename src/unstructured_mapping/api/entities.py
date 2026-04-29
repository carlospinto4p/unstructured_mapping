"""Entity search and detail endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from unstructured_mapping.knowledge_graph import KnowledgeStore
from unstructured_mapping.knowledge_graph.models import (
    EntityStatus,
    EntityType,
)

from ._deps import get_kg
from ._serializers import (
    entity_to_dict,
    provenance_to_dict,
    relationship_to_dict,
)

router = APIRouter()


@router.get("/")
def list_entities(
    q: str | None = None,
    type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """List entities with optional filters.

    Priority: ``q`` (name prefix) > ``type`` > ``status``.
    When no filter is provided, returns ACTIVE entities.
    """
    if q:
        entities = kg.find_by_name_prefix(q, limit=limit + offset)
    elif type:
        try:
            et = EntityType(type)
        except ValueError:
            raise HTTPException(400, f"Unknown entity type: {type!r}")
        entities = kg.find_entities_by_type(et, limit=limit + offset)
    elif status:
        try:
            es = EntityStatus(status)
        except ValueError:
            raise HTTPException(400, f"Unknown entity status: {status!r}")
        entities = kg.find_entities_by_status(es, limit=limit + offset)
    else:
        entities = kg.find_entities_by_status(
            EntityStatus.ACTIVE, limit=limit + offset
        )
    return JSONResponse([entity_to_dict(e) for e in entities[offset:]])


@router.get("/{entity_id}")
def get_entity(
    entity_id: str,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Return a single entity with relationship and mention counts."""
    entity = kg.get_entity(entity_id)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    payload = entity_to_dict(entity)
    payload["relationship_count"] = len(
        kg.find_relationships_for_entity(entity_id)
    )
    payload["mention_count"] = len(kg.find_provenance_for_entity(entity_id))
    return JSONResponse(payload)


@router.get("/{entity_id}/relationships")
def get_entity_relationships(
    entity_id: str,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Return all relationships involving an entity."""
    if kg.get_entity(entity_id) is None:
        raise HTTPException(404, "Entity not found")
    rels = kg.find_relationships_for_entity(entity_id)
    return JSONResponse([relationship_to_dict(r) for r in rels])


@router.get("/{entity_id}/provenance")
def get_entity_provenance(
    entity_id: str,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Return all provenance (mentions) for an entity."""
    if kg.get_entity(entity_id) is None:
        raise HTTPException(404, "Entity not found")
    provs = kg.find_provenance_for_entity(entity_id)
    return JSONResponse([provenance_to_dict(p) for p in provs])
