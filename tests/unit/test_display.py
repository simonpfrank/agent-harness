"""Tests for agent_harness.display."""

from unittest.mock import patch

from agent_harness.display import (
    prompt_user,
    show_budget,
    show_response,
    show_tool_call,
    show_tool_result,
)
from agent_harness.types import Message, Response, ToolCall, ToolResult, Usage


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


class TestShowToolResult:
    def test_success_no_crash(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file contents here")
        show_tool_result(tr)

    def test_error_no_crash(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", error="file not found")
        show_tool_result(tr)


class TestShowBudget:
    def test_no_crash(self) -> None:
        show_budget("Turn 1/10 | $0.0012")


class TestPromptUser:
    def test_returns_input(self) -> None:
        with patch("builtins.input", return_value="hello"):
            result = prompt_user()
        assert result == "hello"
