"""Check health and sanity of the articles database.

Usage::

    uv run python -m unstructured_mapping.cli.db_health
    uv run python -m unstructured_mapping.cli.db_health --db data/articles.db
"""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_DB = Path("data/articles.db")


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return sqlite3.connect(str(db_path))


def _run_report(conn: sqlite3.Connection) -> str:
    """Build a full health report and return it as text."""
    lines: list[str] = []

    # --- Overall counts ---
    total = conn.execute(
        "SELECT COUNT(*) FROM articles"
    ).fetchone()[0]
    lines.append(f"Total articles: {total}")

    if total == 0:
        lines.append("Database is empty — nothing to report.")
        return "\n".join(lines)

    # --- Per-source counts ---
    rows = conn.execute(
        "SELECT source, COUNT(*) FROM articles "
        "GROUP BY source ORDER BY source"
    ).fetchall()
    lines.append("")
    lines.append("Articles by source:")
    for src, cnt in rows:
        lines.append(f"  {src:>10s}  {cnt}")

    # --- Last scrape per source ---
    lines.append("")
    lines.append("Last scrape per source:")
    rows = conn.execute(
        "SELECT source, MAX(scraped_at) FROM articles "
        "GROUP BY source ORDER BY source"
    ).fetchall()
    now = datetime.now(timezone.utc)
    for src, last in rows:
        ts = datetime.fromisoformat(last)
        ago = now - ts
        hours = ago.total_seconds() / 3600
        lines.append(
            f"  {src:>10s}  {last}  ({hours:.1f}h ago)"
        )

    # --- Articles per scrape batch (by scraped_at) ---
    lines.append("")
    lines.append("Recent scrape batches (last 5):")
    rows = conn.execute(
        "SELECT scraped_at, COUNT(*), "
        "GROUP_CONCAT(DISTINCT source) "
        "FROM articles "
        "GROUP BY scraped_at "
        "ORDER BY scraped_at DESC LIMIT 5"
    ).fetchall()
    for ts, cnt, sources in rows:
        lines.append(f"  {ts}  {cnt} articles  [{sources}]")

    # --- Gaps: days with no articles ---
    lines.append("")
    lines.append("Daily coverage (last 7 days):")
    rows = conn.execute(
        "SELECT DATE(scraped_at) AS day, COUNT(*) "
        "FROM articles "
        "WHERE scraped_at >= DATE('now', '-7 days') "
        "GROUP BY day ORDER BY day"
    ).fetchall()
    if rows:
        for day, cnt in rows:
            lines.append(f"  {day}  {cnt} articles")
    else:
        lines.append("  No articles in the last 7 days.")

    # --- Data quality checks ---
    lines.append("")
    lines.append("Data quality:")

    empty_body = conn.execute(
        "SELECT COUNT(*) FROM articles "
        "WHERE body = '' OR body IS NULL"
    ).fetchone()[0]
    lines.append(f"  Empty bodies:      {empty_body}")

    empty_title = conn.execute(
        "SELECT COUNT(*) FROM articles "
        "WHERE title = '' OR title IS NULL"
    ).fetchone()[0]
    lines.append(f"  Empty titles:      {empty_title}")

    no_date = conn.execute(
        "SELECT COUNT(*) FROM articles "
        "WHERE published IS NULL"
    ).fetchone()[0]
    lines.append(
        f"  Missing published: {no_date}"
    )

    short_body = conn.execute(
        "SELECT COUNT(*) FROM articles "
        "WHERE LENGTH(body) < 50 AND body != ''"
    ).fetchone()[0]
    lines.append(
        f"  Short bodies (<50): {short_body}"
    )

    # --- DB file size ---
    lines.append("")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    size = Path(db_path).stat().st_size
    if size < 1024 * 1024:
        lines.append(f"Database size: {size / 1024:.1f} KB")
    else:
        lines.append(
            f"Database size: {size / (1024 * 1024):.1f} MB"
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the db-health CLI."""
    p = argparse.ArgumentParser(
        description="Check articles database health.",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help="Path to SQLite database "
        "(default: data/articles.db).",
    )
    args = p.parse_args(argv)
    conn = _connect(args.db)
    try:
        print(_run_report(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
