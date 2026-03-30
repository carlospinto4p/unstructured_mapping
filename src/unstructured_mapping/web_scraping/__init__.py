"""Web scraping module for fetching unstructured text."""

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.bbc import BBCScraper
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.reuters import (
    ReutersScraper,
)
from unstructured_mapping.web_scraping.storage import (
    ArticleStore,
)

__all__ = [
    "Article",
    "ArticleStore",
    "BBCScraper",
    "ReutersScraper",
    "Scraper",
]
