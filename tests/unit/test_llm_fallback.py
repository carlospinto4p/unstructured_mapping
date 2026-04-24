"""Tests for :mod:`pipeline.llm_fallback`.

Covers:

* the default ambiguity scorer across malformed JSON,
  empty / missing arrays, pass-1 proposal ratios, and
  pass-2 responses,
* the escalation decision matrix (hard failure vs.
  ambiguity vs. primary-succeeded),
* token-usage summing across escalation,
* provider-metadata derivation (context_window,
  supports_json_mode, composite names), and
* constructor validation.
"""

import pytest

from unstructured_mapping.pipeline import (
    DEFAULT_AMBIGUITY_THRESHOLD,
    FallbackLLMProvider,
    LLMConnectionError,
    LLMProvider,
    TokenUsage,
    default_ambiguity_score,
)


# -- scorer --------------------------------------------


def test_scorer_invalid_json_returns_one():
    assert default_ambiguity_score("not json") == 1.0


def test_scorer_non_object_json_returns_one():
    assert default_ambiguity_score("[1, 2, 3]") == 1.0


def test_scorer_missing_both_keys_returns_one():
    assert default_ambiguity_score("{}") == 1.0


def test_scorer_empty_entities_returns_one():
    assert default_ambiguity_score('{"entities": []}') == 1.0


def test_scorer_all_proposals_returns_one():
    payload = (
        '{"entities": ['
        '{"surface_form": "X", "context_snippet": "s", '
        '"new_entity": {"canonical_name": "X"}},'
        '{"surface_form": "Y", "context_snippet": "s", '
        '"new_entity": {"canonical_name": "Y"}}'
        "]}"
    )
    assert default_ambiguity_score(payload) == 1.0


def test_scorer_all_resolved_returns_zero():
    payload = (
        '{"entities": ['
        '{"surface_form": "X", "context_snippet": "s", "entity_id": "e1"},'
        '{"surface_form": "Y", "context_snippet": "s", "entity_id": "e2"}'
        "]}"
    )
    assert default_ambiguity_score(payload) == 0.0


def test_scorer_mixed_ratio():
    payload = (
        '{"entities": ['
        '{"surface_form": "X", "context_snippet": "s", "entity_id": "e1"},'
        '{"surface_form": "Y", "context_snippet": "s", '
        '"new_entity": {"canonical_name": "Y"}}'
        "]}"
    )
    assert default_ambiguity_score(payload) == 0.5


def test_scorer_pass2_returns_zero():
    assert default_ambiguity_score('{"relationships": []}') == 0.0
    assert (
        default_ambiguity_score(
            '{"relationships": [{"source": "a", "target": "b"}]}'
        )
        == 0.0
    )


# -- FakeProvider used by the fallback tests -----------


class _FakeProvider(LLMProvider):
    """Minimal fake that can either return a canned
    response or raise a configured error, and exposes the
    usual metadata the ABC requires."""

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str = "m",
        response: str | None = None,
        raises: Exception | None = None,
        tokens: TokenUsage | None = None,
        context_window: int = 4096,
        supports_json_mode: bool = True,
    ) -> None:
        self._provider_name = provider_name
        self._model_name = model_name
        self._response = response
        self._raises = raises
        self._tokens = tokens
        self._ctx = context_window
        self._supports_json_mode = supports_json_mode
        self.calls: list[tuple[str, str | None, bool]] = []

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append((prompt, system, json_mode))
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return self._response

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def context_window(self) -> int:
        return self._ctx

    @property
    def supports_json_mode(self) -> bool:
        return self._supports_json_mode

    @property
    def last_token_usage(self) -> TokenUsage | None:
        return self._tokens


# -- generate() routing --------------------------------


def _primary_resolved():
    return (
        '{"entities": ['
        '{"surface_form": "X", "context_snippet": "s", "entity_id": "e1"}'
        "]}"
    )


def _primary_all_proposals():
    return (
        '{"entities": ['
        '{"surface_form": "X", "context_snippet": "s", '
        '"new_entity": {"canonical_name": "X"}}'
        "]}"
    )


def test_primary_succeeds_secondary_not_called():
    primary = _FakeProvider(
        provider_name="p",
        response=_primary_resolved(),
        tokens=TokenUsage(10, 5),
    )
    secondary = _FakeProvider(provider_name="s", response="ignored")
    fb = FallbackLLMProvider(primary=primary, secondary=secondary)

    out = fb.generate("p", json_mode=True)

    assert out == _primary_resolved()
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 0
    assert fb.last_served_by == "p"
    assert fb.last_token_usage == TokenUsage(10, 5)
    assert fb.escalations == 0


def test_primary_ambiguous_escalates():
    primary = _FakeProvider(
        provider_name="p",
        response=_primary_all_proposals(),  # score 1.0
        tokens=TokenUsage(10, 5),
    )
    secondary = _FakeProvider(
        provider_name="s",
        response=_primary_resolved(),
        tokens=TokenUsage(100, 50),
    )
    fb = FallbackLLMProvider(primary=primary, secondary=secondary)

    out = fb.generate("p", json_mode=True)

    assert out == _primary_resolved()
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 1
    assert fb.last_served_by == "s"
    assert fb.escalations == 1
    # Token usage sums both sides.
    assert fb.last_token_usage == TokenUsage(110, 55)


def test_primary_hard_failure_escalates():
    primary = _FakeProvider(
        provider_name="p",
        raises=LLMConnectionError("down"),
    )
    secondary = _FakeProvider(
        provider_name="s",
        response=_primary_resolved(),
        tokens=TokenUsage(42, 7),
    )
    fb = FallbackLLMProvider(primary=primary, secondary=secondary)

    out = fb.generate("p", json_mode=True)

    assert out == _primary_resolved()
    assert fb.last_served_by == "s"
    assert fb.escalations == 1
    # Primary never produced usage; only secondary counts.
    assert fb.last_token_usage == TokenUsage(42, 7)


def test_ambiguity_threshold_at_one_only_hard_failures():
    """With threshold=1.0, no response can exceed it, so
    only hard failures trigger escalation. A malformed
    response (score 1.0) is NOT greater than threshold
    1.0, so it stays with the primary.
    """
    primary = _FakeProvider(
        provider_name="p",
        response="not json",  # score 1.0
        tokens=TokenUsage(1, 1),
    )
    secondary = _FakeProvider(provider_name="s", response="unused")
    fb = FallbackLLMProvider(
        primary=primary, secondary=secondary, ambiguity_threshold=1.0
    )

    out = fb.generate("p", json_mode=True)
    assert out == "not json"
    assert fb.escalations == 0
    assert fb.last_served_by == "p"


def test_custom_ambiguity_fn_is_used():
    primary = _FakeProvider(
        provider_name="p",
        response="anything",
        tokens=TokenUsage(0, 0),
    )
    secondary = _FakeProvider(
        provider_name="s",
        response="from-secondary",
        tokens=TokenUsage(0, 0),
    )
    # Custom scorer always says "escalate".
    fb = FallbackLLMProvider(
        primary=primary,
        secondary=secondary,
        ambiguity_threshold=0.0,
        ambiguity_fn=lambda _: 0.9,
    )

    out = fb.generate("p")
    assert out == "from-secondary"
    assert fb.escalations == 1


# -- constructor validation ----------------------------


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_threshold_out_of_range_rejected(bad):
    p = _FakeProvider(provider_name="p", response="")
    s = _FakeProvider(provider_name="s", response="")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        FallbackLLMProvider(primary=p, secondary=s, ambiguity_threshold=bad)


# -- metadata derivation -------------------------------


def test_provider_and_model_name_are_composite():
    p = _FakeProvider(provider_name="ollama", model_name="llama3.1:8b")
    s = _FakeProvider(provider_name="anthropic", model_name="sonnet-4-6")
    fb = FallbackLLMProvider(primary=p, secondary=s)
    assert fb.provider_name == "fallback(ollama->anthropic)"
    assert "ollama:llama3.1:8b" in fb.model_name
    assert "anthropic:sonnet-4-6" in fb.model_name


def test_context_window_is_min_of_two():
    p = _FakeProvider(provider_name="p", context_window=200_000)
    s = _FakeProvider(provider_name="s", context_window=8_000)
    fb = FallbackLLMProvider(primary=p, secondary=s)
    assert fb.context_window == 8_000


def test_supports_json_mode_requires_both():
    p = _FakeProvider(provider_name="p", supports_json_mode=True)
    s_no = _FakeProvider(provider_name="s", supports_json_mode=False)
    s_yes = _FakeProvider(provider_name="s", supports_json_mode=True)
    assert not FallbackLLMProvider(
        primary=p, secondary=s_no
    ).supports_json_mode
    assert FallbackLLMProvider(primary=p, secondary=s_yes).supports_json_mode


def test_last_token_usage_reset_between_calls():
    """A second call should not leak the prior call's
    usage — the fallback accumulates per ``generate``,
    not across calls."""
    primary = _FakeProvider(
        provider_name="p",
        response=_primary_resolved(),
        tokens=TokenUsage(10, 5),
    )
    secondary = _FakeProvider(provider_name="s", response="unused")
    fb = FallbackLLMProvider(primary=primary, secondary=secondary)

    fb.generate("p1", json_mode=True)
    assert fb.last_token_usage == TokenUsage(10, 5)
    fb.generate("p2", json_mode=True)
    # Same tokens reported on second call since fake
    # returns the same usage, but the usage object is the
    # primary-only branch (not accumulated from call 1).
    assert fb.last_token_usage == TokenUsage(10, 5)


def test_default_threshold_constant_value():
    # Sanity check so documentation / callers aren't
    # silently bumped by a refactor.
    assert DEFAULT_AMBIGUITY_THRESHOLD == 0.5
