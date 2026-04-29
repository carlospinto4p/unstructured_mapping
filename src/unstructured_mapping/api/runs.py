"""Ingestion run endpoints: list, detail, trigger, and SSE stream."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from unstructured_mapping.cli.ingest import _build_provider, ingest
from unstructured_mapping.knowledge_graph import KnowledgeStore
from unstructured_mapping.knowledge_graph.models import RunStatus
from unstructured_mapping.web_scraping.storage import ArticleStore

from ._deps import get_articles_path, get_kg, get_kg_path
from ._serializers import run_to_dict

logger = logging.getLogger(__name__)

router = APIRouter()

#: Tracks fire-and-forget asyncio tasks to prevent GC
#: before completion.
_background_tasks: set[asyncio.Task] = set()


class IngestRequest(BaseModel):
    provider: str = "claude"
    model: str | None = None
    limit: int = 50
    cold_start: bool = False
    extract_relationships: bool = True
    source: str | None = None
    ollama_host: str | None = None


def _run_ingest_thread(
    kg_path: Path,
    articles_path: Path,
    req: IngestRequest,
) -> None:
    """Blocking ingest worker — runs in a thread pool thread.

    Opens its own KnowledgeStore and ArticleStore so it does
    not share SQLite connections with the main event loop.
    """
    try:
        provider = _build_provider(
            req.provider,
            model=req.model,
            ollama_host=req.ollama_host,
        )
    except ValueError as exc:
        logger.error("Ingest failed: %s", exc)
        return

    with KnowledgeStore(db_path=kg_path) as kg:
        with ArticleStore(db_path=articles_path) as articles_store:
            articles = articles_store.load(source=req.source, limit=req.limit)
        if not articles:
            logger.info("No articles to ingest.")
            return
        try:
            result = ingest(
                articles,
                kg,
                provider=provider,
                cold_start=req.cold_start,
                extract_relationships=req.extract_relationships,
            )
            logger.info(
                "Ingest complete: run_id=%s processed=%d",
                result.run_id,
                len(result.results),
            )
        except Exception:
            logger.exception("Ingest thread failed")


def _run_scrape_and_ingest_thread(
    kg_path: Path,
    articles_path: Path,
    req: IngestRequest,
) -> None:
    """Like :func:`_run_ingest_thread` but reads from KG store
    which was already populated by a prior scrape.

    Alias kept separate so callers are explicit about intent.
    """
    _run_ingest_thread(kg_path, articles_path, req)


@router.get("/")
def list_runs(
    limit: int = 20,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Return the most recent ingestion runs."""
    runs = kg.find_recent_runs(limit=limit)
    payload = []
    for run in runs:
        metrics = kg.get_run_metrics(run.run_id)
        payload.append(run_to_dict(run, metrics))
    return JSONResponse(payload)


@router.get("/{run_id}")
def get_run(
    run_id: str,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Return a single run with its metrics."""
    run = kg.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    metrics = kg.get_run_metrics(run_id)
    return JSONResponse(run_to_dict(run, metrics))


@router.post("/ingest")
async def trigger_ingest(
    body: IngestRequest,
    kg_path: Path = Depends(get_kg_path),
    articles_path: Path = Depends(get_articles_path),
) -> JSONResponse:
    """Start an ingest run in the background and return immediately.

    The run is tracked in the KG store; poll
    ``GET /api/runs/{run_id}`` or open
    ``GET /api/runs/{run_id}/stream`` for live status.
    """
    task = asyncio.create_task(
        asyncio.to_thread(_run_ingest_thread, kg_path, articles_path, body)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    # The run_id is created inside the pipeline; return a
    # sentinel so the caller knows to poll /runs for the
    # newest run.
    return JSONResponse(
        {"status": "started", "message": "Poll GET /api/runs for status"}
    )


async def _sse_events(
    run_id: str,
    kg_path: Path,
) -> AsyncGenerator[str, None]:
    """Async generator that polls the run status and emits SSE events.

    Emits a ``data:`` event on every status change and on the
    first poll. Terminates when the run reaches a terminal
    state (``completed`` or ``failed``) or after 10 minutes.
    """
    prev_status: str | None = None
    deadline = asyncio.get_event_loop().time() + 600  # 10 min cap

    while asyncio.get_event_loop().time() < deadline:
        with KnowledgeStore(db_path=kg_path) as kg:
            run = kg.get_run(run_id)
            metrics = kg.get_run_metrics(run_id) if run else None

        if run is None:
            yield (
                f"event: error\n"
                f"data: {json.dumps({'message': 'run not found'})}\n\n"
            )
            return

        status = run.status.value
        if status != prev_status:
            yield f"data: {json.dumps(run_to_dict(run, metrics))}\n\n"
            prev_status = status

        if status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value):
            return

        await asyncio.sleep(1)


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    kg_path: Path = Depends(get_kg_path),
) -> StreamingResponse:
    """SSE endpoint that streams run status until completion.

    Connect with ``EventSource`` or ``fetch`` in the browser.
    The stream closes automatically when the run reaches a
    terminal state.
    """

    async def generator() -> AsyncGenerator[str, None]:
        async for event in _sse_events(run_id, kg_path):
            if await request.is_disconnected():
                return
            yield event

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
