"""SQLite storage for scraped articles."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from unstructured_mapping.storage_base import SQLiteStore
from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/articles.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS articles (
    url          TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    source       TEXT NOT NULL,
    published    TEXT,
    scraped_at   TEXT NOT NULL,
    document_id  TEXT NOT NULL UNIQUE,
    content_hash TEXT
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_source_scraped "
    "ON articles (source, scraped_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_scraped_at ON articles (scraped_at)",
    "CREATE INDEX IF NOT EXISTS idx_document_id ON articles (document_id)",
    # Plain (non-unique) index on ``content_hash``: the
    # scrape path should be able to look up "does a row
    # with this body hash already exist?" with one B-tree
    # seek. Non-unique because legacy rows without a hash
    # store NULL, and SQLite already allows duplicate
    # NULLs in a non-unique index.
    "CREATE INDEX IF NOT EXISTS idx_content_hash ON articles (content_hash)",
)

#: Whitespace collapser used by :func:`compute_content_hash`.
#: Matches any run of Unicode whitespace (spaces, tabs,
#: newlines, NBSP) so minor whitespace edits don't change
#: the hash.
_WS_RE = re.compile(r"\s+")


def compute_content_hash(body: str) -> str:
    """Stable content hash over normalised body text.

    Lower-cases and collapses whitespace so minor
    formatting drift (an added newline, a double space,
    title-case vs sentence-case copy-paste) does not
    defeat dedup. Newswire-style near-duplicates that
    only differ in boilerplate wrapping still collide;
    substantively different rewrites do not.

    :param body: Article body text.
    :return: Hex SHA-256 digest of the normalised body.
    """
    normalised = _WS_RE.sub(" ", body.lower()).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class ArticleStore(SQLiteStore):
    """SQLite-backed store for scraped articles.

    :param db_path: Path to the SQLite database file.
        Parent directories are created automatically.
    """

    _ddl_statements = (_CREATE_TABLE,)
    _index_statements = _CREATE_INDEXES

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        super().__init__(db_path)

    def _migrate(self) -> None:
        """Migrate legacy databases to current schema.

        Runs five steps in order:

        1. Add ``document_id`` column and backfill UUIDs.
        2. Rebuild table to enforce NOT NULL + UNIQUE.
        3. Normalize hex IDs to canonical UUID format.
        4. Drop stale ``idx_source`` from pre-v0.5.8.
        5. Add ``content_hash`` column and backfill
           hashes for existing rows so the new dedup
           check has a baseline on legacy DBs.
        """
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(articles)")
        }
        if not cols:
            return
        self._migrate_add_document_id(cols)
        self._migrate_enforce_constraints()
        self._migrate_normalize_uuids()
        self._migrate_drop_stale_indexes()
        self._migrate_add_content_hash()

    def _migrate_add_document_id(self, cols: set[str]) -> None:
        """Add document_id column and backfill UUIDs."""
        if "document_id" in cols:
            return
        self._conn.execute("ALTER TABLE articles ADD COLUMN document_id TEXT")
        rows = self._conn.execute(
            "SELECT url FROM articles WHERE document_id IS NULL"
        ).fetchall()
        for (url,) in rows:
            self._conn.execute(
                "UPDATE articles SET document_id = ? WHERE url = ?",
                (str(uuid4()), url),
            )
        self._commit()
        logger.info(
            "Backfilled document_id for %d articles",
            len(rows),
        )

    def _migrate_enforce_constraints(self) -> None:
        """Rebuild table if NOT NULL constraint missing."""
        info = {
            row[1]: row[3]  # name -> notnull
            for row in self._conn.execute("PRAGMA table_info(articles)")
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
        self._conn.execute("DROP TABLE _articles_old")
        self._commit()
        logger.info("Rebuilt articles table with document_id constraints")

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
                "UPDATE articles SET document_id = ? WHERE url = ?",
                (str(UUID(hex_id)), url),
            )
        self._commit()
        logger.info(
            "Normalized %d hex document_ids to UUID",
            len(hex_rows),
        )

    def _migrate_drop_stale_indexes(self) -> None:
        """Drop idx_source replaced by idx_source_scraped."""
        self._conn.execute("DROP INDEX IF EXISTS idx_source")
        self._commit()

    def _migrate_add_content_hash(self) -> None:
        """Add ``content_hash`` and backfill existing rows.

        Legacy databases predate content-hash dedup. The
        column is added nullable so the migration never
        fails, then every row missing a hash is backfilled
        from its stored ``body``. Once backfilled, the
        insert path writes a hash for every new row and
        the collision check works uniformly across old
        and new data.
        """
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(articles)")
        }
        if "content_hash" not in cols:
            self._conn.execute(
                "ALTER TABLE articles ADD COLUMN content_hash TEXT"
            )
        # Backfill missing hashes in one pass. ``LENGTH``
        # check catches both NULL and empty-string legacy
        # rows without relying on ``IS NULL`` only.
        rows = self._conn.execute(
            "SELECT url, body FROM articles "
            "WHERE content_hash IS NULL OR content_hash = ''"
        ).fetchall()
        if not rows:
            return
        for url, body in rows:
            self._conn.execute(
                "UPDATE articles SET content_hash = ? WHERE url = ?",
                (compute_content_hash(body), url),
            )
        self._commit()
        logger.info(
            "Backfilled content_hash for %d legacy articles",
            len(rows),
        )

    def save(
        self,
        articles: list[Article],
        *,
        skip_content_dupes: bool = True,
    ) -> int:
        """Save articles, skipping duplicates.

        Two layers of dedup:

        * **URL** — enforced by the primary key; duplicate
          URLs have always been silently dropped by
          ``INSERT OR IGNORE``. Unchanged.
        * **Content hash** (new) — body text is normalised
          and hashed. When a matching hash already exists
          in the DB or appears earlier in the same batch,
          the article is dropped and the collision is
          logged. Set ``skip_content_dupes=False`` to keep
          near-duplicates (archival / snapshot runs where
          you want every copy).

        :param articles: Articles to store.
        :param skip_content_dupes: When True (default),
            drop articles whose body hash is already in the
            DB or was already saved earlier in this batch.
            When False, only URL dedup applies.
        :return: Number of newly inserted articles.
        """
        if not articles:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        with_hash = [(a, compute_content_hash(a.body)) for a in articles]
        kept: list[tuple[Article, str]] = []
        if skip_content_dupes:
            kept = self._filter_content_dupes(with_hash)
        else:
            kept = with_hash
        if not kept:
            return 0
        before = self._conn.total_changes
        rows = [
            (
                a.url,
                a.title,
                a.body,
                a.source,
                a.published.isoformat() if a.published else None,
                now,
                str(a.document_id),
                content_hash,
            )
            for a, content_hash in kept
        ]
        self._conn.executemany(
            "INSERT OR IGNORE INTO articles "
            "(url, title, body, source, published, "
            "scraped_at, document_id, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._commit()
        return self._conn.total_changes - before

    def _filter_content_dupes(
        self, candidates: list[tuple[Article, str]]
    ) -> list[tuple[Article, str]]:
        """Drop articles whose body hash already exists.

        Runs one batched ``SELECT DISTINCT content_hash
        FROM articles WHERE content_hash IN (...)`` so
        large batches pay one round-trip, not N. In-batch
        duplicates are also dropped so the insert does
        not paper over them.

        Collisions are logged at INFO (one line per
        dropped article, with source + URL) so operators
        running `/scrape` can see exactly which articles
        were squashed.
        """
        hashes = [h for _, h in candidates]
        existing: set[str] = set()
        if hashes:
            placeholders = ",".join("?" * len(hashes))
            existing = {
                row[0]
                for row in self._conn.execute(
                    "SELECT DISTINCT content_hash FROM articles "
                    f"WHERE content_hash IN ({placeholders})",
                    hashes,
                ).fetchall()
            }
        seen_in_batch: set[str] = set()
        kept: list[tuple[Article, str]] = []
        for article, content_hash in candidates:
            if content_hash in existing or content_hash in seen_in_batch:
                logger.info(
                    "Skipping content-duplicate article "
                    "source=%s url=%s hash=%s",
                    article.source,
                    article.url,
                    content_hash[:12],
                )
                continue
            seen_in_batch.add(content_hash)
            kept.append((article, content_hash))
        return kept

    def load(
        self,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        *,
        document_ids: list[str] | None = None,
    ) -> list[Article]:
        """Load articles from the store.

        :param source: Filter by source name, or ``None``
            for all.
        :param limit: Maximum number of articles to return,
            or ``None`` for all.
        :param offset: Number of articles to skip.
        :param document_ids: Restrict to these document ids.
            Accepts both canonical UUID (``str(uuid)``) and
            hex (``uuid.hex``) forms — the hex form matches
            :attr:`Article.document_id.hex` used by the KG
            pipeline as the provenance key. Empty list
            short-circuits to ``[]`` without a query. Used by
            :mod:`cli.ingest` to resume a prior run by
            loading only the articles the pipeline needs.
        :return: List of articles.
        """
        if document_ids is not None and not document_ids:
            return []
        query = (
            "SELECT url, title, body, source, published,"
            " document_id FROM articles"
        )
        clauses: list[str] = []
        params: list[str | int] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if document_ids is not None:
            # Accept both hex ('...' len 32) and canonical
            # UUID ('...-...-...') forms so callers holding
            # either shape get a match without round-tripping
            # through ``UUID(x)``.
            expanded: list[str] = []
            for doc_id in document_ids:
                expanded.append(doc_id)
                if len(doc_id) == 32:
                    expanded.append(str(UUID(doc_id)))
                elif "-" in doc_id:
                    expanded.append(UUID(doc_id).hex)
            placeholders = ",".join("?" * len(expanded))
            clauses.append(f"document_id IN ({placeholders})")
            params.extend(expanded)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY scraped_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        if offset:
            query += " OFFSET ?"
            params.append(offset)
        rows = self._conn.execute(query, params).fetchall()
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
        return self._conn.execute(query, params).fetchone()[0]

    def counts_by_source(self) -> dict[str, int]:
        """Count articles grouped by source.

        :return: Mapping of source name to article count.
        """
        rows = self._conn.execute(
            "SELECT source, COUNT(*) FROM articles GROUP BY source"
        ).fetchall()
        return {src: cnt for src, cnt in rows}

    @staticmethod
    def _row_to_article(
        row: tuple[str, str, str, str, str | None, str],
    ) -> Article:
        url, title, body, source, pub_str, doc_id = row
        published = datetime.fromisoformat(pub_str) if pub_str else None
        return Article(
            url=url,
            title=title,
            body=body,
            source=source,
            published=published,
            document_id=UUID(doc_id),
        )
