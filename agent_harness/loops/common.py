"""Shared utilities for loop implementations."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from agent_harness.tools import execute_tool
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall

logger = logging.getLogger(__name__)

_MAX_CLEANUP_ATTEMPTS = 3
_EXIT_CODE_RE = re.compile(r"\[exit code (\d+)\]")


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
            response = chat_fn(
                messages, tool_schemas, model=config.model, stream=config.stream, **config.provider_kwargs,
            )
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


def run_completion_check(
    cb: LoopCallbacks,
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
) -> tuple[bool, str]:
    """Resolve and run config.completion_check, and interpret pass/fail.

    Resolution: if config.completion_check names a tool present in
    tool_schemas, it is called with no arguments (a completion-check tool
    must work with zero required arguments). Otherwise it is treated as a
    shell command and dispatched through the built-in run_command tool.
    Either way this goes through cb.on_tool_call — the same permission/
    hook/tracing path as any normal tool call.

    Pass/fail convention, checked in this order:
    1. A tool exception (ToolResult.error set) — FAIL.
    2. Output text starting with "PASS" or "FAIL" (case-insensitive) —
       the simplest thing to satisfy when hand-writing a verification tool.
    3. A trailing "[exit code N]" marker (run_command always appends one)
       — 0 is PASS, nonzero is FAIL.
    4. Anything else — FAIL, not a silent pass.

    Args:
        cb: Loop callbacks. Missing on_tool_call reports FAIL.
        tool_schemas: This run's tool schemas, used to detect whether
            completion_check names an exposed tool vs. a shell command.
        config: Agent configuration; completion_check must be set.

    Returns:
        (verified, detail) — detail is shown to the user and fed back to
        the model on failure.
    """
    check = config.completion_check
    assert check is not None

    if check in {schema["name"] for schema in tool_schemas}:
        tool_call = ToolCall(id="completion_check", name=check, arguments={})
    else:
        tool_call = ToolCall(id="completion_check", name="run_command", arguments={"command": check})

    if cb.on_tool_call is None:
        return False, "completion_check could not run — no on_tool_call callback configured"

    result = cb.on_tool_call(tool_call)
    if result is None:
        return False, "completion_check produced no result"
    if result.error:
        return False, result.error

    output = (result.output or "").strip()
    upper = output.upper()
    if upper.startswith("PASS"):
        return True, output
    if upper.startswith("FAIL"):
        return False, output

    exit_match = _EXIT_CODE_RE.search(output)
    if exit_match:
        return int(exit_match.group(1)) == 0, output

    return False, output or "completion_check output had no PASS/FAIL/exit-code signal"


def report_completion_status(cb: LoopCallbacks, config: AgentConfig, verified: bool, detail: str) -> None:
    """Fire on_completion_status once — only when completion_check is configured.

    Centralizes the "stay fully inert unless opted in" guard so each loop
    doesn't repeat it.

    Args:
        cb: Loop callbacks. No-op if on_completion_status is unset.
        config: Agent configuration. No-op if completion_check is unset.
        verified: Whether completion was actually verified.
        detail: The check's own output, or why the loop stopped without
            ever passing it.
    """
    if config.completion_check and cb.on_completion_status:
        cb.on_completion_status(verified, detail)
