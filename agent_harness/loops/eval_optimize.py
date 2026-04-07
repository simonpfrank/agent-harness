"""Evaluator-Optimizer loop — generate with tools, score, improve until threshold met."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from agent_harness.loops.react import run as react_run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response

logger = logging.getLogger(__name__)

_EVAL_PROMPT = (
    "Evaluate the previous response. Provide feedback and end with SCORE: N/10."
)
_SCORE_PATTERN = re.compile(r"SCORE:\s*(\d+)/10", re.IGNORECASE)
_PASS_THRESHOLD = 7


def _extract_score(text: str) -> int:
    """Extract a SCORE: N/10 rating from evaluator output.

    Args:
        text: Evaluator response text.

    Returns:
        Score as integer (0 if not found).
    """
    match = _SCORE_PATTERN.search(text)
    return int(match.group(1)) if match else 0


def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
    """Run the evaluator-optimizer loop until score >= threshold or max_turns.

    The generate phase uses a react sub-loop so the agent can use tools.
    The evaluate phase has no tools — pure scoring.

    Args:
        chat_fn: Provider chat function.
        messages: Conversation history (mutated in place).
        tool_schemas: JSON schemas for available tools.
        config: Agent configuration.
        callbacks: Optional callbacks.

    Returns:
        The last generated response that passed evaluation.
    """
    cb = callbacks or LoopCallbacks()
    last_output = ""

    for iteration in range(config.max_turns):
        # Generate — use react so tools work
        last_output = react_run(chat_fn, messages, tool_schemas, config, callbacks)

        # Evaluate — no tools, pure scoring
        messages.append(Message(role="user", content=_EVAL_PROMPT))
        eval_response = chat_fn(messages, [], model=config.model, **config.provider_kwargs)
        messages.append(eval_response.message)
        if cb.on_budget and cb.on_budget(eval_response.usage):
            break

        eval_text = eval_response.message.content or ""
        score = _extract_score(eval_text)
        logger.info("Eval iteration %d: score %d/10", iteration + 1, score)

        if score >= _PASS_THRESHOLD:
            break

        # Improve
        messages.append(Message(role="user", content="Improve your response based on the evaluation feedback above."))

    return last_output
