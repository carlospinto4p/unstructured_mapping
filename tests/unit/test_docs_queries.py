"""Smoke tests for ``docs/examples/queries.sql``.

Each query block is parsed out and executed against a
fresh :class:`KnowledgeStore` so schema drift (renamed
columns, removed tables) immediately breaks the cookbook.
We don't assert on row content — the queries are analyst
cookbook entries, not business logic — only that they
run without syntax errors against the current schema.
"""

import re
from pathlib import Path

import pytest

from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)

_QUERY_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "examples" / "queries.sql"
)

# Named parameters the cookbook uses. We bind harmless
# placeholders so the queries can actually run.
_DUMMY_PARAMS = {
    "entity_id": "nonexistent",
    "run_id": "nonexistent",
}


def _split_statements(sql: str) -> list[str]:
    """Split the cookbook into individual SQL statements.

    Strips full-line ``--`` comments so the splitter sees
    one statement per terminator. Leading / trailing
    blanks are stripped per statement.
    """
    lines = [
        ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")
    ]
    body = "\n".join(lines)
    parts = [p.strip() for p in body.split(";")]
    return [p for p in parts if p]


def test_query_file_exists():
    assert _QUERY_FILE.exists(), _QUERY_FILE


def test_query_file_contains_ten_statements():
    """The cookbook promises ten labelled queries — keep
    that count honest so the TOC-style numbering in the
    comments matches reality."""
    sql = _QUERY_FILE.read_text(encoding="utf-8")
    assert len(_split_statements(sql)) == 10


@pytest.mark.parametrize("idx", list(range(10)))
def test_cookbook_query_executes(idx, tmp_path):
    """Every statement parses and executes against an
    empty KG schema without raising."""
    sql = _QUERY_FILE.read_text(encoding="utf-8")
    statements = _split_statements(sql)
    statement = statements[idx]
    needed = set(re.findall(r":(\w+)", statement))
    params = {k: _DUMMY_PARAMS[k] for k in needed if k in _DUMMY_PARAMS}
    with KnowledgeStore(db_path=tmp_path / "kg.db") as store:
        # execute + fetchall shakes out both parse and
        # run-time errors (missing columns surface here).
        store._conn.execute(  # noqa: SLF001
            statement, params
        ).fetchall()
