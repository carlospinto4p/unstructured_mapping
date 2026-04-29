"""Scrape trigger and article listing endpoints."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from unstructured_mapping.web_scraping import (
    APScraper,
    BBC_FEEDS,
    BBCScraper,
    ReutersScraper,
)
from unstructured_mapping.web_scraping.storage import ArticleStore

from ._deps import get_articles, get_articles_path
from ._serializers import article_to_dict
from .runs import _background_tasks

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_SOURCES = ("bbc", "reuters", "ap")


class ScrapeRequest(BaseModel):
    sources: list[str] = list(_VALID_SOURCES)
    feeds: str = "all"
    fetch_full_text: bool = True
    timeout: int = 30


def _run_scrape_thread(
    articles_path: Path,
    req: ScrapeRequest,
) -> int:
    """Blocking scrape worker — runs in a thread pool thread.

    :return: Total number of newly saved articles.
    """
    total = 0
    with ArticleStore(db_path=articles_path) as store:
        for name in req.sources:
            if name not in _VALID_SOURCES:
                logger.warning("Unknown scrape source %r — skipped", name)
                continue
            try:
                scraper = _build_scraper(
                    name, req.feeds, req.fetch_full_text, req.timeout
                )
                with scraper:
                    articles = scraper.fetch()
                saved = store.save(articles)
                logger.info(
                    "Scraped %s: %d articles, %d new",
                    name,
                    len(articles),
                    saved,
                )
                total += saved
            except Exception:
                logger.exception("Scraper failed for source %r", name)
    return total


def _build_scraper(
    name: str,
    feeds: str,
    fetch_full_text: bool,
    timeout: int,
) -> APScraper | BBCScraper | ReutersScraper:
    if name == "bbc":
        feed_urls = (
            list(BBC_FEEDS.values()) if feeds == "all" else [BBC_FEEDS["top"]]
        )
        return BBCScraper(
            feed_urls=feed_urls,
            fetch_full_text=fetch_full_text,
            timeout=timeout,
        )
    if name == "reuters":
        return ReutersScraper(timeout=timeout)
    return APScraper(
        fetch_full_text=fetch_full_text,
        timeout=timeout,
    )


@router.post("/")
async def trigger_scrape(
    body: ScrapeRequest,
    articles_path: Path = Depends(get_articles_path),
) -> JSONResponse:
    """Trigger a background scrape for the given sources."""
    invalid = [s for s in body.sources if s not in _VALID_SOURCES]
    if invalid:
        raise HTTPException(
            400,
            f"Unknown sources: {invalid!r}. Valid: {list(_VALID_SOURCES)}",
        )
    task = asyncio.create_task(
        asyncio.to_thread(_run_scrape_thread, articles_path, body)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(
        {
            "status": "started",
            "sources": body.sources,
            "message": "Poll GET /api/scrape/articles when complete",
        }
    )


@router.get("/articles")
def list_articles(
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
    store: ArticleStore = Depends(get_articles),
) -> JSONResponse:
    """Return recently scraped articles."""
    articles = store.load(source=source, limit=limit, offset=offset)
    return JSONResponse([article_to_dict(a) for a in articles])
