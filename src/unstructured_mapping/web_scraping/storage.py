"""SQLite storage for scraped articles."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/articles.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS articles (
    url         TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    source      TEXT NOT NULL,
    published   TEXT,
    scraped_at  TEXT NOT NULL
)
"""


class ArticleStore:
    """SQLite-backed store for scraped articles.

    :param db_path: Path to the SQLite database file.
        Parent directories are created automatically.
    """

    def __init__(
        self, db_path: Path = _DEFAULT_DB_PATH
    ) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def save(self, articles: list[Article]) -> int:
        """Save articles, skipping duplicates by URL.

        :param articles: Articles to store.
        :return: Number of newly inserted articles.
        """
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for article in articles:
            pub = (
                article.published.isoformat()
                if article.published
                else None
            )
            try:
                self._conn.execute(
                    "INSERT INTO articles "
                    "(url, title, body, source, published, "
                    "scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        article.url,
                        article.title,
                        article.body,
                        article.source,
                        pub,
                        now,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                logger.debug(
                    "Skipping duplicate: %s",
                    article.url,
                )
        self._conn.commit()
        return inserted

    def load(
        self, source: str | None = None
    ) -> list[Article]:
        """Load articles from the store.

        :param source: Filter by source name, or ``None``
            for all.
        :return: List of articles.
        """
        if source is None:
            rows = self._conn.execute(
                "SELECT url, title, body, source, published "
                "FROM articles ORDER BY scraped_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT url, title, body, source, published "
                "FROM articles WHERE source = ? "
                "ORDER BY scraped_at DESC",
                (source,),
            ).fetchall()
        return [self._row_to_article(r) for r in rows]

    def count(self, source: str | None = None) -> int:
        """Count stored articles.

        :param source: Filter by source name, or ``None``
            for all.
        :return: Number of articles.
        """
        if source is None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM articles"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM articles "
                "WHERE source = ?",
                (source,),
            ).fetchone()
        return row[0]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "ArticleStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @staticmethod
    def _row_to_article(
        row: tuple[str, str, str, str, str | None],
    ) -> Article:
        url, title, body, source, pub_str = row
        published = (
            datetime.fromisoformat(pub_str)
            if pub_str
            else None
        )
        return Article(
            url=url,
            title=title,
            body=body,
            source=source,
            published=published,
        )
