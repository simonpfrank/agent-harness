"""Shared retry logic for LLM providers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = [1, 2, 4]


def with_retry(
    fn: Callable[[], Any],
    auth_error: type[Exception],
    bad_request_error: type[Exception],
    api_error: type[Exception],
    provider_name: str,
    env_var: str,
) -> Any:
    """Call fn with retry on transient errors, fail fast on auth/bad request.

    Args:
        fn: Zero-arg callable that makes the API call.
        auth_error: Exception class for authentication failures.
        bad_request_error: Exception class for invalid requests.
        api_error: Base exception class for retryable API errors.
        provider_name: For error messages (e.g. "Anthropic", "OpenAI").
        env_var: Environment variable name for the API key.

    Returns:
        Result from fn.

    Raises:
        RuntimeError: On auth failure or after max retries exhausted.
    """
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except auth_error:
            raise RuntimeError(
                f"{provider_name} API key invalid or not set — export {env_var}"
            ) from None
        except bad_request_error:
            raise
        except api_error as exc:
            if attempt < MAX_RETRIES - 1:
                delay = BACKOFF_SECONDS[attempt]
                logger.warning(
                    "%s API error (attempt %d): %s — retrying in %ds",
                    provider_name, attempt + 1, exc, delay,
                )
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"{provider_name} API failed after {MAX_RETRIES} attempts: {exc}"
                ) from exc
    raise RuntimeError(f"{provider_name} API failed after {MAX_RETRIES} attempts")  # pragma: no cover
