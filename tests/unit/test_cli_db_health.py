"""Tests for the db_health CLI."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unstructured_mapping.cli.db_health import _run_report


def _make_db(path: Path) -> sqlite3.Connection:
    """Create a minimal articles DB matching production schema."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE articles ("
        "  url TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  body TEXT NOT NULL,"
        "  source TEXT NOT NULL,"
        "  published TEXT,"
        "  scraped_at TEXT NOT NULL,"
        "  document_id TEXT NOT NULL UNIQUE"
        ")"
    )
    return conn


def _insert(
    conn: sqlite3.Connection,
    url: str,
    scraped_at: datetime,
) -> None:
    """Insert one article with a body long enough to pass checks."""
    conn.execute(
        "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            url,
            "title",
            "b" * 100,
            "bbc",
            None,
            scraped_at.isoformat(),
            url,
        ),
    )


def test_daily_coverage_flags_past_days_with_no_articles(tmp_path):
    """A past day with zero articles is reported as a GAP."""
    conn = _make_db(tmp_path / "a.db")
    now = datetime.now(timezone.utc)
    # Articles only on today and 2 days ago — yesterday is a gap
    _insert(conn, "u1", now)
    _insert(conn, "u2", now - timedelta(days=2))
    conn.commit()

    report = _run_report(conn)
    conn.close()

    assert "<- GAP" in report
    assert "ALERT:" in report


def test_daily_coverage_no_gaps_when_every_day_filled(tmp_path):
    """No GAP markers when every past day in window has data."""
    conn = _make_db(tmp_path / "a.db")
    now = datetime.now(timezone.utc)
    for i in range(8):  # today plus 7 past days
        _insert(conn, f"u{i}", now - timedelta(days=i))
    conn.commit()

    report = _run_report(conn)
    conn.close()

    assert "<- GAP" not in report
    assert "ALERT:" not in report


def test_daily_coverage_does_not_flag_today_without_articles(tmp_path):
    """Today is never marked as a gap — scraper may not have run."""
    conn = _make_db(tmp_path / "a.db")
    now = datetime.now(timezone.utc)
    # Only past days covered — today is empty but must not be flagged
    for i in range(1, 8):
        _insert(conn, f"u{i}", now - timedelta(days=i))
    conn.commit()

    report = _run_report(conn)
    conn.close()

    today_line = next(
        line for line in report.splitlines() if now.date().isoformat() in line
    )
    assert "<- GAP" not in today_line
