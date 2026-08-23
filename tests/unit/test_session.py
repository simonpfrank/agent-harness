"""Tests for agent_harness.session."""

import tempfile
from pathlib import Path

from agent_harness.session import (
    Session,
    find_session_by_name,
    load_session,
    load_session_by_id,
    resolve_or_create_session,
    save_session,
    session_path,
)
from agent_harness.types import Message, ToolCall, ToolResult


class TestSaveAndLoad:
    def test_round_trip_simple_messages(self) -> None:
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        session = Session(id="abc123", name=None, messages=msgs)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_session(session, path)
        loaded = load_session(path)
        assert loaded is not None
        assert loaded.id == "abc123"
        assert len(loaded.messages) == 3
        assert loaded.messages[0].role == "system"
        assert loaded.messages[1].content == "hi"
        assert loaded.messages[2].content == "hello"
        Path(path).unlink()

    def test_round_trip_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo"})
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        msgs = [
            Message(role="assistant", content="reading", tool_calls=[tc]),
            Message(role="tool", tool_result=tr),
        ]
        session = Session(id="abc123", name=None, messages=msgs)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_session(session, path)
        loaded = load_session(path)
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0].tool_calls is not None
        assert loaded.messages[0].tool_calls[0].name == "read_file"
        assert loaded.messages[1].tool_result is not None
        assert loaded.messages[1].tool_result.output == "file data"
        Path(path).unlink()

    def test_round_trip_with_thinking(self) -> None:
        blocks = [{"type": "thinking", "thinking": "let me think", "signature": "sig123"}]
        msgs = [
            Message(role="assistant", content="the answer", thinking="let me think", thinking_blocks=blocks),
        ]
        session = Session(id="abc123", name=None, messages=msgs)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_session(session, path)
        loaded = load_session(path)
        assert loaded is not None
        assert loaded.messages[0].thinking == "let me think"
        assert loaded.messages[0].thinking_blocks == blocks
        Path(path).unlink()

    def test_round_trip_preserves_name(self) -> None:
        session = Session(id="abc123", name="my-chat", messages=[Message(role="user", content="hi")])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_session(session, path)
        loaded = load_session(path)
        assert loaded is not None
        assert loaded.name == "my-chat"
        Path(path).unlink()

    def test_missing_file_returns_none(self) -> None:
        assert load_session("/nonexistent/path.json") is None

    def test_corrupt_file_returns_none(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("{not valid json")
            path = f.name
        assert load_session(path) is None
        Path(path).unlink()

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "sessions" / "test.json")
            session = Session(id="abc123", name=None, messages=[Message(role="user", content="hi")])
            save_session(session, path)
            assert Path(path).exists()


class TestSessionPath:
    def test_keyed_by_id_not_name(self) -> None:
        session = Session(id="abc123", name="my-chat", messages=[])
        assert session_path("sessions", session) == "sessions/abc123.json"


class TestFindSessionByName:
    def test_finds_by_name(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        session = Session(id="abc123", name="my-chat", messages=[Message(role="user", content="hi")])
        save_session(session, session_path(sessions_dir, session))
        found = find_session_by_name(sessions_dir, "my-chat")
        assert found is not None
        assert found.id == "abc123"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        assert find_session_by_name(sessions_dir, "nope") is None

    def test_returns_none_when_dir_does_not_exist(self, tmp_path: Path) -> None:
        assert find_session_by_name(str(tmp_path / "never-created"), "anything") is None


class TestLoadSessionById:
    def test_finds_by_id(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        session = Session(id="abc123", name="my-chat", messages=[Message(role="user", content="hi")])
        save_session(session, session_path(sessions_dir, session))
        found = load_session_by_id(sessions_dir, "abc123")
        assert found is not None
        assert found.name == "my-chat"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        assert load_session_by_id(sessions_dir, "nonexistent") is None


class TestResolveOrCreateSession:
    def test_creates_fresh_session_when_no_existing_match(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        session = resolve_or_create_session(sessions_dir, "brand-new")
        assert session.name == "brand-new"
        assert session.messages == []
        assert session.id  # non-empty

    def test_resolves_existing_session_by_name(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        first = resolve_or_create_session(sessions_dir, "foo")
        first.messages = [Message(role="user", content="hi")]
        save_session(first, session_path(sessions_dir, first))

        second = resolve_or_create_session(sessions_dir, "foo")
        assert second.id == first.id
        assert len(second.messages) == 1

    def test_two_different_names_never_collide(self, tmp_path: Path) -> None:
        sessions_dir = str(tmp_path / "sessions")
        a = resolve_or_create_session(sessions_dir, "chat")
        b = resolve_or_create_session(sessions_dir, "chat-2")
        assert a.id != b.id
