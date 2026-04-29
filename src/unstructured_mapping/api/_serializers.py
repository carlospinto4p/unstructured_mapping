"""JSON-safe dict serialisers for KG and article models.

Follows the same pattern as :mod:`cli.export`: ``asdict()``
plus explicit field transforms for enums, datetimes, tuples,
and UUIDs. All functions return plain ``dict`` objects that
FastAPI's ``JSONResponse`` can serialise without a custom
encoder.
"""

from dataclasses import asdict
from datetime import datetime

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    IngestionRun,
    Provenance,
    Relationship,
    RunMetrics,
)
from unstructured_mapping.web_scraping.models import Article


def entity_to_dict(entity: Entity) -> dict[str, object]:
    """Serialise an :class:`Entity` to a JSON-safe dict."""
    payload = asdict(entity)
    payload["entity_type"] = entity.entity_type.value
    payload["status"] = entity.status.value
    for field in ("valid_from", "valid_until", "created_at", "updated_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    payload["aliases"] = list(entity.aliases)
    return payload


def relationship_to_dict(rel: Relationship) -> dict[str, object]:
    """Serialise a :class:`Relationship` to a JSON-safe dict."""
    payload = asdict(rel)
    for field in ("valid_from", "valid_until", "discovered_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    return payload


def provenance_to_dict(prov: Provenance) -> dict[str, object]:
    """Serialise a :class:`Provenance` to a JSON-safe dict."""
    payload = asdict(prov)
    value = payload.get("detected_at")
    if isinstance(value, datetime):
        payload["detected_at"] = value.isoformat()
    return payload


def run_to_dict(
    run: IngestionRun,
    metrics: RunMetrics | None,
) -> dict[str, object]:
    """Serialise an :class:`IngestionRun` + optional metrics."""
    payload = asdict(run)
    payload["status"] = run.status.value
    for field in ("started_at", "finished_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    payload["metrics"] = asdict(metrics) if metrics is not None else None
    return payload


def article_to_dict(article: Article) -> dict[str, object]:
    """Serialise an :class:`Article` to a JSON-safe dict."""
    payload = asdict(article)
    pub = payload.get("published")
    if isinstance(pub, datetime):
        payload["published"] = pub.isoformat()
    payload["document_id"] = str(article.document_id)
    return payload
