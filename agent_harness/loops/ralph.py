"""Ralph Wiggum loop — naive persistence with fresh context on each retry."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.loops.react import run as react_run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)

_DONE_MARKER = "DONE"


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run react with fresh context on each retry until DONE or max attempts.

    Each attempt starts with only the original system + user messages.
    If the response contains 'DONE', the task is considered complete.

    Args:
        chat_fn: Provider chat function.
        messages: Initial messages (system + user). Mutated on final attempt.
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks.

    Returns:
        Final response content.
    """
    # Preserve the original messages for fresh retries
    initial = [Message(role=m.role, content=m.content) for m in messages]
    last_result = ""

    for attempt in range(config.max_turns):
        # Fresh context each attempt
        attempt_messages = list(initial)
        last_result = react_run(chat_fn, attempt_messages, tool_schemas, config, callbacks)
        logger.info("Ralph attempt %d: %s", attempt + 1, last_result[:60])

        if _DONE_MARKER in last_result.upper():
            # Update the original messages with the successful attempt
            messages.clear()
            messages.extend(attempt_messages)
            return last_result

    return last_result
