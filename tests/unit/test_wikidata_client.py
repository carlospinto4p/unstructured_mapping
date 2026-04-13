"""Tests for the Wikidata SPARQL client.

The client is exercised with a fake :class:`httpx.Client`
built on :class:`httpx.MockTransport` so no network calls
are made.
"""

import httpx
import pytest

from unstructured_mapping.wikidata.client import (
    SparqlClient,
    SparqlError,
)


def _json_response(bindings: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"results": {"bindings": bindings}},
    )


def _mock_client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        transport=transport,
        headers={"Accept": "application/sparql-results+json"},
    )


def test_query_returns_bindings():
    bindings = [{"item": {"type": "uri", "value": "X"}}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"query=" in request.content
        return _json_response(bindings)

    with SparqlClient(client=_mock_client(handler)) as client:
        assert client.query("SELECT *") == bindings


def test_query_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        "unstructured_mapping.wikidata.client.time.sleep",
        lambda _: None,
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return _json_response([])

    with SparqlClient(client=_mock_client(handler)) as client:
        assert client.query("SELECT *") == []
    assert calls["n"] == 2


def test_query_raises_after_max_retries(monkeypatch):
    monkeypatch.setattr(
        "unstructured_mapping.wikidata.client.time.sleep",
        lambda _: None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with SparqlClient(client=_mock_client(handler)) as client:
        with pytest.raises(SparqlError):
            client.query("SELECT *")


def test_query_raises_on_non_retryable_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad query")

    with SparqlClient(client=_mock_client(handler)) as client:
        with pytest.raises(SparqlError):
            client.query("SELECT *")
