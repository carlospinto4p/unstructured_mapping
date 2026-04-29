"""FastAPI dependency providers for database connections.

Each request gets its own :class:`KnowledgeStore` and
:class:`ArticleStore` connection via ``Depends()``. This
avoids SQLite thread-safety issues — a single shared
connection could be accessed from multiple worker threads
simultaneously.

DB paths are stored on ``app.state`` during lifespan
startup (see :mod:`api.__init__`).
"""

from collections.abc import Generator
from pathlib import Path

from fastapi import Request

from unstructured_mapping.knowledge_graph import KnowledgeStore
from unstructured_mapping.web_scraping.storage import ArticleStore


def get_kg_path(request: Request) -> Path:
    """Return the KG database path stored on app state."""
    return request.app.state.kg_path


def get_articles_path(request: Request) -> Path:
    """Return the articles database path stored on app state."""
    return request.app.state.articles_path


def get_seed_dir(request: Request) -> Path:
    """Return the seed directory path stored on app state."""
    return request.app.state.seed_dir


def get_kg(request: Request) -> Generator[KnowledgeStore, None, None]:
    """Yield an open :class:`KnowledgeStore` for the request lifetime."""
    with KnowledgeStore(db_path=request.app.state.kg_path) as kg:
        yield kg


def get_articles(
    request: Request,
) -> Generator[ArticleStore, None, None]:
    """Yield an open :class:`ArticleStore` for the request lifetime."""
    with ArticleStore(db_path=request.app.state.articles_path) as store:
        yield store
