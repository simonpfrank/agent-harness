"""Standard ReAct loop — reason, act, observe, repeat."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_harness.tools import execute_tool
from agent_harness.types import (
    AgentConfig,
    Message,
    OnBudget,
    OnResponse,
    OnToolCall,
    Response,
)


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    on_response: OnResponse | None = None,
    on_tool_call: OnToolCall | None = None,
    on_budget: OnBudget | None = None,
) -> str:
    """Run the ReAct loop until completion or budget exceeded.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        on_response: Called after each LLM response.
        on_tool_call: Called to execute each tool call.
        on_budget: Called with usage; returns True if budget exceeded.

    Returns:
        Final assistant message content.
    """
    turn = 0
    while turn < config.max_turns:
        response = chat_fn(messages, tool_schemas, model=config.model)
        messages.append(response.message)

        if on_response:
            on_response(response)
        if on_budget and on_budget(response.usage):
            break

        if response.stop_reason != "tool_use":
            break

        for tc in response.message.tool_calls or []:
            result = on_tool_call(tc) if on_tool_call else execute_tool(tc)
            if result is not None:
                messages.append(Message(role="tool", tool_result=result))

        turn += 1

    last = messages[-1] if messages else None
    return last.content or "" if last else ""
