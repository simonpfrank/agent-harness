"""Tests for agent_harness.display."""

import io
from unittest.mock import patch

from rich.console import Console

from agent_harness import display
from agent_harness.display import (
    prompt_user,
    show_budget,
    show_delta,
    show_response,
    show_thinking_delta,
    show_tool_call,
    show_tool_result,
)
from agent_harness.types import Message, Response, ToolCall, ToolResult, Usage


def _recording_console() -> Console:
    return Console(file=io.StringIO(), record=True, width=200)


class TestShowResponse:
    def test_no_crash_on_valid_input(self) -> None:
        msg = Message(role="assistant", content="Hello world")
        resp = Response(message=msg, usage=Usage(10, 5), stop_reason="end_turn")
        show_response(resp)

    def test_no_crash_on_none_content(self) -> None:
        msg = Message(role="assistant", content=None)
        resp = Response(message=msg, usage=Usage(10, 5), stop_reason="tool_use")
        show_response(resp)


class TestShowToolCall:
    def test_no_crash(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo.txt"})
        show_tool_call(tc)

    def test_bracket_content_not_swallowed_as_markup(self) -> None:
        recorder = _recording_console()
        with patch.object(display, "console", recorder):
            tc = ToolCall(id="tc_1", name="edit_file", arguments={"old_string": "def f(x: list[str])"})
            show_tool_call(tc)
        assert "list[str]" in recorder.export_text()


class TestShowToolResult:
    def test_success_no_crash(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file contents here")
        show_tool_result(tr)

    def test_error_no_crash(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", error="file not found")
        show_tool_result(tr)

    def test_bracket_content_not_swallowed_as_markup(self) -> None:
        recorder = _recording_console()
        with patch.object(display, "console", recorder):
            tr = ToolResult(tool_call_id="tc_1", output="[Getting started](https://example.com)")
            show_tool_result(tr)
        assert "[Getting started](https://example.com)" in recorder.export_text()

    def test_error_bracket_content_not_swallowed_as_markup(self) -> None:
        recorder = _recording_console()
        with patch.object(display, "console", recorder):
            tr = ToolResult(tool_call_id="tc_1", error="path [invalid] not found")
            show_tool_result(tr)
        assert "path [invalid] not found" in recorder.export_text()


class TestShowBudget:
    def test_no_crash(self) -> None:
        show_budget("Turn 1/10 | $0.0012")

    def test_bracket_content_not_swallowed_as_markup(self) -> None:
        recorder = _recording_console()
        with patch.object(display, "console", recorder):
            show_budget("Turn 1/10 | $0.0012 [warning]")
        assert "[warning]" in recorder.export_text()


class TestShowDelta:
    def test_no_crash(self) -> None:
        show_delta("Hello")

    def test_bracket_content_not_swallowed_as_markup(self) -> None:
        recorder = _recording_console()
        with patch.object(display, "console", recorder):
            show_delta("a list[str] type hint")
        assert "list[str]" in recorder.export_text()


class TestShowThinkingDelta:
    def test_no_crash(self) -> None:
        show_thinking_delta("pondering...")

    def test_bracket_content_not_swallowed_as_markup(self) -> None:
        recorder = _recording_console()
        with patch.object(display, "console", recorder):
            show_thinking_delta("considering list[str] as the type")
        assert "list[str]" in recorder.export_text()


class TestPromptUser:
    def test_returns_input(self) -> None:
        with patch("builtins.input", return_value="hello"):
            result = prompt_user()
        assert result == "hello"
