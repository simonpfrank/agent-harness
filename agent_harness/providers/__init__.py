"""Provider registry."""

from __future__ import annotations

from collections.abc import Callable

from agent_harness.providers import anthropic
from agent_harness.types import Response

ChatFn = Callable[..., Response]

registry: dict[str, ChatFn] = {
    "anthropic": anthropic.chat,
}
