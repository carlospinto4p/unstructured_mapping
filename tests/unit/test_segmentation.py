"""Tests for the pipeline.segmentation module."""

import pytest

from unstructured_mapping.pipeline.segmentation import (
    DocumentSegmenter,
    DocumentType,
    FilingSegmenter,
    NewsSegmenter,
    ResearchSegmenter,
    TranscriptSegmenter,
)
from unstructured_mapping.pipeline.segmentation._sub_chunk import (
    estimate_tokens,
    sub_chunk_by_paragraph,
)


# -- DocumentType -----------------------------------------------


def test_document_type_enum_values():
    assert DocumentType.NEWS.value == "news"
    assert DocumentType.RESEARCH.value == "research"
    assert DocumentType.TRANSCRIPT.value == "transcript"
    assert DocumentType.FILING.value == "filing"


# -- NewsSegmenter ----------------------------------------------


def test_news_segmenter_emits_single_chunk():
    seg = NewsSegmenter()
    chunks = seg.segment("doc1", "A one-paragraph article.")
    assert len(chunks) == 1
    assert chunks[0].document_id == "doc1"
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == "A one-paragraph article."
    assert chunks[0].section_name is None


def test_news_segmenter_empty_text_returns_empty_list():
    assert NewsSegmenter().segment("doc1", "") == []
    assert NewsSegmenter().segment("doc1", "   \n") == []


def test_news_segmenter_preserves_multiline_body():
    text = "Lead paragraph.\n\nSecond paragraph."
    chunks = NewsSegmenter().segment("doc1", text)
    assert len(chunks) == 1
    assert chunks[0].text == text


# -- ResearchSegmenter ------------------------------------------


def test_research_segmenter_splits_on_atx_headings():
    text = (
        "Cover page preamble.\n\n"
        "## Executive Summary\n"
        "The thesis.\n\n"
        "## Valuation\n"
        "DCF and comps.\n\n"
        "## Risks\n"
        "Supplier concentration, regulatory."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert [c.section_name for c in chunks] == [
        "Executive Summary",
        "Valuation",
        "Risks",
    ]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert "DCF and comps." in chunks[1].text


def test_research_segmenter_splits_on_setext_headings():
    text = (
        "Valuation\n"
        "=========\n"
        "Body A.\n\n"
        "Risks\n"
        "-----\n"
        "Body B."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert [c.section_name for c in chunks] == [
        "Valuation",
        "Risks",
    ]


def test_research_segmenter_no_headings_single_chunk():
    text = "Just body text with no headings at all."
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name is None
    assert chunks[0].text == text


def test_research_segmenter_drops_preamble_before_first_heading():
    text = (
        "Report cover boilerplate.\n\n"
        "## Body\n"
        "Real content."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name == "Body"
    assert "cover boilerplate" not in chunks[0].text


def test_research_segmenter_skips_empty_sections():
    text = (
        "## Executive Summary\n"
        "\n"
        "## Valuation\n"
        "Real content."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name == "Valuation"


# -- TranscriptSegmenter ----------------------------------------


def test_transcript_segmenter_splits_on_speaker_turns():
    text = (
        "Operator: Welcome to the Q3 2026 earnings call.\n"
        "Tim Cook - CEO: Thank you. Revenue hit $95B.\n"
        "Luca Maestri - CFO: Margins expanded 200bps."
    )
    chunks = TranscriptSegmenter().segment("t1", text)
    names = [c.section_name for c in chunks]
    assert names == [
        "Operator",
        "Tim Cook - CEO",
        "Luca Maestri - CFO",
    ]
    assert "Revenue hit $95B." in chunks[1].text


def test_transcript_segmenter_emits_qa_divider_chunk():
    text = (
        "Tim Cook - CEO: Prepared remarks.\n"
        "Q&A\n"
        "Analyst: Question about iPhone.\n"
        "Tim Cook - CEO: Answer."
    )
    chunks = TranscriptSegmenter().segment("t1", text)
    names = [c.section_name for c in chunks]
    assert names == [
        "Tim Cook - CEO",
        "Q&A",
        "Analyst",
        "Tim Cook - CEO",
    ]
    qa = next(c for c in chunks if c.section_name == "Q&A")
    assert qa.text == ""


def test_transcript_segmenter_falls_back_to_one_chunk_without_speakers():
    text = "Just narrative text with no speaker labels."
    chunks = TranscriptSegmenter().segment("t1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name is None
    assert chunks[0].text == text


def test_transcript_segmenter_captures_multiline_turn_body():
    text = (
        "Tim Cook - CEO: First line.\n"
        "Continuation of the same turn.\n"
        "Luca Maestri - CFO: New turn."
    )
    chunks = TranscriptSegmenter().segment("t1", text)
    assert len(chunks) == 2
    assert (
        "Continuation of the same turn."
        in chunks[0].text
    )


# -- FilingSegmenter --------------------------------------------


def test_filing_segmenter_splits_on_item_headings():
    text = (
        "Cover page.\n\n"
        "Item 1. Business\n"
        "We design phones.\n\n"
        "Item 1A. Risk Factors\n"
        "Supplier concentration risk.\n\n"
        "Item 7. Management's Discussion\n"
        "Margins expanded."
    )
    chunks = FilingSegmenter().segment("f1", text)
    names = [c.section_name for c in chunks]
    assert names == [
        "Item 1. Business",
        "Item 1A. Risk Factors",
        "Item 7. Management's Discussion",
    ]
    risks = next(
        c for c in chunks if "Risk" in c.section_name
    )
    assert "Supplier concentration risk." in risks.text


def test_filing_segmenter_normalises_item_suffix_casing():
    text = "item 7b. Quantitative Disclosures\nBody."
    chunks = FilingSegmenter().segment("f1", text)
    assert chunks[0].section_name == (
        "Item 7B. Quantitative Disclosures"
    )


def test_filing_segmenter_no_items_single_chunk():
    text = "A generic business document without Items."
    chunks = FilingSegmenter().segment("f1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name is None


def test_filing_segmenter_ignores_item_inside_long_line():
    # "refer to Item 1A. Risk Factors" is prose, not a
    # heading — long lines are never treated as headings.
    prose = (
        "Operator: " + "x " * 150 + "refer to Item 1A. "
        "Risk Factors in the attached filing."
    )
    text = (
        "Item 1. Business\n"
        "Body.\n"
        + prose
        + "\n"
        "Item 2. Properties\nBody 2."
    )
    chunks = FilingSegmenter().segment("f1", text)
    assert len(chunks) == 2
    assert chunks[0].section_name == "Item 1. Business"
    assert chunks[1].section_name == "Item 2. Properties"


def test_filing_segmenter_drops_preamble():
    text = (
        "Registration Statement\n"
        "Cover information.\n\n"
        "Item 1. Business\nBody."
    )
    chunks = FilingSegmenter().segment("f1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name == "Item 1. Business"
    assert "Cover information." not in chunks[0].text


# -- ABC --------------------------------------------------------


def test_abstract_segmenter_rejects_instantiation():
    with pytest.raises(TypeError):
        DocumentSegmenter()  # type: ignore[abstract]


# -- sub_chunk_by_paragraph -------------------------------------


def test_sub_chunk_short_text_passes_through():
    text = "One small paragraph."
    assert sub_chunk_by_paragraph(text, max_tokens=100) == [
        "One small paragraph."
    ]


def test_sub_chunk_empty_returns_empty_list():
    assert sub_chunk_by_paragraph("", max_tokens=10) == []
    assert (
        sub_chunk_by_paragraph("   \n  ", max_tokens=10)
        == []
    )


def test_sub_chunk_splits_on_paragraph_boundaries():
    para_a = " ".join(["alpha"] * 20)
    para_b = " ".join(["beta"] * 20)
    para_c = " ".join(["gamma"] * 20)
    text = f"{para_a}\n\n{para_b}\n\n{para_c}"
    pieces = sub_chunk_by_paragraph(
        text, max_tokens=25, overlap_ratio=0.0
    )
    assert len(pieces) == 3
    assert "alpha" in pieces[0]
    assert "beta" in pieces[1]
    assert "gamma" in pieces[2]
    # No paragraph is split mid-body.
    assert "alpha" not in pieces[1]


def test_sub_chunk_overlap_prepends_prior_tail():
    para_a = " ".join(["alpha"] * 20)
    para_b = " ".join(["beta"] * 20)
    text = f"{para_a}\n\n{para_b}"
    pieces = sub_chunk_by_paragraph(
        text, max_tokens=25, overlap_ratio=0.2
    )
    assert len(pieces) == 2
    # The second sub-chunk should carry some alphas
    # prepended as overlap, so boundary entities survive.
    assert "alpha" in pieces[1]
    assert "beta" in pieces[1]


def test_sub_chunk_oversized_paragraph_emits_alone():
    big = " ".join(["x"] * 300)
    pieces = sub_chunk_by_paragraph(big, max_tokens=50)
    assert pieces == [big]


def test_sub_chunk_rejects_non_positive_max_tokens():
    with pytest.raises(ValueError):
        sub_chunk_by_paragraph("text", max_tokens=0)


def test_estimate_tokens_counts_words():
    assert estimate_tokens("one two three") == 3
    assert estimate_tokens("") == 0
    assert estimate_tokens("  padded   ") == 1


# -- segmenter max_tokens fallback ------------------------------


def _big_paragraph(word: str, count: int) -> str:
    return " ".join([word] * count)


def test_research_segmenter_sub_chunks_oversized_section():
    big_body = (
        _big_paragraph("alpha", 40)
        + "\n\n"
        + _big_paragraph("beta", 40)
        + "\n\n"
        + _big_paragraph("gamma", 40)
    )
    text = f"## Risks\n{big_body}"
    seg = ResearchSegmenter(max_tokens=50, overlap_ratio=0.0)
    chunks = seg.segment("r1", text)
    # Three 40-word paragraphs with a 50-token cap → 3
    # sub-chunks, all sharing the "Risks" section name.
    assert len(chunks) == 3
    assert all(
        c.section_name == "Risks" for c in chunks
    )
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_research_segmenter_no_max_tokens_keeps_one_per_section():
    big_body = _big_paragraph("alpha", 200)
    text = f"## Risks\n{big_body}"
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1


def test_filing_segmenter_sub_chunks_oversized_item():
    body = (
        _big_paragraph("alpha", 40)
        + "\n\n"
        + _big_paragraph("beta", 40)
    )
    text = f"Item 1A. Risk Factors\n{body}"
    chunks = FilingSegmenter(max_tokens=50).segment(
        "f1", text
    )
    assert len(chunks) == 2
    assert all(
        c.section_name == "Item 1A. Risk Factors"
        for c in chunks
    )


def test_transcript_segmenter_sub_chunks_long_turn():
    body = (
        _big_paragraph("alpha", 40)
        + "\n\n"
        + _big_paragraph("beta", 40)
    )
    text = f"Tim Cook - CEO: {body}"
    chunks = TranscriptSegmenter(max_tokens=50).segment(
        "t1", text
    )
    assert len(chunks) == 2
    assert all(
        c.section_name == "Tim Cook - CEO" for c in chunks
    )


def test_transcript_segmenter_qa_divider_not_sub_chunked():
    text = (
        "Tim Cook - CEO: Prepared remarks.\n"
        "Q&A\n"
        "Analyst: Question."
    )
    chunks = TranscriptSegmenter(max_tokens=5).segment(
        "t1", text
    )
    # Q&A divider survives with zero body even under a
    # very tight budget — it is a marker, not content.
    qa_chunks = [
        c for c in chunks if c.section_name == "Q&A"
    ]
    assert len(qa_chunks) == 1
    assert qa_chunks[0].text == ""
