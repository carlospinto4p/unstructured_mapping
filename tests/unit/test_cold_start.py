"""Tests for cold-start entity discovery."""

import json

import pytest

from tests.unit.conftest import (
    FakeProvider,
    make_article,
    make_chunk,
)
from unstructured_mapping.knowledge_graph import (
    EntityType,
    KnowledgeStore,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    ColdStartEntityDiscoverer,
    NoopDetector,
    Pipeline,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProviderError,
)


# -- helpers ---------------------------------------------------


def _proposal_response(entities: list[dict]) -> str:
    return json.dumps({"entities": entities})


def _fed_entity(entity_id: str | None = None) -> dict:
    return {
        "surface_form": "the Fed",
        "entity_id": entity_id,
        "new_entity": (
            None
            if entity_id
            else {
                "canonical_name": "Federal Reserve",
                "entity_type": "organization",
                "subtype": "central_bank",
                "description": "US central bank.",
                "aliases": ["Fed"],
            }
        ),
        "context_snippet": "the Fed raised rates",
    }


def _chunk(text: str = "the Fed raised rates today"):
    return make_chunk(text)


def _article(body: str = "The Fed raised rates."):
    return make_article(body=body, title="News")


# -- NoopDetector ---------------------------------------------


def test_noop_detector_returns_empty():
    assert NoopDetector().detect(_chunk("any text")) == ()


# -- ColdStartEntityDiscoverer --------------------------------


def test_discover_returns_proposals_from_llm():
    provider = FakeProvider(
        _proposal_response([_fed_entity()])
    )
    discoverer = ColdStartEntityDiscoverer(provider)
    proposals = discoverer.discover(_chunk())
    assert len(proposals) == 1
    p = proposals[0]
    assert p.canonical_name == "Federal Reserve"
    assert p.entity_type is EntityType.ORGANIZATION
    assert p.subtype == "central_bank"
    assert p.aliases == ("Fed",)


def test_discover_empty_text_returns_empty():
    provider = FakeProvider(_proposal_response([]))
    proposals = ColdStartEntityDiscoverer(
        provider
    ).discover(_chunk())
    assert proposals == ()


def test_discover_rejects_resolved_ids_with_empty_candidates():
    # If the LLM claims to resolve to an ID, validation
    # fails (empty candidate set) and retry eventually
    # raises LLMProviderError. This guards against the
    # LLM ignoring the "no candidates" instruction.
    provider = FakeProvider(
        _proposal_response(
            [_fed_entity(entity_id="some-existing-id")]
        )
    )
    with pytest.raises(LLMProviderError):
        ColdStartEntityDiscoverer(provider).discover(
            _chunk()
        )


def test_discover_prompt_has_no_candidates_block():
    provider = FakeProvider(_proposal_response([]))
    ColdStartEntityDiscoverer(provider).discover(
        _chunk("hello world")
    )
    prompt = provider.calls[0][0]
    assert "CANDIDATE ENTITIES" not in prompt
    assert "hello world" in prompt


# -- Pipeline integration -------------------------------------


def test_pipeline_cold_start_persists_entities(
    tmp_path,
):
    provider = FakeProvider(
        _proposal_response([_fed_entity()])
    )
    with KnowledgeStore(
        db_path=tmp_path / "kg.db"
    ) as store:
        pipeline = Pipeline(
            detector=NoopDetector(),
            resolver=AliasResolver(),
            store=store,
            cold_start_discoverer=(
                ColdStartEntityDiscoverer(provider)
            ),
        )
        result = pipeline.run([_article()])

        assert result.documents_processed == 1
        assert result.proposals_saved == 1
        assert result.provenances_saved == 1
        assert result.relationships_saved == 0

        fed = store.find_by_name("Federal Reserve")
        assert len(fed) == 1
        history = store.get_entity_history(
            fed[0].entity_id
        )
        assert history[0].reason == "proposed by LLM"


def test_pipeline_cold_start_bypasses_detector(
    tmp_path,
):
    """Detector must not be invoked in cold-start mode —
    the call to discoverer replaces detection."""

    class _ExplodingDetector(NoopDetector):
        def detect(self, chunk):
            raise AssertionError(
                "detector must not run in cold-start"
            )

    provider = FakeProvider(_proposal_response([]))
    with KnowledgeStore(
        db_path=tmp_path / "kg.db"
    ) as store:
        pipeline = Pipeline(
            detector=_ExplodingDetector(),
            resolver=AliasResolver(),
            store=store,
            cold_start_discoverer=(
                ColdStartEntityDiscoverer(provider)
            ),
        )
        result = pipeline.run([_article()])

    assert result.documents_processed == 1
    assert result.proposals_saved == 0


def test_pipeline_cold_start_respects_idempotency(
    tmp_path,
):
    provider = FakeProvider(
        _proposal_response([_fed_entity()])
    )
    with KnowledgeStore(
        db_path=tmp_path / "kg.db"
    ) as store:
        pipeline = Pipeline(
            detector=NoopDetector(),
            resolver=AliasResolver(),
            store=store,
            cold_start_discoverer=(
                ColdStartEntityDiscoverer(provider)
            ),
        )
        article = _article()
        pipeline.run([article])
        # Second run with same document_id should be
        # skipped via provenance check.
        second = pipeline.run([article])
        assert second.documents_processed == 0
        assert second.results[0].skipped is True
