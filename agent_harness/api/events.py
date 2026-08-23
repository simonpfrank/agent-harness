"""Server-Sent Event types and wire-format serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DELTA = "delta"
THINKING_DELTA = "thinking_delta"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
BUDGET = "budget"
THRASH_WARNING = "thrash_warning"
APPROVAL_NEEDED = "approval_needed"
HEARTBEAT = "heartbeat"
DONE = "done"
ERROR = "error"


@dataclass
class SseEvent:
    """One Server-Sent Event.

    Attributes:
        event: Event type name (one of the module-level constants above).
        data: JSON-serializable payload.
        seq: Monotonic per-run sequence number, sent as the SSE `id:` field.
    """

    event: str
    data: dict[str, Any]
    seq: int


def format_sse(event: SseEvent) -> str:
    """Serialize an `SseEvent` to standard SSE wire format.

    Args:
        event: Event to serialize.

    Returns:
        `"event: <type>\\nid: <seq>\\ndata: <json>\\n\\n"`.
    """
    return f"event: {event.event}\nid: {event.seq}\ndata: {json.dumps(event.data)}\n\n"
