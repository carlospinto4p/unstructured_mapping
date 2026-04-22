"""Check health and sanity of the articles database.

Usage::

    uv run python -m unstructured_mapping.cli.db_health
    uv run python -m unstructured_mapping.cli.db_health --db data/articles.db
"""

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    ARTICLES_DEFAULT_DB,
    add_db_argument,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return sqlite3.connect(str(db_path))


def _section_overall(
    conn: sqlite3.Connection,
) -> tuple[list[str], int]:
    """Total article count.

    :return: Tuple of (report lines, total count).
    """
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return [f"Total articles: {total}"], total


def _section_by_source(
    conn: sqlite3.Connection,
) -> list[str]:
    """Article counts per source."""
    rows = conn.execute(
        "SELECT source, COUNT(*) FROM articles "
        "GROUP BY source ORDER BY source"
    ).fetchall()
    lines = ["", "Articles by source:"]
    for src, cnt in rows:
        lines.append(f"  {src:>10s}  {cnt}")
    return lines


def _section_last_scrape(
    conn: sqlite3.Connection,
) -> list[str]:
    """Most recent scrape timestamp per source."""
    rows = conn.execute(
        "SELECT source, MAX(scraped_at) FROM articles "
        "GROUP BY source ORDER BY source"
    ).fetchall()
    now = datetime.now(timezone.utc)
    lines = ["", "Last scrape per source:"]
    for src, last in rows:
        ts = datetime.fromisoformat(last)
        ago = now - ts
        hours = ago.total_seconds() / 3600
        lines.append(f"  {src:>10s}  {last}  ({hours:.1f}h ago)")
    return lines


def _section_recent_batches(
    conn: sqlite3.Connection,
) -> list[str]:
    """Last 5 scrape batches by timestamp."""
    rows = conn.execute(
        "SELECT scraped_at, COUNT(*), "
        "GROUP_CONCAT(DISTINCT source) "
        "FROM articles "
        "GROUP BY scraped_at "
        "ORDER BY scraped_at DESC LIMIT 5"
    ).fetchall()
    lines = ["", "Recent scrape batches (last 5):"]
    for ts, cnt, sources in rows:
        lines.append(f"  {ts}  {cnt} articles  [{sources}]")
    return lines


def _section_daily_coverage(
    conn: sqlite3.Connection,
) -> list[str]:
    """Article counts per day in the rolling 7-day window.

    Fills in zero-count days explicitly so gaps are visible, and
    flags any past day with no articles as ``<- GAP``. Today is
    never flagged — the scraper may not have run yet.
    """
    rows = conn.execute(
        "SELECT DATE(scraped_at) AS day, COUNT(*) "
        "FROM articles "
        "WHERE scraped_at >= DATE('now', '-7 days') "
        "GROUP BY day"
    ).fetchall()
    counts = {day: cnt for day, cnt in rows}

    today = datetime.now(timezone.utc).date()
    window = [today - timedelta(days=i) for i in range(7, -1, -1)]

    lines = ["", "Daily coverage (last 7 days):"]
    gap_count = 0
    for d in window:
        key = d.isoformat()
        cnt = counts.get(key, 0)
        marker = ""
        if cnt == 0 and d != today:
            marker = "  <- GAP"
            gap_count += 1
        lines.append(f"  {key}  {cnt:>4d} articles{marker}")
    if gap_count:
        lines.append(
            f"  ALERT: {gap_count} day(s) with no articles in window"
        )
    return lines


_QUALITY_CHECKS: list[tuple[str, str]] = [
    (
        "Empty bodies",
        "body = '' OR body IS NULL",
    ),
    (
        "Empty titles",
        "title = '' OR title IS NULL",
    ),
    (
        "Missing published",
        "published IS NULL",
    ),
    (
        "Short bodies (<50)",
        "LENGTH(body) < 50 AND body != ''",
    ),
]


def _section_data_quality(
    conn: sqlite3.Connection,
) -> list[str]:
    """Data quality checks on articles.

    Combines basic checks into a single table scan
    using ``SUM(CASE)`` aggregation.
    """
    lines = ["", "Data quality:"]
    sums = ", ".join(
        f"SUM(CASE WHEN {w} THEN 1 ELSE 0 END)" for _, w in _QUALITY_CHECKS
    )
    row = conn.execute(f"SELECT {sums} FROM articles").fetchone()
    for i, (label, _) in enumerate(_QUALITY_CHECKS):
        lines.append(f"  {label + ':':<18s} {row[i]}")

    col_names = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
    if "document_id" in col_names:
        dupe_ids = conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT document_id "
            "  FROM articles "
            "  GROUP BY document_id "
            "  HAVING COUNT(*) > 1"
            ")"
        ).fetchone()[0]
        lines.append(f"  {'Dupe document_ids:':<18s} {dupe_ids}")
    else:
        lines.append("  document_id:       MISSING (run migration)")
    return lines


def _section_db_size(
    conn: sqlite3.Connection,
) -> list[str]:
    """Database file size."""
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    size = Path(db_path).stat().st_size
    if size < 1024 * 1024:
        return [
            "",
            f"Database size: {size / 1024:.1f} KB",
        ]
    return [
        "",
        f"Database size: {size / (1024 * 1024):.1f} MB",
    ]


def _run_report(conn: sqlite3.Connection) -> str:
    """Build a full health report."""
    overall, total = _section_overall(conn)
    lines = overall

    if total == 0:
        lines.append("Database is empty — nothing to report.")
        return "\n".join(lines)

    for section in (
        _section_by_source,
        _section_last_scrape,
        _section_recent_batches,
        _section_daily_coverage,
        _section_data_quality,
        _section_db_size,
    ):
        lines.extend(section(conn))

    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Check articles database health.",
    )
    add_db_argument(
        p,
        default=ARTICLES_DEFAULT_DB,
        label="articles SQLite database",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point for the db-health CLI.

    ``db_health`` prints its report directly rather than
    routing through the logger: the output is the primary
    deliverable (like ``git status``), and adding log
    prefixes would obscure the aligned columns.
    """
    args = _build_parser().parse_args(argv)
    conn = _connect(args.db)
    try:
        print(_run_report(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
