"""Shared startup helper for KG-backed CLI commands.

Every CLI that opens a :class:`~unstructured_mapping.knowledge_graph.KnowledgeStore`
repeats the same three lines before its core logic::

    setup_logging()
    args = _build_parser().parse_args(argv)
    with open_kg_store(args.db) as store:
        ...

:func:`run_cli_with_kg` centralises that pattern so callers only
supply a parser factory, an optional arg validator, and a body
function that receives the open store and parsed namespace.
"""

import argparse
from collections.abc import Callable

from unstructured_mapping.cli._db_helpers import open_kg_store
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import KnowledgeStore


def run_cli_with_kg(
    parser_factory: Callable[[], argparse.ArgumentParser],
    body: Callable[[KnowledgeStore, argparse.Namespace], None],
    argv: list[str] | None = None,
    *,
    validate: Callable[[argparse.Namespace], None] | None = None,
    create_if_missing: bool = False,
) -> None:
    """Run a CLI body against an open :class:`KnowledgeStore`.

    Handles ``setup_logging``, argument parsing, optional arg
    validation, and the store context manager so callers do not
    repeat these three lines in every ``main``.

    :param parser_factory: Callable that returns a configured
        :class:`~argparse.ArgumentParser`.
    :param body: Core logic. Receives the open store and the
        parsed :class:`~argparse.Namespace`.
    :param argv: Argument list (``sys.argv[1:]`` when ``None``).
    :param validate: Optional post-parse validator called before
        the store is opened. Raise :class:`SystemExit` to abort
        with an error message.
    :param create_if_missing: When ``True`` the store is created
        if the database file does not exist. The default
        (``False``) raises :class:`SystemExit` on a missing file.
    """
    setup_logging()
    args = parser_factory().parse_args(argv)
    if validate is not None:
        validate(args)
    with open_kg_store(args.db, create_if_missing=create_if_missing) as store:
        body(store, args)


__all__ = ["run_cli_with_kg"]
