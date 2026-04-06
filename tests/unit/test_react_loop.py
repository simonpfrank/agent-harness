"""Tests for agent_harness.loops.react."""

from unittest.mock import MagicMock

from agent_harness.loops.react import run
from agent_harness.types import AgentConfig, Message, Response, ToolCall, ToolResult, Usage


def _config(max_turns: int = 10) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test",
        instructions="test",
        max_turns=max_turns,
    )


def _response(content: str, stop_reason: str = "end_turn",
              tool_calls: list[ToolCall] | None = None) -> Response:
    msg = Message(role="assistant", content=content, tool_calls=tool_calls)
    return Response(message=msg, usage=Usage(10, 5), stop_reason=stop_reason)


class TestRunSimple:
    def test_returns_content_on_end_turn(self) -> None:
        chat_fn = MagicMock(return_value=_response("Hello!"))
        messages = [Message(role="user", content="hi")]
        result = run(chat_fn, messages, [], _config())
        assert result == "Hello!"
        chat_fn.assert_called_once()

    def test_passes_messages_and_tools(self) -> None:
        chat_fn = MagicMock(return_value=_response("done"))
        messages = [Message(role="user", content="hi")]
        schemas = [{"name": "test", "description": "t", "input_schema": {}}]
        run(chat_fn, messages, schemas, _config())
        call_args = chat_fn.call_args
        assert call_args[0][0] is messages
        assert call_args[0][1] is schemas


class TestRunWithToolCalls:
    def test_executes_tools_and_continues(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo"})
        responses = [
            _response("reading", stop_reason="tool_use", tool_calls=[tc]),
            _response("The file says hello"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            return_value=ToolResult(tool_call_id="tc_1", output="hello")
        )
        messages = [Message(role="user", content="read foo")]
        result = run(chat_fn, messages, [], _config(), on_tool_call=on_tool_call)
        assert result == "The file says hello"
        assert chat_fn.call_count == 2
        on_tool_call.assert_called_once_with(tc)


class TestRunMaxTurns:
    def test_stops_at_max_turns(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={})
        chat_fn = MagicMock(
            return_value=_response("loop", stop_reason="tool_use", tool_calls=[tc])
        )
        on_tool_call = MagicMock(
            return_value=ToolResult(tool_call_id="tc_1", output="data")
        )
        messages = [Message(role="user", content="go")]
        run(chat_fn, messages, [], _config(max_turns=3), on_tool_call=on_tool_call)
        assert chat_fn.call_count == 3


class TestRunCallbacks:
    def test_on_response_called(self) -> None:
        resp = _response("hi")
        chat_fn = MagicMock(return_value=resp)
        on_response = MagicMock()
        run(chat_fn, [Message(role="user", content="hi")], [], _config(),
            on_response=on_response)
        on_response.assert_called_once_with(resp)

    def test_on_budget_stops_loop(self) -> None:
        tc = ToolCall(id="tc_1", name="test", arguments={})
        chat_fn = MagicMock(
            return_value=_response("go", stop_reason="tool_use", tool_calls=[tc])
        )
        on_tool_call = MagicMock(
            return_value=ToolResult(tool_call_id="tc_1", output="ok")
        )
        on_budget = MagicMock(return_value=True)  # budget exceeded immediately
        run(chat_fn, [Message(role="user", content="go")], [], _config(),
            on_tool_call=on_tool_call, on_budget=on_budget)
        assert chat_fn.call_count == 1  # stopped after first call
