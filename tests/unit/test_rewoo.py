"""Tests for agent_harness.loops.rewoo."""

from unittest.mock import MagicMock

from agent_harness.loops.rewoo import _parse_tool_calls, run
from agent_harness.types import AgentConfig, Message, Response, ToolCall, ToolResult, Usage


def _config() -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=10,
    )


def _response(content: str, tool_calls: list[ToolCall] | None = None) -> Response:
    msg = Message(role="assistant", content=content, tool_calls=tool_calls)
    return Response(message=msg, usage=Usage(10, 5), stop_reason="end_turn" if not tool_calls else "tool_use")


class TestParseToolCalls:
    def test_extracts_tool_calls(self) -> None:
        tc1 = ToolCall(id="tc_1", name="read_file", arguments={"path": "a.txt"})
        tc2 = ToolCall(id="tc_2", name="run_command", arguments={"command": "ls"})
        response = _response("planning", tool_calls=[tc1, tc2])
        calls = _parse_tool_calls(response)
        assert len(calls) == 2
        assert calls[0].name == "read_file"

    def test_no_tool_calls(self) -> None:
        response = _response("just text")
        assert _parse_tool_calls(response) == []


class TestReWOOLoop:
    def test_plan_execute_solve(self) -> None:
        """Three phases: plan (with tools), execute tools, solve."""
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "x"})
        plan_resp = _response("I'll read the file", tool_calls=[tc])
        solve_resp = _response("The file contains hello")

        chat_fn = MagicMock(side_effect=[plan_resp, solve_resp])
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="tc_1", output="hello"))

        from agent_harness.types import LoopCallbacks
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        messages = [Message(role="user", content="read x")]
        result = run(chat_fn, messages, [{"name": "read_file"}], _config(), cb)

        assert "hello" in result.lower()
        assert chat_fn.call_count == 2  # plan + solve
        on_tool_call.assert_called_once()

    def test_no_tools_in_plan_returns_directly(self) -> None:
        """If plan has no tool calls, return the plan response directly."""
        plan_resp = _response("The answer is 42")
        chat_fn = MagicMock(return_value=plan_resp)
        messages = [Message(role="user", content="what is 42")]
        result = run(chat_fn, messages, [], _config())
        assert "42" in result

    def test_registered(self) -> None:
        from agent_harness.loops import registry
        assert "rewoo" in registry
