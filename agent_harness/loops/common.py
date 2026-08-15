"""Shared utilities for loop implementations."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from agent_harness.tools import execute_tool
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall, ToolResult

logger = logging.getLogger(__name__)

_MAX_CLEANUP_ATTEMPTS = 3
_EXIT_CODE_RE = re.compile(r"\[exit code (\d+)\]")

_DUPLICATE_ARGS_NUDGE = (
    "Thrash guard: you've called '{tool}' with identical arguments {count} times. "
    "Repeating this exact call will not produce a different result — "
    "change the arguments or try a different tool."
)
_ERROR_STREAK_NUDGE = (
    "Thrash guard: '{tool}' has now failed {count} times in a row. "
    "Stop retrying the same approach — re-read the last error, reconsider your "
    "assumptions, and try something different."
)


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


def check_tool_thrashing(
    tool_call: ToolCall,
    result: ToolResult | None,
    call_counts: dict[str, int],
    error_streaks: dict[str, int],
    threshold: int,
) -> str | None:
    """Update per-run thrash-tracking state for one tool call and detect thrashing.

    Two independent signals share one threshold, checked in this order
    (error streak first — the more urgent state to break; if both fire on
    the same call, the streak message is the more useful one):
    1. `tool_call.name` erroring >= threshold times in a row (tracked per
       tool name only; resets to 0 the moment that tool succeeds).
    2. The exact (name, arguments) pair called >= threshold times total
       this run (JSON-serialized, sort_keys=True, for a stable key —
       arguments always come from parsed provider tool-call responses, so
       this never needs defensive error handling).

    Args:
        tool_call: The tool call just executed.
        result: Its result, or None if no message will be recorded for it.
            Still counted toward the duplicate-args signal, excluded from
            error-streak tracking (unknown whether it was a failure).
        call_counts: Mutable per-run map of "{tool}:{args_json}" -> count,
            mutated in place.
        error_streaks: Mutable per-run map of tool_name -> consecutive
            error count, mutated in place.
        threshold: Repeat/streak count that triggers a nudge. <= 0
            disables detection entirely.

    Returns:
        A nudge message to feed back to the model, or None if nothing
        looks like thrashing yet.
    """
    if threshold <= 0:
        return None

    is_error = result is not None and result.error is not None
    if is_error:
        error_streaks[tool_call.name] = error_streaks.get(tool_call.name, 0) + 1
    else:
        error_streaks[tool_call.name] = 0

    args_key = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"
    call_counts[args_key] = call_counts.get(args_key, 0) + 1

    if error_streaks[tool_call.name] >= threshold:
        return _ERROR_STREAK_NUDGE.format(tool=tool_call.name, count=error_streaks[tool_call.name])
    if call_counts[args_key] >= threshold:
        return _DUPLICATE_ARGS_NUDGE.format(tool=tool_call.name, count=call_counts[args_key])
    return None


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
