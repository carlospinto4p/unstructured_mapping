"""Shared test fixtures for unstructured_mapping unit tests."""

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProvider,
)


def make_entity(**kwargs):
    defaults = {
        "canonical_name": "Test Entity",
        "entity_type": EntityType.PERSON,
        "description": "A test entity.",
    }
    defaults.update(kwargs)
    return Entity(**defaults)


class FakeProvider(LLMProvider):
    """Reusable fake LLM provider for tests.

    Supports single or multiple responses (popped in
    order). Captures all calls for assertion.

    :param response: A single response string or a list
        of strings (popped in order; last one repeats).
    :param supports_json_mode: Whether the provider
        claims to support JSON mode.
    """

    provider_name = "fake"
    model_name = "fake-1"
    context_window = 4096

    def __init__(
        self,
        response: str | list[str] = "{}",
        *,
        supports_json_mode: bool = True,
    ):
        self._responses = (
            [response]
            if isinstance(response, str)
            else list(response)
        )
        self._supports_json_mode = supports_json_mode
        self.calls: list[
            tuple[str, str | None, bool]
        ] = []

    @property
    def supports_json_mode(self) -> bool:
        return self._supports_json_mode

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append((prompt, system, json_mode))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]
