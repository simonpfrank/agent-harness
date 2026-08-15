"""Tests for agent_harness.providers.retry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agent_harness.providers.retry import with_retry


class _AuthError(Exception):
    pass


class _BadRequestError(Exception):
    pass


class _ApiError(Exception):
    pass


def _call(fn: Callable[[], Any]) -> Any:
    return with_retry(
        fn,
        auth_error=_AuthError,
        bad_request_error=_BadRequestError,
        api_error=_ApiError,
        provider_name="TestProvider",
        env_var="TEST_API_KEY",
    )


class TestBadRequestError:
    def test_wrapped_as_runtime_error(self) -> None:
        def raises() -> None:
            raise _BadRequestError("temperature not supported with this model")

        with pytest.raises(RuntimeError, match="TestProvider rejected the request"):
            _call(raises)

    def test_original_exception_chained_as_cause(self) -> None:
        original = _BadRequestError("bad shape")

        def raises() -> None:
            raise original

        with pytest.raises(RuntimeError) as exc_info:
            _call(raises)
        assert exc_info.value.__cause__ is original

    def test_not_retried(self) -> None:
        calls = 0

        def raises() -> None:
            nonlocal calls
            calls += 1
            raise _BadRequestError("bad")

        with pytest.raises(RuntimeError):
            _call(raises)
        assert calls == 1


class TestAuthError:
    def test_wrapped_as_runtime_error(self) -> None:
        def raises() -> None:
            raise _AuthError("no key")

        with pytest.raises(RuntimeError, match="TEST_API_KEY"):
            _call(raises)
