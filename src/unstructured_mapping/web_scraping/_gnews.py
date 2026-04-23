"""Shared Google News decoding + trafilatura helpers.

Both the live :mod:`.ap` scraper and the :mod:`.backfill` archive
scraper consume Google News redirect URLs. Decoding them with
:mod:`googlenewsdecoder` and extracting body text with
:mod:`trafilatura` is identical in both paths, so the logic lives
here instead of being duplicated per scraper.

Module is internal (leading underscore) — not re-exported from
:mod:`.web_scraping`. Error-handling contracts:

- :func:`_has_scraping_deps` returns a bool so callers can decide
  whether to degrade gracefully (AP) or fail fast (backfill).
- :func:`_resolve_gnews_url` and :func:`_extract_text` both return
  empty strings on failure so the pipeline can skip the article
  instead of raising.
"""

import logging

logger = logging.getLogger(__name__)

# Exceptions swallowed when decoding gnews URLs or fetching/extracting
# article HTML. Module-level tuples so the except clauses stay simple
# references — local formatters occasionally mangle inline tuples
# (stripping parens into Python-2-style syntax).
_DECODE_ERRORS = (ValueError, KeyError, OSError)
_EXTRACT_ERRORS = (OSError, ValueError)


def _has_scraping_deps() -> bool:
    """Return ``True`` when googlenewsdecoder + trafilatura import.

    :return: Whether both optional deps are installed.
    """
    try:
        import googlenewsdecoder  # noqa: F401
        import trafilatura  # noqa: F401
    except ImportError:
        return False
    return True


def _resolve_gnews_url(gnews_url: str) -> str:
    """Decode a Google News redirect URL to its source URL.

    :param gnews_url: Google News redirect URL.
    :return: Resolved source URL, or empty string on failure.
    """
    from googlenewsdecoder import new_decoderv1

    try:
        result = new_decoderv1(gnews_url)
    except _DECODE_ERRORS:
        logger.warning("Failed to decode %s", gnews_url, exc_info=True)
        return ""
    if not result.get("status"):
        logger.warning("Decoder failed for %s", gnews_url)
        return ""
    return result["decoded_url"]


def _extract_text(url: str) -> str:
    """Fetch an article page and extract main text with trafilatura.

    :param url: Direct article URL (after gnews decoding).
    :return: Extracted text, or empty string on failure.
    """
    import trafilatura

    try:
        html = trafilatura.fetch_url(url)
        text = trafilatura.extract(html) if html else ""
    except _EXTRACT_ERRORS:
        logger.warning("Failed to extract %s", url, exc_info=True)
        return ""
    return text or ""
