"""Shared database-open helpers for CLI commands.

:class:`KnowledgeStore` transparently creates the SQLite
file on first open. That is the right default for tools
that *populate* the KG (``populate``, ``seed``,
``wikidata_seed``), but the wrong default for tools that
*read* it: an audit run against a freshly created empty
database silently reports "nothing to audit" instead of
flagging the typo'd path.

``open_kg_store`` gives each CLI a single line that
expresses which behaviour it wants. Callers pass
``create_if_missing=False`` (the default) to fail loudly
on a missing file, or ``create_if_missing=True`` to preserve
the auto-create behaviour explicitly.
"""

from pathlib import Path

from unstructured_mapping.knowledge_graph import KnowledgeStore


def open_kg_store(
    path: Path,
    *,
    create_if_missing: bool = False,
) -> KnowledgeStore:
    """Open the KG SQLite store with explicit existence control.

    :param path: Filesystem path to the SQLite database.
    :param create_if_missing: When True, delegate to
        :class:`KnowledgeStore`'s default behaviour and
        create the database file if it does not exist.
        When False (the default), raise :class:`SystemExit`
        so the user sees a clear error rather than an empty
        database.
    :return: An opened :class:`KnowledgeStore` — callers
        should use it as a context manager.
    :raises SystemExit: When ``create_if_missing=False``
        and ``path`` does not exist.
    """
    if not create_if_missing and not path.exists():
        raise SystemExit(f"error: KG database not found at {path}")
    return KnowledgeStore(db_path=path)


__all__ = ["open_kg_store"]
