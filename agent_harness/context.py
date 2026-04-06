"""Context window management — trim messages to avoid overflow."""

from __future__ import annotations

import logging

from agent_harness.types import Message

logger = logging.getLogger(__name__)

_CONTEXT_LIMITS: dict[tuple[str, str], int] = {
    ("anthropic", "claude-haiku-4-5-20251001"): 200_000,
    ("anthropic", "claude-sonnet-4-6"): 200_000,
    ("anthropic", "claude-opus-4-6"): 200_000,
    ("openai", "gpt-4o-mini"): 128_000,
    ("openai", "gpt-4o"): 128_000,
}

_DEFAULT_LIMIT = 128_000
_THRESHOLD = 0.8


def estimate_tokens(text: str) -> int:
    """Approximate token count from text length.

    Args:
        text: Input text.

    Returns:
        Estimated token count (~4 chars per token).
    """
    return len(text) // 4


def get_context_limit(provider: str, model: str) -> int:
    """Get the context window limit for a provider/model pair.

    Args:
        provider: Provider name.
        model: Model name.

    Returns:
        Max tokens for the model's context window.
    """
    return _CONTEXT_LIMITS.get((provider, model), _DEFAULT_LIMIT)


def _message_tokens(msg: Message) -> int:
    """Estimate tokens for a single message."""
    total = 0
    if msg.content:
        total += estimate_tokens(msg.content)
    if msg.tool_result and msg.tool_result.output:
        total += estimate_tokens(msg.tool_result.output)
    return total + 4  # overhead per message


def trim_messages(messages: list[Message], max_tokens: int) -> list[Message]:
    """Trim oldest non-system messages if total exceeds threshold.

    Preserves the system message and the most recent messages.

    Args:
        messages: Full conversation history.
        max_tokens: Context window size in tokens.

    Returns:
        Trimmed message list.
    """
    if not messages:
        return []

    threshold = int(max_tokens * _THRESHOLD)
    total = sum(_message_tokens(m) for m in messages)
    if total <= threshold:
        return messages

    # Separate system message from the rest
    system = [m for m in messages if m.role == "system"]
    others = [m for m in messages if m.role != "system"]
    system_tokens = sum(_message_tokens(m) for m in system)
    budget = threshold - system_tokens

    # Keep messages from the end until budget is used
    kept: list[Message] = []
    used = 0
    for msg in reversed(others):
        msg_tokens = _message_tokens(msg)
        if used + msg_tokens > budget:
            break
        kept.append(msg)
        used += msg_tokens
    kept.reverse()

    dropped = len(others) - len(kept)
    if dropped > 0:
        logger.info("Context trimmed: dropped %d oldest messages (%d remaining)", dropped, len(kept))

    return system + kept
