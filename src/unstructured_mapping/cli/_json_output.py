"""Shared JSON serialisation helpers for CLI commands.

Several CLIs hand-roll the same ``json.dumps(..., indent=2, default=str)``
→ stdout-or-file write pattern. This module centralises it so the
serialisation shape (indentation, type coercion, encoding) can
evolve in one place.

Why ``default=str``
-------------------

KG payloads routinely contain :class:`~datetime.datetime` objects
(timestamps), :class:`~uuid.UUID` entity IDs, and
:class:`~pathlib.Path` references. ``default=str`` coerces all of
these to their natural string representation without requiring
callers to pre-serialise fields.
"""

import json
import sys
from collections.abc import Iterable
from pathlib import Path


def emit_json(
    payload: object,
    dest: Path | None = None,
) -> None:
    """Serialise ``payload`` as indented JSON to ``dest`` or stdout.

    :param payload: JSON-serialisable object.
        :class:`~datetime.datetime`, :class:`~uuid.UUID`, and
        :class:`~pathlib.Path` values are coerced to strings
        automatically.
    :param dest: Target file path. When ``None`` the output is
        written to stdout.
    """
    text = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    if dest is None:
        sys.stdout.write(text + "\n")
    else:
        dest.write_text(text, encoding="utf-8")


def emit_jsonl(
    rows: Iterable[object],
    dest: Path | None = None,
) -> int:
    """Serialise ``rows`` as newline-delimited JSON to ``dest`` or stdout.

    Each row is one compact JSON line followed by ``\\n``.
    :class:`~datetime.datetime`, :class:`~uuid.UUID`, and
    :class:`~pathlib.Path` values are coerced to strings automatically.

    :param rows: Iterable of JSON-serialisable objects.
    :param dest: Target file path. When ``None`` the output is
        written to stdout.
    :return: Number of rows written.
    """
    count = 0
    if dest is None:
        for row in rows:
            sys.stdout.write(json.dumps(row, default=str, ensure_ascii=False))
            sys.stdout.write("\n")
            count += 1
    else:
        with dest.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str, ensure_ascii=False))
                fh.write("\n")
                count += 1
    return count


__all__ = ["emit_json", "emit_jsonl"]
