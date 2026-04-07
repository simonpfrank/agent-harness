"""Shared utilities for loop implementations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.tools import execute_tool
from agent_harness.types import AgentConfig, Message, Response

logger = logging.getLogger(__name__)

_MAX_CLEANUP_ATTEMPTS = 3


def ensure_clean_state(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
) -> str:
    """Ensure messages end with a text-only assistant response.

    After a react sub-loop, the message history may end with unresolved
    tool_use or tool_result blocks. This resolves them by completing
    any pending tool calls and getting a final text response.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: Tool schemas for API compatibility.
        config: Agent configuration.

    Returns:
        The final assistant text content.
    """
    for _ in range(_MAX_CLEANUP_ATTEMPTS):
        if not messages:
            return ""

        last = messages[-1]

        # Clean state — last message is text-only assistant
        if last.role == "assistant" and not last.tool_calls:
            return last.content or ""

        # Last message is tool result — LLM needs to respond
        if last.role == "tool":
            response = chat_fn(messages, tool_schemas, model=config.model, **config.provider_kwargs)
            messages.append(response.message)
            continue  # Check again — response might have tool_calls

        # Last assistant message has tool_calls — execute them
        if last.role == "assistant" and last.tool_calls:
            for tc in last.tool_calls:
                result = execute_tool(tc)
                messages.append(Message(role="tool", tool_result=result))
            continue  # Now we have tool results, loop to get LLM response

    # Fallback: couldn't clean up, return whatever content we have
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.content:
            return msg.content
    return ""
