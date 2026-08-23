"""Tests for agent_harness.api.events."""

import json

from agent_harness.api.events import SseEvent, format_sse


class TestFormatSse:
    def test_wire_format_exact_shape(self) -> None:
        event = SseEvent(event="delta", data={"agent": "default", "text": "hi"}, seq=1)
        wire = format_sse(event)
        assert wire == 'event: delta\nid: 1\ndata: {"agent": "default", "text": "hi"}\n\n'

    def test_data_is_valid_json(self) -> None:
        event = SseEvent(event="tool_call", data={"id": "tc", "name": "read_file", "arguments": {"path": "a"}}, seq=2)
        wire = format_sse(event)
        data_line = wire.splitlines()[2]
        assert data_line.startswith("data: ")
        parsed = json.loads(data_line[len("data: "):])
        assert parsed == {"id": "tc", "name": "read_file", "arguments": {"path": "a"}}

    def test_ends_with_blank_line(self) -> None:
        event = SseEvent(event="heartbeat", data={}, seq=3)
        assert format_sse(event).endswith("\n\n")

    def test_empty_payload(self) -> None:
        event = SseEvent(event="heartbeat", data={}, seq=1)
        assert format_sse(event) == "event: heartbeat\nid: 1\ndata: {}\n\n"


class TestEventTypeConstants:
    def test_expected_event_types_exist(self) -> None:
        from agent_harness.api import events

        expected = {
            "DELTA", "THINKING_DELTA", "TOOL_CALL", "TOOL_RESULT", "BUDGET",
            "THRASH_WARNING", "APPROVAL_NEEDED", "HEARTBEAT", "DONE", "ERROR",
        }
        for name in expected:
            assert hasattr(events, name)
            assert isinstance(getattr(events, name), str)
