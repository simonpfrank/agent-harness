"""ReWOO loop — plan once, execute all tools, solve once."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.tools import execute_tool
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall

logger = logging.getLogger(__name__)


def _parse_tool_calls(response: Response) -> list[ToolCall]:
    """Extract tool calls from a response.

    Args:
        response: LLM response that may contain tool calls.

    Returns:
        List of tool calls, or empty list.
    """
    return response.message.tool_calls or []


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run the ReWOO loop: plan with tools, execute all, solve with results.

    Only 2 LLM calls: one to plan (with tool calls), one to solve with all results.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks.

    Returns:
        Final assistant message content.
    """
    cb = callbacks or LoopCallbacks()

    # Phase 1: Plan — LLM sees tools and produces tool calls
    plan_response = chat_fn(messages, tool_schemas, model=config.model, **config.provider_kwargs)
    messages.append(plan_response.message)
    if cb.on_response:
        cb.on_response(plan_response)

    tool_calls = _parse_tool_calls(plan_response)
    if not tool_calls:
        return plan_response.message.content or ""

    # Phase 2: Execute all tool calls
    for tc in tool_calls:
        logger.debug("ReWOO executing: %s", tc.name)
        result = cb.on_tool_call(tc) if cb.on_tool_call else execute_tool(tc)
        if result is not None:
            messages.append(Message(role="tool", tool_result=result))

    # Phase 3: Solve — LLM sees all results, no tools
    solve_response = chat_fn(messages, [], model=config.model, **config.provider_kwargs)
    messages.append(solve_response.message)
    if cb.on_response:
        cb.on_response(solve_response)
    if cb.on_budget:
        cb.on_budget(solve_response.usage)

    return solve_response.message.content or ""
