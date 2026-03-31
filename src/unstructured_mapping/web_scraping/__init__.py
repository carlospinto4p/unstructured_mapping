"""Web scraping module for fetching unstructured text."""

from unstructured_mapping.web_scraping.ap import APScraper
from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.bbc import (
    BBC_FEEDS,
    BBCScraper,
)
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.reuters import (
    ReutersScraper,
)
from unstructured_mapping.web_scraping.storage import (
    ArticleStore,
)

__all__ = [
    "APScraper",
    "Article",
    "ArticleStore",
    "BBC_FEEDS",
    "BBCScraper",
    "ReutersScraper",
    "Scraper",
]
