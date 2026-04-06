"""Tests for agent_harness.session."""

import tempfile
from pathlib import Path

from agent_harness.session import load_session, save_session
from agent_harness.types import Message, ToolCall, ToolResult


class TestSaveAndLoad:
    def test_round_trip_simple_messages(self) -> None:
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_session(msgs, path)
        loaded = load_session(path)
        assert len(loaded) == 3
        assert loaded[0].role == "system"
        assert loaded[1].content == "hi"
        assert loaded[2].content == "hello"
        Path(path).unlink()

    def test_round_trip_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo"})
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        msgs = [
            Message(role="assistant", content="reading", tool_calls=[tc]),
            Message(role="tool", tool_result=tr),
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_session(msgs, path)
        loaded = load_session(path)
        assert len(loaded) == 2
        assert loaded[0].tool_calls is not None
        assert loaded[0].tool_calls[0].name == "read_file"
        assert loaded[1].tool_result is not None
        assert loaded[1].tool_result.output == "file data"
        Path(path).unlink()

    def test_missing_file_returns_empty(self) -> None:
        loaded = load_session("/nonexistent/path.json")
        assert loaded == []

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "sessions" / "test.json")
            save_session([Message(role="user", content="hi")], path)
            assert Path(path).exists()
