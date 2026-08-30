"""Standard ReAct loop — reason, act, observe, repeat."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent_harness.attachments import prune_attachments
from agent_harness.context import get_context_limit, trim_messages
from agent_harness.loops.common import check_tool_thrashing
from agent_harness.tools import execute_tool
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall, ToolResult

logger = logging.getLogger(__name__)

_MAX_PARALLEL_WORKERS = 8


def _run_tool_calls(
    tool_calls: list[ToolCall], cb: LoopCallbacks, parallel: bool,
) -> list[tuple[ToolCall, ToolResult | None]]:
    """Execute one turn's tool calls, sequentially or in parallel.

    Args:
        tool_calls: This turn's tool calls, in the order the model requested them.
        cb: Loop callbacks; `on_tool_call` (or `execute_tool` if unset) does the work.
        parallel: Whether to use a thread pool. Ignored for a single call —
            there's nothing to parallelize and it would only add overhead.

    Returns:
        (tool_call, result) pairs in the same order as `tool_calls`, regardless
        of which order they actually completed in — keeps the resulting
        message history deterministic even though execution isn't. A real
        exception from a call propagates from here (via `future.result()`),
        same as it would from a plain sequential loop.
    """
    def call(tc: ToolCall) -> ToolResult | None:
        return cb.on_tool_call(tc) if cb.on_tool_call else execute_tool(tc)

    if not parallel or len(tool_calls) <= 1:
        return [(tc, call(tc)) for tc in tool_calls]

    with ThreadPoolExecutor(max_workers=min(len(tool_calls), _MAX_PARALLEL_WORKERS)) as executor:
        futures = [executor.submit(call, tc) for tc in tool_calls]
        return [(tc, future.result()) for tc, future in zip(tool_calls, futures, strict=True)]


def _handle_tool_calls(
    tool_calls: list[ToolCall],
    messages: list[Message],
    cb: LoopCallbacks,
    config: AgentConfig,
    call_counts: dict[str, int],
    error_streaks: dict[str, int],
) -> tuple[str | None, str]:
    """Execute a turn's tool calls, append their results, and run thrash detection.

    Args:
        tool_calls: This turn's tool calls.
        messages: Conversation history, appended to in place.
        cb: Loop callbacks.
        config: Agent configuration.
        call_counts: Mutable per-run thrash-tracking state, mutated in place.
        error_streaks: Mutable per-run thrash-tracking state, mutated in place.

    Returns:
        `(thrash_detail, thrash_tool)` — `thrash_detail` is `None` if
        nothing looks like thrashing yet.
    """
    for tc in tool_calls:
        logger.debug("Executing tool: %s(%s)", tc.name, list(tc.arguments.keys()))
    results = _run_tool_calls(tool_calls, cb, config.parallel_tool_calls)
    for _tc, result in results:
        if result is not None:
            messages.append(Message(role="tool", tool_result=result))
    thrash_detail: str | None = None
    thrash_tool = ""
    for tc, result in results:
        detail = check_tool_thrashing(tc, result, call_counts, error_streaks, config.thrash_threshold)
        if detail is not None:
            thrash_detail = detail
            thrash_tool = tc.name
    return thrash_detail, thrash_tool


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
    call_counts: dict[str, int] = {}
    error_streaks: dict[str, int] = {}
    turn = 0
    while turn < config.max_turns:
        if cb.is_cancelled and cb.is_cancelled():
            break
        trimmed = trim_messages(messages, context_limit)
        if len(trimmed) < len(messages):
            messages.clear()
            messages.extend(trimmed)
        logger.debug("Turn %d: calling %s/%s", turn + 1, config.provider, config.model)
        call_messages = _with_budget_note(prune_attachments(messages), cb)
        response = chat_fn(
            call_messages, tool_schemas, model=config.model,
            stream=config.stream, on_delta=cb.on_delta, on_thinking_delta=cb.on_thinking_delta,
            is_cancelled=cb.is_cancelled,
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

        thrash_detail, thrash_tool = _handle_tool_calls(
            response.message.tool_calls or [], messages, cb, config, call_counts, error_streaks,
        )

        turn += 1
        if budget_exceeded:
            break
        if thrash_detail is not None:
            messages.append(Message(role="user", content=thrash_detail))
            if cb.on_thrash_detected:
                cb.on_thrash_detected(thrash_tool, thrash_detail)

    last = messages[-1] if messages else None
    return last.content or "" if last else ""
