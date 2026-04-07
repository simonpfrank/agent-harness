"""Reflection loop — generate with tools, critique, refine until satisfied."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.loops.common import ensure_clean_state
from agent_harness.loops.react import run as react_run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)

_CRITIQUE_PROMPT = (
    "Critique your previous response. If it's good enough, respond with DONE. "
    "Otherwise explain what needs improving."
)


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run the reflection loop: generate (with tools) → critique → refine → repeat.

    The generate phase uses a react sub-loop so the agent can use tools.
    The critique phase has no tools — pure reasoning.
    Stops when the critique contains 'DONE' or max_turns iterations reached.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks.

    Returns:
        The last generated response content.
    """
    cb = callbacks or LoopCallbacks()
    last_output = ""

    for iteration in range(config.max_turns):
        # Generate — use react so tools work
        react_run(chat_fn, messages, tool_schemas, config, callbacks)
        last_output = ensure_clean_state(chat_fn, messages, tool_schemas, config)

        # Critique — pass tool_schemas so API accepts tool_use in history
        messages.append(Message(role="user", content=_CRITIQUE_PROMPT))
        critique = chat_fn(messages, tool_schemas, model=config.model, **config.provider_kwargs)
        messages.append(critique.message)
        if cb.on_response:
            cb.on_response(critique)
        if cb.on_budget and cb.on_budget(critique.usage):
            break

        critique_text = critique.message.content or ""
        logger.info("Reflection iteration %d: %s", iteration + 1, critique_text[:80])

        if "DONE" in critique_text.upper():
            break

        # Set up refinement prompt
        messages.append(Message(role="user", content="Refine your response based on the critique above."))

    return last_output
