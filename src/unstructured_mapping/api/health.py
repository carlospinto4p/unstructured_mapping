"""Health endpoint: counts and latest-run summary."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from unstructured_mapping.knowledge_graph import KnowledgeStore
from unstructured_mapping.web_scraping.storage import ArticleStore

from ._deps import get_articles, get_kg
from ._serializers import run_to_dict

router = APIRouter()


@router.get("/health")
def health(
    kg: KnowledgeStore = Depends(get_kg),
    articles: ArticleStore = Depends(get_articles),
) -> JSONResponse:
    """Return entity counts, relationship count, article count,
    and the most recent ingestion run."""
    entity_counts = kg.count_entities_by_type()
    total_entities = sum(entity_counts.values())
    rel_count = kg.count_relationships()
    article_count = articles.count()
    article_counts_by_source = articles.counts_by_source()

    recent_runs = kg.find_recent_runs(limit=1)
    latest_run = None
    if recent_runs:
        run = recent_runs[0]
        metrics = kg.get_run_metrics(run.run_id)
        latest_run = run_to_dict(run, metrics)

    return JSONResponse(
        {
            "entities": {
                "total": total_entities,
                "by_type": entity_counts,
            },
            "relationships": rel_count,
            "articles": {
                "total": article_count,
                "by_source": article_counts_by_source,
            },
            "latest_run": latest_run,
        }
    )
