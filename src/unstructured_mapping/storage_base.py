"""Shared base for SQLite-backed stores.

Both :class:`ArticleStore` and :class:`KnowledgeStore`
follow the same init pattern: create directories, open a
connection, run DDL, migrate, create indexes, and commit.
This module extracts the shared lifecycle so each store
only declares its schema and migrations.
"""

import sqlite3
from pathlib import Path


class SQLiteStore:
    """Base class for SQLite stores.

    Handles directory creation, connection lifecycle, and
    the DDL → migrate → index → commit init sequence.

    Subclasses must set :attr:`_ddl_statements` and
    :attr:`_index_statements`, and may override
    :meth:`_migrate` to run schema migrations.

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
