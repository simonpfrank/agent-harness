"""Tests for agent_harness.loops.rewoo."""

from unittest.mock import MagicMock

from agent_harness.loops.rewoo import _parse_tool_calls, run
from agent_harness.types import AgentConfig, Attachment, LoopCallbacks, Message, Response, ToolCall, ToolResult, Usage


def _config(stream: bool = False) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=10, stream=stream,
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

    def test_prunes_attachments_before_solve_call(self) -> None:
        """Regression: rewoo has its own tool-execution path (doesn't
        delegate to react_run), so pruning needs its own wiring here too."""
        tc1 = ToolCall(id="tc_1", name="view_image", arguments={"path": "a.png"})
        tc2 = ToolCall(id="tc_2", name="view_image", arguments={"path": "b.png"})
        plan_resp = _response("viewing both", tool_calls=[tc1, tc2])
        solve_resp = _response("done")
        chat_fn = MagicMock(side_effect=[plan_resp, solve_resp])
        attachment1 = Attachment(kind="image", media_type="image/png", data="AAAA", filename="a.png")
        attachment2 = Attachment(kind="image", media_type="image/png", data="BBBB", filename="b.png")
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="tc_1", output="Viewing a.png", attachment=attachment1),
                ToolResult(tool_call_id="tc_2", output="Viewing b.png", attachment=attachment2),
            ]
        )
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        messages = [Message(role="user", content="look at these")]

        run(chat_fn, messages, [{"name": "view_image"}], _config(), cb)

        solve_call_messages = chat_fn.call_args_list[-1][0][0]
        attachment_bearing = [
            m for m in solve_call_messages if m.tool_result is not None and m.tool_result.attachment is not None
        ]
        assert len(attachment_bearing) == 1
        assert attachment_bearing[0].tool_result.attachment.filename == "b.png"
        # Canonical messages list keeps both — only the disposable overlay sent to chat_fn is pruned.
        canonical_bearing = [
            m for m in messages if m.tool_result is not None and m.tool_result.attachment is not None
        ]
        assert len(canonical_bearing) == 2

    def test_forwards_stream_flag(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "x"})
        plan_resp = _response("reading", tool_calls=[tc])
        solve_resp = _response("done")
        chat_fn = MagicMock(side_effect=[plan_resp, solve_resp])
        messages = [Message(role="user", content="read x")]
        run(chat_fn, messages, [{"name": "read_file"}], _config(stream=True))
        for call in chat_fn.call_args_list:
            assert call.kwargs["stream"] is True
