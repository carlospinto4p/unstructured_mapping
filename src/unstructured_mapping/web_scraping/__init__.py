"""Web scraping module for fetching unstructured text."""

from unstructured_mapping.web_scraping._ap import APScraper
from unstructured_mapping.web_scraping._bbc import (
    BBC_FEEDS,
    BBCScraper,
)
from unstructured_mapping.web_scraping._reuters import (
    ReutersScraper,
)
from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.models import (
    Article,
    ExtractionResult,
)
from unstructured_mapping.web_scraping.storage import (
    ArticleStore,
)

__all__ = [
    "APScraper",
    "Article",
    "ArticleStore",
    "ExtractionResult",
    "BBC_FEEDS",
    "BBCScraper",
    "ReutersScraper",
    "Scraper",
]
