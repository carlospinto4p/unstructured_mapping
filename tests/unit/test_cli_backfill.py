"""Tests for the backfill CLI."""

from datetime import date
from unittest.mock import patch

import pytest

from unstructured_mapping.cli.backfill import main
from unstructured_mapping.web_scraping.models import Article


def _article(url: str) -> Article:
    return Article(
        title="t",
        body="b" * 100,
        url=url,
        source="ap",
    )


def test_main_invokes_fetch_range_for_every_source_when_all(tmp_path):
    """``--source all`` must fan out to every known archive source."""
    db = tmp_path / "a.db"
    sources_called: list[str] = []

    def fake_fetch_range(source, from_date, until_date, **_):
        sources_called.append(source)
        return [_article(f"u-{source}")]

    with patch(
        "unstructured_mapping.cli.backfill.fetch_range",
        side_effect=fake_fetch_range,
    ):
        main(
            [
                "--from",
                "2026-04-17",
                "--until",
                "2026-04-17",
                "--source",
                "all",
                "--db",
                str(db),
            ]
        )

    assert sorted(sources_called) == ["ap", "bbc", "reuters"]


def test_main_single_source_only_calls_that_source(tmp_path):
    """``--source ap`` must not call fetch_range for other sources."""
    db = tmp_path / "a.db"
    sources_called: list[str] = []

    def fake_fetch_range(source, from_date, until_date, **_):
        sources_called.append(source)
        return []

    with patch(
        "unstructured_mapping.cli.backfill.fetch_range",
        side_effect=fake_fetch_range,
    ):
        main(
            [
                "--from",
                "2026-04-17",
                "--until",
                "2026-04-17",
                "--source",
                "ap",
                "--db",
                str(db),
            ]
        )

    assert sources_called == ["ap"]


def test_main_rejects_reversed_date_range(tmp_path):
    """``--from`` after ``--until`` must fail fast with SystemExit."""
    db = tmp_path / "a.db"
    with pytest.raises(SystemExit):
        main(
            [
                "--from",
                "2026-04-20",
                "--until",
                "2026-04-17",
                "--db",
                str(db),
            ]
        )


def test_main_rejects_non_iso_date(tmp_path):
    """Non-ISO date strings must raise SystemExit (argparse)."""
    db = tmp_path / "a.db"
    with pytest.raises(SystemExit):
        main(
            [
                "--from",
                "17-04-2026",
                "--until",
                "2026-04-17",
                "--db",
                str(db),
            ]
        )


def test_main_passes_date_range_through_unchanged(tmp_path):
    """Dates reach fetch_range exactly as parsed."""
    db = tmp_path / "a.db"
    calls: list[tuple[date, date]] = []

    def fake_fetch_range(source, from_date, until_date, **_):
        calls.append((from_date, until_date))
        return []

    with patch(
        "unstructured_mapping.cli.backfill.fetch_range",
        side_effect=fake_fetch_range,
    ):
        main(
            [
                "--from",
                "2026-04-17",
                "--until",
                "2026-04-20",
                "--source",
                "ap",
                "--db",
                str(db),
            ]
        )

    assert calls == [(date(2026, 4, 17), date(2026, 4, 20))]
