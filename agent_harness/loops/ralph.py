"""Ralph Wiggum loop — naive persistence with fresh context on each retry."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.loops.common import report_completion_status, run_completion_check
from agent_harness.loops.react import run as react_run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)

_DONE_MARKER = "DONE"


def _run_attempt(
    chat_fn: Callable[..., Response],
    attempt_messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None,
    cb: LoopCallbacks,
) -> tuple[str, bool, str]:
    """Run react to a DONE claim, verifying it if completion_check is configured.

    On a failed check, the failure is fed back as a user message and react
    is re-run on the same (not fresh) attempt_messages so the model can see
    and act on it — discarding it every time would defeat the point of
    checking at all. Bounded by config.max_turns regardless of whether
    is_budget_exceeded is wired, matching react.py's own defensive pattern
    of never depending solely on an optional callback for its bound.

    Args:
        chat_fn: Provider chat function.
        attempt_messages: This attempt's message history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Callbacks forwarded to react_run.
        cb: Resolved LoopCallbacks (callbacks or a fresh LoopCallbacks()).

    Returns:
        (last_result, verified, detail).
    """
    last_result = ""
    for _ in range(config.max_turns):
        last_result = react_run(chat_fn, attempt_messages, tool_schemas, config, callbacks)
        if _DONE_MARKER not in last_result.upper():
            return last_result, False, ""
        if not config.completion_check:
            return last_result, True, ""

        verified, detail = run_completion_check(cb, tool_schemas, config)
        if verified:
            return last_result, True, detail
        logger.info("Ralph completion_check failed: %s", detail[:80])
        attempt_messages.append(
            Message(role="user", content=f"Completion check failed:\n{detail}\nAddress this and continue."),
        )
        if cb.is_budget_exceeded and cb.is_budget_exceeded():
            return last_result, False, detail

    return last_result, False, "max retries within attempt reached without passing completion_check"


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run react with fresh context on each retry until DONE or max attempts.

    Each attempt starts with only the original system + user messages. If
    the response contains 'DONE', the task is considered complete — unless
    completion_check is configured, in which case a failed check feeds back
    into the *same* attempt (see _run_attempt) rather than starting fresh.

    Args:
        chat_fn: Provider chat function.
        messages: Initial messages (system + user). Mutated on final attempt.
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks.

    Returns:
        Final response content.
    """
    cb = callbacks or LoopCallbacks()
    # Preserve the original messages for fresh retries
    initial = [Message(role=m.role, content=m.content) for m in messages]
    last_result = ""

    for attempt in range(config.max_turns):
        # Fresh context each attempt
        attempt_messages = list(initial)
        last_result, verified, detail = _run_attempt(chat_fn, attempt_messages, tool_schemas, config, callbacks, cb)
        logger.info("Ralph attempt %d: %s", attempt + 1, last_result[:60])

        if verified:
            # Update the original messages with the successful attempt
            messages.clear()
            messages.extend(attempt_messages)
            report_completion_status(cb, config, True, detail)
            return last_result

        if cb.is_budget_exceeded and cb.is_budget_exceeded():
            break

    report_completion_status(cb, config, False, "stopped: max_turns/budget reached without passing completion_check")
    return last_result
