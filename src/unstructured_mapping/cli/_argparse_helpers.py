"""Shared argparse helpers for CLI commands.

Every CLI in :mod:`unstructured_mapping.cli` layers a few
standard flags on top of its own options. This module
keeps their flag name, type, and help wording consistent
so the ``--help`` output stays uniform across commands.

The helpers standardize on argparse-native ``required=True``
for flags that must be supplied — CLIs that previously
validated ``default=None`` manually in ``main()`` should use
this idiom instead. Conditionally-required flags (e.g.
``--kg-db`` in :mod:`cli.preview`, which is off under
``--cold-start``) use :func:`require_db_unless`, since
argparse cannot express this natively.
"""

import argparse
from pathlib import Path

#: Default SQLite path for the knowledge graph. A single
#: constant keeps all KG-bound CLIs pointing at the same
#: file on disk.
KG_DEFAULT_DB = Path("data/knowledge.db")

#: Default SQLite path for the scraped-articles database.
ARTICLES_DEFAULT_DB = Path("data/articles.db")


def add_db_argument(
    parser: argparse.ArgumentParser,
    *,
    default: Path | None = KG_DEFAULT_DB,
    required: bool = False,
    label: str = "KG SQLite database",
) -> None:
    """Attach a standardized ``--db`` argument.

    :param parser: Target parser.
    :param default: Default path used when ``required`` is
        False. Ignored when ``required=True``.
    :param required: When True, argparse enforces the flag
        and emits no default.
    :param label: Human phrase plugged into the help text
        (e.g. ``"KG SQLite database"`` or ``"articles
        SQLite database"``).
    """
    if required:
        parser.add_argument(
            "--db",
            type=Path,
            required=True,
            help=f"Path to the {label}.",
        )
        return
    parser.add_argument(
        "--db",
        type=Path,
        default=default,
        help=f"Path to the {label} (default: {default}).",
    )


def add_dry_run_argument(
    parser: argparse.ArgumentParser,
    *,
    help_text: str = (
        "Parse and validate input without writing to the database."
    ),
) -> None:
    """Attach a standardized ``--dry-run`` flag.

    :param parser: Target parser.
    :param help_text: Override help string when the CLI
        parses a different input shape (e.g. Wikidata
        snapshots vs curated seed).
    """
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=help_text,
    )


def require_db_unless(
    args: argparse.Namespace,
    *,
    db_attr: str = "kg_db",
    unless_flag: str = "cold_start",
    db_flag_label: str = "--kg-db",
    unless_flag_label: str = "--cold-start",
) -> None:
    """Enforce "DB flag is set unless ``unless_flag`` is on".

    Argparse cannot express "required unless another flag is
    set" directly, so this is a post-``parse_args`` validator.
    Raises :class:`SystemExit` with the standardised message —
    matches argparse's own failure path so the CLI exits with
    the expected shape.

    :param args: Parsed namespace from ``parser.parse_args``.
    :param db_attr: Attribute name on ``args`` holding the DB
        path (e.g. ``"kg_db"`` for ``--kg-db``).
    :param unless_flag: Attribute name on ``args`` for the
        bypass flag (e.g. ``"cold_start"``).
    :param db_flag_label: User-facing label of the DB flag for
        the error message.
    :param unless_flag_label: User-facing label of the bypass
        flag for the error message.
    :raises SystemExit: When the DB is missing and the bypass
        flag is off.
    """
    if not getattr(args, unless_flag) and getattr(args, db_attr) is None:
        raise SystemExit(
            f"error: {db_flag_label} is required unless "
            f"{unless_flag_label} is set."
        )


def add_csv_output_argument(
    parser: argparse.ArgumentParser,
    *,
    help_text: str = (
        "Write findings to a CSV file instead of the text report."
    ),
) -> None:
    """Attach a standardized ``--csv`` output path flag.

    :param parser: Target parser.
    :param help_text: Override help string for CLIs whose
        CSV payload is not a "report".
    """
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help=help_text,
    )


__all__ = [
    "ARTICLES_DEFAULT_DB",
    "KG_DEFAULT_DB",
    "add_csv_output_argument",
    "add_db_argument",
    "add_dry_run_argument",
    "require_db_unless",
]
