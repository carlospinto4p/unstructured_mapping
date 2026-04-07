"""Tests for pipeline entity resolution."""

import pytest

from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
    ResolvedMention,
    ResolutionResult,
)
from unstructured_mapping.pipeline.resolution import (
    AliasResolver,
    _extract_snippet,
)


# -- Helpers --


def _chunk(
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


def _mention(
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
    chunk = _chunk("The Fed raised rates today.")
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 1
    assert len(result.unresolved) == 0
    assert result.resolved[0].entity_id == "fed_id"
    assert result.resolved[0].surface_form == "Fed"


def test_resolver_zero_candidates_unresolved():
    resolver = AliasResolver()
    chunk = _chunk("NewCo announced a deal.")
    mentions = (
        _mention("NewCo", 0, 5, ()),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].surface_form == "NewCo"


def test_resolver_multi_candidates_unresolved():
    resolver = AliasResolver()
    chunk = _chunk("Buy Apple now.")
    mentions = (
        _mention("Apple", 4, 9, ("corp", "stock")),
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
    chunk = _chunk(text)
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
        _mention(
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
    chunk = _chunk("Some text.")
    result = resolver.resolve(chunk, ())
    assert result.resolved == ()
    assert result.unresolved == ()


def test_resolver_context_snippet_contains_mention():
    resolver = AliasResolver()
    chunk = _chunk("The Fed raised rates on Wednesday.")
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert "Fed" in result.resolved[0].context_snippet


def test_resolver_inherits_section_name():
    resolver = AliasResolver()
    chunk = _chunk(
        "The Fed raised rates.",
        section="Prepared remarks",
    )
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert (
        result.resolved[0].section_name
        == "Prepared remarks"
    )


def test_resolver_section_name_none_by_default():
    resolver = AliasResolver()
    chunk = _chunk("The Fed raised rates.")
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
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
    chunk = _chunk(text)
    mentions = (
        _mention("Fed", start, end, ("fed_id",)),
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
    chunk = _chunk(text)
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
        _mention("ECB", 16, 19, ("ecb_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert len(result.resolved) == 2
    ids = {rm.entity_id for rm in result.resolved}
    assert ids == {"fed_id", "ecb_id"}


def test_resolver_returns_resolution_result():
    resolver = AliasResolver()
    chunk = _chunk("text")
    result = resolver.resolve(chunk, ())
    assert isinstance(result, ResolutionResult)


def test_resolver_resolved_are_tuples():
    resolver = AliasResolver()
    chunk = _chunk("The Fed.")
    mentions = (
        _mention("Fed", 4, 7, ("fed_id",)),
    )
    result = resolver.resolve(chunk, mentions)
    assert isinstance(result.resolved, tuple)
    assert isinstance(result.unresolved, tuple)
