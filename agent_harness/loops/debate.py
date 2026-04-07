"""Debate loop — two perspectives argue, synthesiser reconciles."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)

_FOR_PROMPT = "Argue IN FAVOUR of the following. Be specific and provide evidence."
_AGAINST_PROMPT = "Argue AGAINST the following. Be specific and provide evidence."
_SYNTH_PROMPT = "You have seen arguments for and against. Synthesise a balanced, well-reasoned answer."


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run a debate: two perspectives argue for max_turns rounds, then synthesise.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas (unused — debate is reasoning only).
        config: Agent configuration. max_turns = number of debate rounds.
        callbacks: Optional callbacks.

    Returns:
        Synthesised answer content.
    """
    cb = callbacks or LoopCallbacks()
    transcript: list[Message] = list(messages)

    for round_num in range(config.max_turns):
        logger.info("Debate round %d/%d", round_num + 1, config.max_turns)

        # Argument FOR
        for_messages = list(transcript)
        for_messages.append(Message(role="user", content=_FOR_PROMPT))
        for_response = chat_fn(for_messages, [], model=config.model, **config.provider_kwargs)
        transcript.append(for_response.message)
        if cb.on_response:
            cb.on_response(for_response)
        if cb.on_budget and cb.on_budget(for_response.usage):
            break

        # Argument AGAINST
        against_messages = list(transcript)
        against_messages.append(Message(role="user", content=_AGAINST_PROMPT))
        against_response = chat_fn(against_messages, [], model=config.model, **config.provider_kwargs)
        transcript.append(against_response.message)
        if cb.on_response:
            cb.on_response(against_response)
        if cb.on_budget and cb.on_budget(against_response.usage):
            break

    # Synthesise
    transcript.append(Message(role="user", content=_SYNTH_PROMPT))
    synth_response = chat_fn(transcript, [], model=config.model, **config.provider_kwargs)
    messages.clear()
    messages.extend(transcript)
    messages.append(synth_response.message)
    if cb.on_response:
        cb.on_response(synth_response)

    return synth_response.message.content or ""
