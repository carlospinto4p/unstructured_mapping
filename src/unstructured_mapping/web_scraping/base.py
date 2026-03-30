"""Base scraper interface."""

from abc import ABC, abstractmethod

from unstructured_mapping.web_scraping.models import Article


class Scraper(ABC):
    """Abstract base class for news scrapers.

    Subclasses must implement :attr:`source` and :meth:`fetch`.
    """

    @property
    @abstractmethod
    def source(self) -> str:
        """Short identifier for this news source."""

    @abstractmethod
    def fetch(self) -> list[Article]:
        """Fetch articles from the source.

        :return: List of scraped articles.
        """
