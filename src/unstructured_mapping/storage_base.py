"""Shared base for SQLite-backed stores.

Both :class:`ArticleStore` and :class:`KnowledgeStore`
follow the same init pattern: create directories, open a
connection, run DDL, migrate, create indexes, and commit.
This module extracts the shared lifecycle so each store
only declares its schema and migrations.
"""

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


class SQLiteStore:
    """Base class for SQLite stores.

    Handles directory creation, connection lifecycle, the
    DDL → migrate → index → commit init sequence, and a
    shared :meth:`transaction` context manager so bulk
    writers can defer the per-call ``COMMIT`` that
    individual write helpers issue by default.

    Subclasses must set :attr:`_ddl_statements` and
    :attr:`_index_statements`, and may override
    :meth:`_migrate` to run schema migrations. Write
    helpers on subclasses should call :meth:`_commit`
    instead of ``self._conn.commit()`` so the commit is
    suppressed while inside a :meth:`transaction` block.

    :param db_path: Path to the SQLite database file.
        Parent directories are created automatically.
    :param pragmas: Optional PRAGMA statements to run
        after connecting (e.g. ``"foreign_keys = ON"``).
    """

    _ddl_statements: tuple[str, ...] = ()
    _index_statements: tuple[str, ...] = ()

    def __init__(
        self,
        db_path: Path,
        *,
        pragmas: tuple[str, ...] = (),
    ) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        #: Nest depth for :meth:`transaction`. When > 0,
        #: :meth:`_commit` becomes a no-op so the enclosing
        #: block controls when the actual COMMIT fires.
        self._transaction_depth = 0
        for pragma in pragmas:
            self._conn.execute(f"PRAGMA {pragma}")
        for ddl in self._ddl_statements:
            self._conn.execute(ddl)
        self._migrate()
        for idx in self._index_statements:
            self._conn.execute(idx)
        self._conn.commit()

    def _migrate(self) -> None:
        """Run schema migrations.

        Override in subclasses. Default is a no-op.
        """

    def _commit(self) -> None:
        """Commit unless we're inside a :meth:`transaction`.

        Write helpers should call this instead of
        ``self._conn.commit()`` directly. It lets bulk
        writers (seed importers, scraper batches) wrap N
        writes in a single transaction: every inner write
        helper still looks like it commits locally, but
        the actual ``COMMIT`` fires only once on block
        exit — cutting 1 round-trip per row down to 1 per
        batch.
        """
        if self._transaction_depth == 0:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Defer per-write commits until the block exits.

        Reentrant (nesting increments a depth counter;
        only the outermost block fires the actual
        COMMIT/ROLLBACK). Exceptions trigger a rollback
        of the deferred writes, matching the SQLite
        default autocommit semantics at the block level.

        Usage::

            with store.transaction():
                for entity in entities:
                    store.save_entity(entity)
        """
        self._transaction_depth += 1
        try:
            yield
        except BaseException:
            self._transaction_depth -= 1
            if self._transaction_depth == 0:
                self._conn.rollback()
            raise
        else:
            self._transaction_depth -= 1
            if self._transaction_depth == 0:
                self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()
