"""Session persistence — save and load conversation history."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent_harness.types import Message, ToolCall, ToolResult

logger = logging.getLogger(__name__)


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message to a JSON-compatible dict.

    Args:
        msg: Message to serialize.

    Returns:
        Dict representation.
    """
    data: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        data["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    if msg.tool_result:
        data["tool_result"] = {
            "tool_call_id": msg.tool_result.tool_call_id,
            "output": msg.tool_result.output,
            "error": msg.tool_result.error,
        }
    return data


def _dict_to_message(data: dict[str, Any]) -> Message:
    """Deserialize a dict to a Message.

    Args:
        data: Dict from JSON.

    Returns:
        Reconstructed Message.
    """
    tool_calls = None
    if "tool_calls" in data:
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in data["tool_calls"]
        ]
    tool_result = None
    if "tool_result" in data:
        tr = data["tool_result"]
        tool_result = ToolResult(
            tool_call_id=tr["tool_call_id"],
            output=tr.get("output"),
            error=tr.get("error"),
        )
    return Message(
        role=data["role"],
        content=data.get("content"),
        tool_calls=tool_calls,
        tool_result=tool_result,
    )


def save_session(messages: list[Message], path: str) -> None:
    """Save conversation messages to a JSON file.

    Args:
        messages: Conversation history to save.
        path: File path to write to.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = [_message_to_dict(m) for m in messages]
    Path(path).write_text(json.dumps(data, indent=2))
    logger.info("Session saved: %d messages to %s", len(messages), path)


def load_session(path: str) -> list[Message]:
    """Load conversation messages from a JSON file.

    Args:
        path: File path to read from.

    Returns:
        List of Messages, or empty list if file doesn't exist.
    """
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    messages = [_dict_to_message(d) for d in data]
    logger.info("Session loaded: %d messages from %s", len(messages), path)
    return messages
