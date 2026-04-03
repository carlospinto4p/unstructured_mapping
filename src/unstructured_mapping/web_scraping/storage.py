"""SQLite storage for scraped articles."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from unstructured_mapping.storage_base import SQLiteStore
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
    scraped_at  TEXT NOT NULL,
    document_id TEXT NOT NULL UNIQUE
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_source_scraped "
    "ON articles (source, scraped_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_scraped_at "
    "ON articles (scraped_at)",
    "CREATE INDEX IF NOT EXISTS idx_document_id "
    "ON articles (document_id)",
)


class ArticleStore(SQLiteStore):
    """SQLite-backed store for scraped articles.

    :param db_path: Path to the SQLite database file.
        Parent directories are created automatically.
    """

    _ddl_statements = (_CREATE_TABLE,)
    _index_statements = _CREATE_INDEXES

    def __init__(
        self, db_path: Path = _DEFAULT_DB_PATH
    ) -> None:
        super().__init__(db_path)

    def _migrate(self) -> None:
        """Migrate legacy databases to current schema.

        Runs four steps in order:

        1. Add ``document_id`` column and backfill UUIDs.
        2. Rebuild table to enforce NOT NULL + UNIQUE.
        3. Normalize hex IDs to canonical UUID format.
        4. Drop stale ``idx_source`` from pre-v0.5.8.
        """
        cols = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(articles)"
            )
        }
        if not cols:
            return
        self._migrate_add_document_id(cols)
        self._migrate_enforce_constraints()
        self._migrate_normalize_uuids()
        self._migrate_drop_stale_indexes()

    def _migrate_add_document_id(
        self, cols: set[str]
    ) -> None:
        """Add document_id column and backfill UUIDs."""
        if "document_id" in cols:
            return
        self._conn.execute(
            "ALTER TABLE articles "
            "ADD COLUMN document_id TEXT"
        )
        rows = self._conn.execute(
            "SELECT url FROM articles "
            "WHERE document_id IS NULL"
        ).fetchall()
        for (url,) in rows:
            self._conn.execute(
                "UPDATE articles "
                "SET document_id = ? "
                "WHERE url = ?",
                (str(uuid4()), url),
            )
        self._conn.commit()
        logger.info(
            "Backfilled document_id for %d articles",
            len(rows),
        )

    def _migrate_enforce_constraints(self) -> None:
        """Rebuild table if NOT NULL constraint missing."""
        info = {
            row[1]: row[3]  # name -> notnull
            for row in self._conn.execute(
                "PRAGMA table_info(articles)"
            )
        }
        if info.get("document_id"):
            return
        self._conn.executescript("""
            ALTER TABLE articles
                RENAME TO _articles_old;
        """)
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute("""
            INSERT INTO articles
                (url, title, body, source,
                 published, scraped_at, document_id)
            SELECT url, title, body, source,
                   published, scraped_at, document_id
            FROM _articles_old
        """)
        self._conn.execute(
            "DROP TABLE _articles_old"
        )
        self._conn.commit()
        logger.info(
            "Rebuilt articles table with "
            "document_id constraints"
        )

    def _migrate_normalize_uuids(self) -> None:
        """Normalize 32-char hex IDs to UUID format."""
        hex_rows = self._conn.execute(
            "SELECT url, document_id FROM articles "
            "WHERE LENGTH(document_id) = 32"
        ).fetchall()
        if not hex_rows:
            return
        for url, hex_id in hex_rows:
            self._conn.execute(
                "UPDATE articles "
                "SET document_id = ? "
                "WHERE url = ?",
                (str(UUID(hex_id)), url),
            )
        self._conn.commit()
        logger.info(
            "Normalized %d hex document_ids to UUID",
            len(hex_rows),
        )

    def _migrate_drop_stale_indexes(self) -> None:
        """Drop idx_source replaced by idx_source_scraped."""
        self._conn.execute(
            "DROP INDEX IF EXISTS idx_source"
        )
        self._conn.commit()

    def save(self, articles: list[Article]) -> int:
        """Save articles, skipping duplicates by URL.

        Uses bulk insert for performance.

        :param articles: Articles to store.
        :return: Number of newly inserted articles.
        """
        if not articles:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        before = self._conn.total_changes
        rows = [
            (
                a.url,
                a.title,
                a.body,
                a.source,
                a.published.isoformat()
                if a.published
                else None,
                now,
                str(a.document_id),
            )
            for a in articles
        ]
        self._conn.executemany(
            "INSERT OR IGNORE INTO articles "
            "(url, title, body, source, published, "
            "scraped_at, document_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def load(
        self,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Article]:
        """Load articles from the store.

        :param source: Filter by source name, or ``None``
            for all.
        :param limit: Maximum number of articles to return,
            or ``None`` for all.
        :param offset: Number of articles to skip.
        :return: List of articles.
        """
        query = (
            "SELECT url, title, body, source, published,"
            " document_id FROM articles"
        )
        params: list[str | int] = []
        if source is not None:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY scraped_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        if offset:
            query += " OFFSET ?"
            params.append(offset)
        rows = self._conn.execute(
            query, params
        ).fetchall()
        return [self._row_to_article(r) for r in rows]

    def count(self, source: str | None = None) -> int:
        """Count stored articles.

        :param source: Filter by source name, or ``None``
            for all.
        :return: Number of articles.
        """
        query = "SELECT COUNT(*) FROM articles"
        params: tuple[str, ...] = ()
        if source is not None:
            query += " WHERE source = ?"
            params = (source,)
        return self._conn.execute(
            query, params
        ).fetchone()[0]

    def counts_by_source(self) -> dict[str, int]:
        """Count articles grouped by source.

        :return: Mapping of source name to article count.
        """
        rows = self._conn.execute(
            "SELECT source, COUNT(*) FROM articles "
            "GROUP BY source"
        ).fetchall()
        return {src: cnt for src, cnt in rows}

    @staticmethod
    def _row_to_article(
        row: tuple[
            str, str, str, str, str | None, str
        ],
    ) -> Article:
        url, title, body, source, pub_str, doc_id = row
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
            document_id=UUID(doc_id),
        )
