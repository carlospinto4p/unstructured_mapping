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

import shutil
from pathlib import Path

from unstructured_mapping.knowledge_graph import KnowledgeStore


def prepare_throwaway_kg(
    workdir: Path,
    name: str,
    *,
    source: Path | None = None,
) -> Path:
    """Materialise a throwaway KG file under ``workdir``.

    Used by the preview and benchmark CLIs, which both
    need a scratch SQLite file that either starts empty
    (cold-start flows) or is seeded from an existing KG
    (kg-driven flows). The helper centralises the
    "unlink stale copy, optionally copyfile from source"
    shape so both callers share one failure surface.

    :param workdir: Directory that owns the throwaway
        file. The caller is responsible for creating and
        eventually cleaning up this directory.
    :param name: Basename for the scratch file (e.g.
        ``"preview.db"``).
    :param source: Existing KG to seed the scratch file
        from. When ``None``, the returned path is
        guaranteed not to exist — callers open a fresh
        :class:`KnowledgeStore` on it. When set, the
        source is copied to the scratch path.
    :return: Full path to the throwaway file.
    :raises FileNotFoundError: When ``source`` is set
        but does not exist.
    """
    target = workdir / name
    if target.exists():
        target.unlink()
    if source is not None:
        if not source.exists():
            raise FileNotFoundError(source)
        shutil.copyfile(source, target)
    return target


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


__all__ = ["open_kg_store", "prepare_throwaway_kg"]
