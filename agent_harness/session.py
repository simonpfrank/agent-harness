"""Session persistence — save and load conversation history.

Sessions are identified by a GUID, not by the human-chosen name (mirrors
Claude Code's session model): a name is optional and cosmetic, resolved via
a directory scan rather than a second index file to keep in sync.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_harness.atomic_write import atomic_write_text
from agent_harness.types import Message, ToolCall, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """One saved conversation.

    Attributes:
        id: Stable GUID identity — the file's key, never guessed or reused.
        name: Optional human-chosen label, purely cosmetic, resolved by scan.
        messages: Conversation history.
    """

    id: str
    name: str | None
    messages: list[Message]


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message to a JSON-compatible dict.

    Args:
        msg: Message to serialize.

    Returns:
        Dict representation.
    """
    data: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.thinking is not None:
        data["thinking"] = msg.thinking
    if msg.thinking_blocks is not None:
        data["thinking_blocks"] = msg.thinking_blocks
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
        thinking=data.get("thinking"),
        thinking_blocks=data.get("thinking_blocks"),
    )


def save_session(session: Session, path: str) -> None:
    """Save a session to a JSON file.

    Args:
        session: Session to save.
        path: File path to write to.
    """
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "id": session.id,
            "name": session.name,
            "messages": [_message_to_dict(m) for m in session.messages],
        }
        atomic_write_text(path, json.dumps(data, indent=2))
        logger.info("Session saved: %d messages to %s", len(session.messages), path)
    except OSError:
        logger.warning("Could not save session to %s", path)


def load_session(path: str) -> Session | None:
    """Load a session from a JSON file.

    Args:
        path: File path to read from.

    Returns:
        The loaded `Session`, or `None` if the file is missing, corrupt, or
        malformed — callers treat this as "no saved session", not a crash.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        logger.warning("Corrupted session file: %s — starting fresh", path)
        return None
    if not isinstance(data, dict) or "id" not in data or "messages" not in data:
        logger.warning("Invalid session format in %s — starting fresh", path)
        return None
    try:
        messages = [_dict_to_message(d) for d in data["messages"]]
    except (KeyError, TypeError) as exc:
        logger.warning("Malformed message in session %s: %s — starting fresh", path, exc)
        return None
    logger.info("Session loaded: %d messages from %s", len(messages), path)
    return Session(id=data["id"], name=data.get("name"), messages=messages)


def session_path(sessions_dir: str, session: Session) -> str:
    """Resolve the on-disk path for a session.

    Args:
        sessions_dir: Directory sessions are stored under.
        session: Session to resolve a path for.

    Returns:
        `{sessions_dir}/{session.id}.json` — keyed by id, never by name.
    """
    return str(Path(sessions_dir) / f"{session.id}.json")


def load_session_by_id(sessions_dir: str, session_id: str) -> Session | None:
    """Load a session directly by its GUID.

    Args:
        sessions_dir: Directory sessions are stored under.
        session_id: Session id to load.

    Returns:
        The session, or `None` if no file exists for that id.
    """
    return load_session(str(Path(sessions_dir) / f"{session_id}.json"))


def find_session_by_name(sessions_dir: str, name: str) -> Session | None:
    """Find an existing session by its human-chosen name.

    Args:
        sessions_dir: Directory to scan.
        name: Name to match.

    Returns:
        The first session whose `name` matches, or `None` if none found.
        A linear scan, not an index — avoids a second file to keep in sync,
        and is fine at this project's real scale.
    """
    for path in sorted(Path(sessions_dir).glob("*.json")):
        session = load_session(str(path))
        if session is not None and session.name == name:
            return session
    return None


def resolve_or_create_session(sessions_dir: str, name: str | None) -> Session:
    """Find a session by name, or create a fresh one.

    Args:
        sessions_dir: Directory sessions are stored under.
        name: Human-chosen name to resolve, or `None` for an unnamed session.

    Returns:
        The existing session matching `name`, or a new empty `Session` with
        a fresh GUID if none matches (or `name` is `None`).
    """
    if name is not None:
        existing = find_session_by_name(sessions_dir, name)
        if existing is not None:
            return existing
    return Session(id=uuid.uuid4().hex, name=name, messages=[])
