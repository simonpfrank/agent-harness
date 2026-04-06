"""Plan-execute loop — plan first, then execute each step with react."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from agent_harness.loops.react import run as react_run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)

_PLAN_PROMPT_SUFFIX = (
    "\n\nCreate a numbered plan (1. 2. 3. ...) for this task. "
    "Do not execute anything yet — just list the steps."
)


def _parse_plan(text: str) -> list[str]:
    """Extract numbered steps from a plan text.

    Args:
        text: LLM response containing numbered steps.

    Returns:
        List of step descriptions.
    """
    steps: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*\d+\.\s*(.+)", line)
        if match:
            steps.append(match.group(1).strip())
    return steps


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run a plan-execute loop: plan first, then execute each step.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks for display and budget.

    Returns:
        Final summary content.
    """
    cb = callbacks or LoopCallbacks()

    # Phase 1: Planning — no tools, ask for numbered plan
    task = messages[-1].content or "" if messages else ""
    plan_messages = list(messages)
    plan_messages.append(Message(role="user", content=task + _PLAN_PROMPT_SUFFIX))
    plan_response = chat_fn(plan_messages, [], model=config.model, **config.provider_kwargs)
    messages.append(plan_response.message)
    if cb.on_response:
        cb.on_response(plan_response)

    plan_text = plan_response.message.content or ""
    steps = _parse_plan(plan_text)
    logger.info("Plan has %d steps", len(steps))

    if not steps:
        logger.warning("No steps found in plan — falling back to react")
        return react_run(chat_fn, messages, tool_schemas, config, callbacks)

    # Phase 2: Execute each step with a mini react loop
    for i, step in enumerate(steps):
        logger.info("Executing step %d/%d: %s", i + 1, len(steps), step[:60])
        messages.append(Message(role="user", content=f"Execute step {i + 1}: {step}"))
        react_run(chat_fn, messages, tool_schemas, config, callbacks)

    # Phase 3: Summarise
    messages.append(Message(role="user", content="Summarise what was accomplished."))
    summary_response = chat_fn(messages, [], model=config.model, **config.provider_kwargs)
    messages.append(summary_response.message)
    if cb.on_response:
        cb.on_response(summary_response)

    return summary_response.message.content or ""
