"""Standard ReAct loop — reason, act, observe, repeat."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.attachments import prune_attachments
from agent_harness.context import get_context_limit, trim_messages
from agent_harness.tools import execute_tool
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)


def _with_budget_note(messages: list[Message], cb: LoopCallbacks) -> list[Message]:
    """Build a disposable message list with a budget note appended to the
    system message, without mutating the canonical (persisted) list.

    Args:
        messages: Canonical conversation history.
        cb: Loop callbacks; only used if `get_budget_status` is set.

    Returns:
        `messages` unchanged if no note applies, otherwise a new list whose
        first element is a replacement system message.
    """
    if not cb.get_budget_status or not messages or messages[0].role != "system" or not messages[0].content:
        return messages
    note = cb.get_budget_status()
    logger.debug("Budget note injected: %s", note)
    overlay = Message(role="system", content=f"{messages[0].content}\n\n{note}")
    return [overlay, *messages[1:]]


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run the ReAct loop until completion or budget exceeded.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional response, tool, and budget callbacks.

    Returns:
        Final assistant message content.
    """
    cb = callbacks or LoopCallbacks()
    context_limit = get_context_limit(config.provider, config.model)
    turn = 0
    while turn < config.max_turns:
        trimmed = trim_messages(messages, context_limit)
        if len(trimmed) < len(messages):
            messages.clear()
            messages.extend(trimmed)
        logger.debug("Turn %d: calling %s/%s", turn + 1, config.provider, config.model)
        call_messages = _with_budget_note(prune_attachments(messages), cb)
        response = chat_fn(
            call_messages, tool_schemas, model=config.model,
            stream=config.stream, on_delta=cb.on_delta, on_thinking_delta=cb.on_thinking_delta,
            **config.provider_kwargs,
        )
        messages.append(response.message)
        logger.info(
            "Turn %d: %d in / %d out tokens",
            turn + 1, response.usage.input_tokens, response.usage.output_tokens,
        )

        if cb.on_response:
            cb.on_response(response)
        budget_exceeded = bool(cb.on_budget and cb.on_budget(response.usage))

        if response.stop_reason != "tool_use":
            break

        for tc in response.message.tool_calls or []:
            logger.debug("Executing tool: %s(%s)", tc.name, list(tc.arguments.keys()))
            result = cb.on_tool_call(tc) if cb.on_tool_call else execute_tool(tc)
            if result is not None:
                messages.append(Message(role="tool", tool_result=result))

        turn += 1
        if budget_exceeded:
            break

    last = messages[-1] if messages else None
    return last.content or "" if last else ""
