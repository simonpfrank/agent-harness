"""Reflection loop — generate, critique, refine until satisfied."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

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
    """Run the reflection loop: generate → critique → refine → repeat.

    Stops when the critique contains 'DONE' or max_turns iterations reached.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks.

    Returns:
        The last generated (non-critique) response content.
    """
    cb = callbacks or LoopCallbacks()
    last_output = ""

    for iteration in range(config.max_turns):
        # Generate (or refine)
        response = chat_fn(messages, tool_schemas, model=config.model, **config.provider_kwargs)
        messages.append(response.message)
        last_output = response.message.content or ""
        if cb.on_response:
            cb.on_response(response)
        if cb.on_budget and cb.on_budget(response.usage):
            break

        # Critique
        messages.append(Message(role="user", content=_CRITIQUE_PROMPT))
        critique = chat_fn(messages, [], model=config.model, **config.provider_kwargs)
        messages.append(critique.message)
        if cb.on_budget and cb.on_budget(critique.usage):
            break

        critique_text = critique.message.content or ""
        logger.info("Reflection iteration %d: %s", iteration + 1, critique_text[:80])

        if "DONE" in critique_text.upper():
            break

        # Set up refinement prompt
        messages.append(Message(role="user", content="Refine your response based on the critique above."))

    return last_output
