"""Tests for pipeline entity resolution."""

import json

import pytest

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityType,
)
from unstructured_mapping.pipeline.llm_parsers import (
    Pass1ValidationError,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProvider,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
    ResolvedMention,
    ResolutionResult,
)
from unstructured_mapping.pipeline.resolution import (
    AliasResolver,
    LLMEntityResolver,
    _extract_snippet,
)


# -- Helpers --


def make_chunk(
    text: str,
    doc_id: str = "doc1",
    section: str | None = None,
) -> Chunk:
    return Chunk(
        document_id=doc_id,
        chunk_index=0,
        text=text,
        section_name=section,
    )


def make_mention(
    form: str,
    start: int,
    end: int,
    candidates: tuple[str, ...] = (),
) -> Mention:
    return Mention(
        surface_form=form,
        span_start=start,
        span_end=end,
        candidate_ids=candidates,
    )


# -- ResolvedMention model tests --


def test_resolved_mention_fields():
    rm = ResolvedMention(
        entity_id="e1",
        surface_form="Apple",
        context_snippet="...bought Apple stock...",
    )
    assert rm.entity_id == "e1"
    assert rm.section_name is None


def test_resolved_mention_with_section():
    rm = ResolvedMention(
        entity_id="e1",
        surface_form="Apple",
        context_snippet="ctx",
        section_name="Q&A",
    )
    assert rm.section_name == "Q&A"


def test_resolved_mention_frozen():
    rm = ResolvedMention(
        entity_id="e1",
        surface_form="x",
        context_snippet="ctx",
    )
    with pytest.raises(AttributeError):
        rm.entity_id = "e2"  # type: ignore[misc]


# -- ResolutionResult model tests --


def test_resolution_result_defaults():
    r = ResolutionResult()
    assert r.resolved == ()
    assert r.unresolved == ()


def test_resolution_result_frozen():
    r = ResolutionResult()
    with pytest.raises(AttributeError):
        r.resolved = ()  # type: ignore[misc]


# -- Context snippet extraction tests --


def test_snippet_short_text():
    text = "Buy Apple now"
    snippet = _extract_snippet(text, 4, 9)
    assert "Apple" in snippet
    # Short text — no ellipsis needed
    assert not snippet.startswith("...")
    assert not snippet.endswith("...")


def test_snippet_adds_leading_ellipsis():
    text = "X" * 200 + " Apple stock is rising"
    start = 201
    end = 206
    snippet = _extract_snippet(text, start, end)
    assert snippet.startswith("...")
    assert "Apple" in snippet


def test_snippet_adds_trailing_ellipsis():
    text = "Apple stock is rising " + "X" * 200
    snippet = _extract_snippet(text, 0, 5)
    assert snippet.endswith("...")
    assert "Apple" in snippet


def test_snippet_both_ellipsis():
    text = (
        "X" * 200
        + " The Fed raised rates today "
        + "Y" * 200
    )
    start = text.index("Fed")
    end = start + 3
    snippet = _extract_snippet(text, start, end)
    assert snippet.startswith("...")
    assert snippet.endswith("...")
    assert "Fed" in snippet


def test_snippet_custom_window():
    text = "The Federal Reserve raised interest rates"
    start = 4
    end = 19  # "Federal Reserve"
    snippet = _extract_snippet(
        text, start, end, window=5
    )
    assert "Federal Reserve" in snippet
    assert len(snippet) < len(text) + 10


def test_snippet_at_text_start():
    text = "Apple announced earnings today for Q4"
    snippet = _extract_snippet(text, 0, 5, window=50)
    assert snippet.startswith("Apple")
    assert not snippet.startswith("...")


def test_snippet_at_text_end():
    text = "Good results from Apple"
    end = len(text)
    start = end - 5  # "Apple"
    snippet = _extract_snippet(text, start, end)
    assert snippet.endswith("Apple")
    assert not snippet.endswith("...")


# -- AliasResolver tests --


def test_resolver_single_candidate_resolves():
    resolver = AliasResolver()
    chunk = make_chunk("The Fed raised rates today.")
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 1
    assert len(result.unresolved) == 0
    assert result.resolved[0].entity_id == "fed_id"
    assert result.resolved[0].surface_form == "Fed"


def test_resolver_zero_candidates_unresolved():
    resolver = AliasResolver()
    chunk = make_chunk("NewCo announced a deal.")
    mentions = (
        make_mention("NewCo", 0, 5, ()),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].surface_form == "NewCo"


def test_resolver_multi_candidates_unresolved():
    resolver = AliasResolver()
    chunk = make_chunk("Buy Apple now.")
    mentions = (
        make_mention("Apple", 4, 9, ("corp", "stock")),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 0
    assert len(result.unresolved) == 1
    assert set(
        result.unresolved[0].candidate_ids
    ) == {"corp", "stock"}


def test_resolver_mixed_mentions():
    resolver = AliasResolver()
    text = "The Fed and Apple announced a deal."
    chunk = make_chunk(text)
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
        make_mention(
            "Apple", 12, 17, ("corp", "stock")
        ),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 1
    assert len(result.unresolved) == 1
    assert result.resolved[0].entity_id == "fed_id"
    assert (
        result.unresolved[0].surface_form == "Apple"
    )


def test_resolver_empty_mentions():
    resolver = AliasResolver()
    chunk = make_chunk("Some text.")
    result = resolver.resolve(chunk, ())
    assert result.resolved == ()
    assert result.unresolved == ()


def test_resolver_context_snippet_contains_mention():
    resolver = AliasResolver()
    chunk = make_chunk("The Fed raised rates on Wednesday.")
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert "Fed" in result.resolved[0].context_snippet


def test_resolver_inherits_section_name():
    resolver = AliasResolver()
    chunk = make_chunk(
        "The Fed raised rates.",
        section="Prepared remarks",
    )
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert (
        result.resolved[0].section_name
        == "Prepared remarks"
    )


def test_resolver_section_name_none_by_default():
    resolver = AliasResolver()
    chunk = make_chunk("The Fed raised rates.")
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert result.resolved[0].section_name is None


def test_resolver_custom_context_window():
    resolver = AliasResolver(context_window=10)
    text = (
        "A" * 50
        + " Fed "
        + "B" * 50
    )
    start = 51
    end = 54
    chunk = make_chunk(text)
    mentions = (
        make_mention("Fed", start, end, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    snippet = result.resolved[0].context_snippet
    # With window=10, snippet should be much shorter
    # than the full text
    assert len(snippet) < len(text)
    assert "Fed" in snippet


def test_resolver_multiple_resolved():
    resolver = AliasResolver()
    text = "The Fed and the ECB held rates."
    chunk = make_chunk(text)
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
        make_mention("ECB", 16, 19, ("ecb_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 2
    ids = {rm.entity_id for rm in result.resolved}
    assert ids == {"fed_id", "ecb_id"}


def test_resolver_returns_resolution_result():
    resolver = AliasResolver()
    chunk = make_chunk("text")
    result = resolver.resolve(chunk, ())
    assert isinstance(result, ResolutionResult)


def test_resolver_resolved_are_tuples():
    resolver = AliasResolver()
    chunk = make_chunk("The Fed.")
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert isinstance(result.resolved, tuple)
    assert isinstance(result.unresolved, tuple)


# -- LLMEntityResolver helpers --


class _FakeProvider(LLMProvider):
    """Fake LLM that returns a preset response."""

    provider_name = "fake"
    supports_json_mode = True
    model_name = "fake-1"
    context_window = 4096

    def __init__(self, response: str = "{}"):
        self._response = response
        self.calls: list[
            tuple[str, str | None, bool]
        ] = []

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append((prompt, system, json_mode))
        return self._response


def _make_kg_entity(
    entity_id: str,
    name: str,
    aliases: tuple[str, ...] = (),
) -> Entity:
    return Entity(
        entity_id=entity_id,
        canonical_name=name,
        entity_type=EntityType.ORGANIZATION,
        description=f"Test entity {name}",
        aliases=aliases,
    )


def _llm_response(*entities):
    """Build a valid pass 1 JSON response string."""
    return json.dumps({"entities": list(entities)})


def _resolved_entry(
    entity_id, surface_form, snippet="...ctx..."
):
    return {
        "surface_form": surface_form,
        "entity_id": entity_id,
        "new_entity": None,
        "context_snippet": snippet,
    }


def _new_entry(
    surface_form,
    canonical_name,
    entity_type="organization",
    description="A new entity.",
    snippet="...ctx...",
):
    return {
        "surface_form": surface_form,
        "entity_id": None,
        "new_entity": {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "description": description,
            "aliases": [],
        },
        "context_snippet": snippet,
    }


# -- LLMEntityResolver tests --


def test_llm_resolver_resolves_entity():
    """LLM response with entity_id produces resolved."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    response = _llm_response(
        _resolved_entry("fed_id", "the Fed")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk("the Fed raised rates")
    mentions = (
        make_mention(
            "the Fed", 0, 7, ("fed_id",)
        ),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 1
    assert result.resolved[0].entity_id == "fed_id"
    assert result.resolved[0].surface_form == "the Fed"


def test_llm_resolver_proposes_new_entity():
    """LLM new_entity response produces a proposal."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    response = _llm_response(
        _new_entry("Powell", "Jerome Powell", "person")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk("Powell spoke at the Fed")
    mentions = (
        make_mention("Powell", 0, 6, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 0
    assert len(resolver.proposals) == 1
    assert (
        resolver.proposals[0].canonical_name
        == "Jerome Powell"
    )
    assert (
        resolver.proposals[0].entity_type
        == EntityType.PERSON
    )


def test_llm_resolver_mixed_resolved_and_proposals():
    """LLM can return both resolved and new entities."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    response = _llm_response(
        _resolved_entry("fed_id", "the Fed"),
        _new_entry("Powell", "Jerome Powell", "person"),
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk(
        "the Fed Chair Powell announced rates"
    )
    mentions = (
        make_mention(
            "the Fed", 0, 7, ("fed_id",)
        ),
        make_mention("Powell", 14, 20),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 1
    assert len(resolver.proposals) == 1


def test_llm_resolver_empty_mentions():
    """No mentions → empty result, no LLM call."""
    provider = _FakeProvider()
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lambda _: None,
    )
    chunk = make_chunk("some text")
    result = resolver.resolve(chunk, ())
    assert result == ResolutionResult()
    assert len(provider.calls) == 0


def test_llm_resolver_calls_provider():
    """Resolver passes system prompt and json_mode."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    response = _llm_response(
        _resolved_entry("fed_id", "Fed")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk("the Fed raised rates")
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    resolver.resolve(chunk, mentions)
    assert len(provider.calls) == 1
    prompt, system, json_mode = provider.calls[0]
    assert system is not None
    assert "Fed" in prompt
    assert json_mode is True


def test_llm_resolver_deduplicates_candidates():
    """Same entity_id from multiple mentions is fetched
    only once."""
    fed = _make_kg_entity(
        "fed_id", "Federal Reserve",
        aliases=("the Fed", "Fed"),
    )
    calls: list[str] = []

    def tracking_lookup(eid):
        calls.append(eid)
        return {"fed_id": fed}.get(eid)

    response = _llm_response(
        _resolved_entry("fed_id", "the Fed")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=tracking_lookup,
    )
    chunk = make_chunk("the Fed and Fed again")
    mentions = (
        make_mention(
            "the Fed", 0, 7, ("fed_id",)
        ),
        make_mention(
            "Fed", 12, 15, ("fed_id",)
        ),
    )
    resolver.resolve(chunk, mentions)
    assert calls.count("fed_id") == 1


def test_llm_resolver_skips_missing_candidate():
    """Missing entity in lookup is silently skipped."""
    response = _llm_response()
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lambda _: None,
    )
    chunk = make_chunk("unknown entity text")
    mentions = (
        make_mention(
            "unknown", 0, 7, ("missing_id",)
        ),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 0


def test_llm_resolver_validation_error_propagates():
    """Invalid LLM response raises Pass1ValidationError."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    provider = _FakeProvider("not valid json")
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk("the Fed")
    mentions = (
        make_mention("Fed", 4, 7, ("fed_id",)),
    )
    with pytest.raises(Pass1ValidationError):
        resolver.resolve(chunk, mentions)


def test_llm_resolver_section_name_propagated():
    """Section name from chunk appears on resolved."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    response = _llm_response(
        _resolved_entry("fed_id", "the Fed")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk(
        "the Fed raised rates",
        section="Economy",
    )
    mentions = (
        make_mention(
            "the Fed", 0, 7, ("fed_id",)
        ),
    )
    result = resolver.resolve(chunk, mentions)
    assert result.resolved[0].section_name == "Economy"


def test_llm_resolver_prev_entities_in_prompt():
    """Previous entities appear in the user prompt."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    prev = [
        ResolvedMention(
            entity_id="ecb_id",
            surface_form="ECB",
            context_snippet="...ECB...",
        )
    ]
    response = _llm_response(
        _resolved_entry("fed_id", "the Fed")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
        prev_entities=prev,
    )
    chunk = make_chunk("the Fed raised rates")
    mentions = (
        make_mention(
            "the Fed", 0, 7, ("fed_id",)
        ),
    )
    resolver.resolve(chunk, mentions)
    prompt = provider.calls[0][0]
    assert "ECB" in prompt


def test_llm_resolver_proposals_reset_each_call():
    """Proposals are cleared between resolve() calls."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    lookup = {"fed_id": fed}
    response1 = _llm_response(
        _new_entry("Powell", "Jerome Powell", "person")
    )
    provider = _FakeProvider(response1)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk("Powell spoke")
    mentions = (
        make_mention("Powell", 0, 6, ("fed_id",)),
    )
    resolver.resolve(chunk, mentions)
    assert len(resolver.proposals) == 1

    # Second call returns only resolved, no proposals.
    response2 = _llm_response(
        _resolved_entry("fed_id", "Fed")
    )
    provider._response = response2
    resolver.resolve(chunk, mentions)
    assert len(resolver.proposals) == 0


def test_llm_resolver_multiple_candidates():
    """Multiple candidate entities are sent to LLM."""
    fed = _make_kg_entity("fed_id", "Federal Reserve")
    ecb = _make_kg_entity("ecb_id", "ECB")
    lookup = {"fed_id": fed, "ecb_id": ecb}
    response = _llm_response(
        _resolved_entry("fed_id", "the bank")
    )
    provider = _FakeProvider(response)
    resolver = LLMEntityResolver(
        provider=provider,
        entity_lookup=lookup.get,
    )
    chunk = make_chunk("the bank raised rates")
    mentions = (
        make_mention(
            "the bank", 0, 8,
            ("fed_id", "ecb_id"),
        ),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 1
    prompt = provider.calls[0][0]
    assert "Federal Reserve" in prompt
    assert "ECB" in prompt
