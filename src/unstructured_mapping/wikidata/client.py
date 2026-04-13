"""SPARQL client for the Wikidata Query Service.

A thin wrapper around :mod:`httpx` that submits SPARQL
queries to ``query.wikidata.org`` and returns the parsed
JSON result. Kept intentionally minimal:

- No query-building DSL — callers pass a raw SPARQL string
  (see :mod:`unstructured_mapping.wikidata.queries`).
- Retries on transient errors (HTTP 429 and 5xx) with a
  short exponential backoff. Hard-limited retry count so a
  misconfigured query cannot spin forever.
- A polite ``User-Agent`` header, as required by the
  Wikidata endpoint's etiquette rules.

The client has no knowledge of the KG schema; mapping
from SPARQL rows to :class:`Entity` instances is the job
of :mod:`unstructured_mapping.wikidata.mapper`.
"""

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ENDPOINT = "https://query.wikidata.org/sparql"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_USER_AGENT = (
    "unstructured_mapping/0.x "
    "(https://github.com/; KG seed pipeline)"
)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


class SparqlError(RuntimeError):
    """Raised when a SPARQL request fails after retries."""


class SparqlClient:
    """Submits SPARQL queries to the Wikidata endpoint.

    :param endpoint: SPARQL endpoint URL. Defaults to the
        public Wikidata Query Service.
    :param user_agent: Value for the ``User-Agent`` header.
        Wikidata requires a descriptive agent string.
    :param timeout: Per-request timeout in seconds.
    :param client: Optional pre-configured
        :class:`httpx.Client`. When ``None``, the instance
        owns its own client and closes it on ``__exit__``.
    """

    def __init__(
        self,
        *,
        endpoint: str = _ENDPOINT,
        user_agent: str = _DEFAULT_USER_AGENT,
        timeout: float = _DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/sparql-results+json",
            },
        )

    def __enter__(self) -> "SparqlClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._owns_client:
            self._client.close()

    def query(self, sparql: str) -> list[dict[str, Any]]:
        """Run a SPARQL query and return result bindings.

        :param sparql: The SPARQL query string.
        :return: A list of binding rows. Each row is a
            ``dict`` mapping variable name to the raw
            Wikidata binding (``{"type": ..., "value": ...}``).
        :raises SparqlError: On network failure, non-2xx
            response, or malformed JSON after retries.
        """
        response = self._request_with_retry(sparql)
        try:
            data = response.json()
        except ValueError as exc:
            raise SparqlError(
                "Wikidata returned non-JSON payload"
            ) from exc
        bindings = (
            data.get("results", {}).get("bindings", [])
        )
        logger.debug(
            "Wikidata returned %d bindings", len(bindings)
        )
        return bindings

    def _request_with_retry(
        self, sparql: str
    ) -> httpx.Response:
        """Submit the query with exponential backoff retry."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.post(
                    self._endpoint,
                    data={"query": sparql},
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "Wikidata request failed (attempt %d): %s",
                    attempt + 1,
                    exc,
                )
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise SparqlError(
                        "Wikidata returned HTTP "
                        f"{response.status_code}: "
                        f"{response.text[:200]}"
                    )
                last_exc = SparqlError(
                    f"HTTP {response.status_code}"
                )
                logger.warning(
                    "Wikidata HTTP %d (attempt %d)",
                    response.status_code,
                    attempt + 1,
                )
            if attempt + 1 < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE ** attempt)
        raise SparqlError(
            "Wikidata request failed after "
            f"{_MAX_RETRIES} attempts"
        ) from last_exc
