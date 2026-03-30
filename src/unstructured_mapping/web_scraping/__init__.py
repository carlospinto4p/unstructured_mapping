"""Web scraping module for fetching unstructured text."""

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.reuters import (
    ReutersScraper,
)

__all__ = ["Article", "ReutersScraper", "Scraper"]
