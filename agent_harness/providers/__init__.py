"""Provider registry with lazy loading."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, cast

from agent_harness.types import Response

ChatFn = Callable[..., Response]

_PROVIDER_MODULES: dict[str, str] = {
    "anthropic": "agent_harness.providers.anthropic",
    "openai": "agent_harness.providers.openai_provider",
}


def _lazy_chat(module_name: str) -> ChatFn:
    def chat(*args: Any, **kwargs: Any) -> Response:
        module = importlib.import_module(module_name)
        return cast(Response, module.chat(*args, **kwargs))

    return chat


registry: dict[str, ChatFn] = {
    name: _lazy_chat(module_name)
    for name, module_name in _PROVIDER_MODULES.items()
}


def get_provider(name: str) -> ChatFn:
    """Return the provider chat function for a configured provider name."""
    return registry[name]
