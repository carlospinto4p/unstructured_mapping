"""Shared retry logic for LLM pipeline passes.

Both pass 1 (entity resolution) and pass 2 (relationship
extraction) use the same retry-with-error-feedback
pattern from ``docs/pipeline/03_llm_interface.md`` §
"Retry and error feedback". This module extracts the
common loop so each pass only supplies the parse
function and system prompt.
"""

import logging
from collections.abc import Callable

from unstructured_mapping.pipeline.llm.provider import (
    LLMProvider,
    LLMProviderError,
    TokenUsage,
)

logger = logging.getLogger(__name__)

#: Maximum number of LLM calls per chunk (1 original
#: + 1 retry on validation failure).
MAX_ATTEMPTS: int = 2


def retry_llm_call(
    provider: LLMProvider,
    user_prompt: str,
    system_prompt: str,
    parse_fn: Callable[[str], object],
    *,
    pass_label: str = "LLM",
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[object, TokenUsage]:
    """Call the LLM with retry on validation failure.

    Sends ``user_prompt`` with ``system_prompt`` to the
    provider. The raw response is passed to ``parse_fn``
    for validation. If ``parse_fn`` raises a
    ``ValueError`` subclass (e.g.
    ``Pass1ValidationError``, ``Pass2ValidationError``),
    the error is appended to the prompt and the call is
    retried once.

    After ``max_attempts`` consecutive failures, raises
    :class:`LLMProviderError`.

    :param provider: The LLM backend.
    :param user_prompt: The user prompt to send.
    :param system_prompt: The system prompt.
    :param parse_fn: Callable that validates the raw
        response. Should raise ``ValueError`` on
        validation failure.
    :param pass_label: Label for log messages (e.g.
        ``"Pass 1"``, ``"Pass 2"``).
    :param max_attempts: Maximum LLM calls per chunk.
    :return: Tuple of ``(parse_fn result, summed
        TokenUsage across attempts)``. Usage is a zero-
        valued :class:`TokenUsage` when the provider does
        not expose counts (e.g. test fakes).
    :raises LLMProviderError: After ``max_attempts``
        consecutive validation failures.
    """
    last_error: ValueError | None = None
    usage_total = TokenUsage()
    for attempt in range(max_attempts):
        prompt = user_prompt
        if last_error is not None:
            prompt = append_error(prompt, last_error)

        raw = provider.generate(
            prompt,
            system=system_prompt,
            json_mode=provider.supports_json_mode,
        )
        call_usage = provider.last_token_usage
        if call_usage is not None:
            usage_total = usage_total + call_usage

        try:
            result = parse_fn(raw)
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "%s validation failed (attempt %d/%d): %s",
                pass_label,
                attempt + 1,
                max_attempts,
                exc,
            )
            continue

        return result, usage_total

    raise LLMProviderError(
        f"{pass_label} failed after {max_attempts} attempts: {last_error}"
    )


def append_error(
    prompt: str,
    error: ValueError,
) -> str:
    """Append a validation error to the user prompt.

    Follows the retry format from
    ``03_llm_interface.md`` § "Retry and error
    feedback".

    :param prompt: The original user prompt.
    :param error: The validation error to append.
    :return: Prompt with error feedback appended.
    """
    return (
        f"{prompt}\n\n"
        "Your previous response had the "
        "following error:\n"
        f"{error}\n\n"
        "Please correct your response. Output "
        "valid JSON matching the required schema."
    )
