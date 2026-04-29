"""FastAPI application for the Unstructured Mapping API.

Exposes the knowledge graph and pipeline over HTTP so the
SvelteKit front-end (and any other client) can query
entities, relationships, provenance, and ingestion runs,
and trigger scrape/ingest jobs.

Usage (dev)::

    uv run python -m unstructured_mapping.cli.serve --reload

Environment variables:

``KNOWLEDGE_DB``
    Path to the KG SQLite file. Defaults to
    ``data/knowledge.db``.

``ARTICLES_DB``
    Path to the articles SQLite file. Defaults to
    ``data/articles.db``.

``ALLOWED_ORIGINS``
    Comma-separated list of origins allowed by CORS.
    Defaults to ``http://localhost:5173``.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .entities import router as _entities_router
from .health import router as _health_router
from .relationships import router as _relationships_router
from .runs import router as _runs_router
from .scrape import router as _scrape_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.kg_path = Path(
        os.environ.get("KNOWLEDGE_DB", "data/knowledge.db")
    )
    app.state.articles_path = Path(
        os.environ.get("ARTICLES_DB", "data/articles.db")
    )
    yield


app = FastAPI(
    title="Unstructured Mapping API",
    version="1.0.0",
    lifespan=_lifespan,
)

_allowed_origins = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    _entities_router, prefix="/api/entities", tags=["entities"]
)
app.include_router(
    _relationships_router,
    prefix="/api/relationships",
    tags=["relationships"],
)
app.include_router(_runs_router, prefix="/api/runs", tags=["runs"])
app.include_router(_scrape_router, prefix="/api/scrape", tags=["scrape"])
app.include_router(_health_router, prefix="/api", tags=["health"])
