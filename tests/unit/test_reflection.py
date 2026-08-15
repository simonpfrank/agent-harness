"""Tests for agent_harness.loops.reflection."""

from unittest.mock import MagicMock

from agent_harness.loops.reflection import run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolResult, Usage


def _config(max_turns: int = 10, stream: bool = False, completion_check: str | None = None) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=max_turns, stream=stream,
        completion_check=completion_check,
    )


def _response(content: str) -> Response:
    msg = Message(role="assistant", content=content)
    return Response(message=msg, usage=Usage(10, 5), stop_reason="end_turn")


class TestReflectionLoop:
    def test_accepts_on_first_try(self) -> None:
        """If critique says DONE, return immediately."""
        responses = [
            _response("draft answer"),
            _response("LGTM. DONE"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="write something")]
        result = run(chat_fn, messages, [], _config())
        assert "draft answer" in result
        assert chat_fn.call_count == 2  # generate + critique

    def test_refines_then_accepts(self) -> None:
        """Critique rejects first draft, accepts refined version."""
        responses = [
            _response("bad draft"),
            _response("Too vague. Needs more detail."),
            _response("improved draft with detail"),
            _response("DONE"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="write something")]
        result = run(chat_fn, messages, [], _config())
        assert "improved" in result
        assert chat_fn.call_count == 4

    def test_max_iterations_stops(self) -> None:
        """Stops after max_turns even if critique never says DONE."""
        chat_fn = MagicMock(return_value=_response("not done yet"))
        messages = [Message(role="user", content="go")]
        run(chat_fn, messages, [], _config(max_turns=3))
        # 3 iterations × 2 calls each = 6, but capped
        assert chat_fn.call_count <= 6

    def test_on_response_called(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        on_response = MagicMock()
        cb = LoopCallbacks(on_response=on_response)
        run(chat_fn, [Message(role="user", content="go")], [], _config(), cb)
        assert on_response.call_count >= 1

    def test_registered(self) -> None:
        from agent_harness.loops import registry
        assert "reflection" in registry

    def test_forwards_stream_flag(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        run(chat_fn, [Message(role="user", content="go")], [], _config(stream=True))
        for call in chat_fn.call_args_list:
            assert call.kwargs["stream"] is True


class TestReflectionCompletionCheck:
    def test_accepts_done_when_completion_check_passes(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="PASS"))
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        config = _config(completion_check="verify")
        result = run(chat_fn, [Message(role="user", content="go")], [], config, cb)
        assert "draft" in result
        assert chat_fn.call_count == 2
        on_tool_call.assert_called_once()

    def test_rejects_done_and_retries_when_completion_check_fails(self) -> None:
        responses = [
            _response("draft"),
            _response("DONE"),
            _response("fixed draft"),
            _response("DONE"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="x", output="FAIL: tests red"),
                ToolResult(tool_call_id="x", output="PASS"),
            ],
        )
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        config = _config(max_turns=5, completion_check="verify")
        messages = [Message(role="user", content="go")]
        result = run(chat_fn, messages, [], config, cb)
        assert "fixed draft" in result
        assert chat_fn.call_count == 4
        assert on_tool_call.call_count == 2
        feedback_messages = [m.content or "" for m in messages if m.role == "user"]
        assert any("FAIL: tests red" in m for m in feedback_messages)

    def test_completion_check_none_keeps_existing_behavior(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        cb = LoopCallbacks()
        result = run(chat_fn, [Message(role="user", content="go")], [], _config(), cb)
        assert "draft" in result
        assert chat_fn.call_count == 2

    def test_fires_on_completion_status_true_on_verified_done(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="PASS: good"))
        status_calls = []
        cb = LoopCallbacks(on_tool_call=on_tool_call, on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="go")], [], _config(completion_check="verify"), cb)
        assert status_calls == [(True, "PASS: good")]

    def test_fires_on_completion_status_false_on_max_turns_without_pass(self) -> None:
        chat_fn = MagicMock(return_value=_response("not done yet"))
        status_calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="go")], [], _config(max_turns=2, completion_check="verify"), cb)
        assert len(status_calls) == 1
        assert status_calls[0][0] is False

    def test_fires_on_completion_status_false_on_budget_exceeded_before_check(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        status_calls = []
        cb = LoopCallbacks(
            on_budget=lambda usage: True,
            on_completion_status=lambda v, d: status_calls.append((v, d)),
        )
        run(chat_fn, [Message(role="user", content="go")], [], _config(completion_check="verify"), cb)
        assert status_calls == [(False, "stopped: budget exceeded before completion was verified")]

    def test_no_completion_status_call_when_completion_check_unset(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        status_calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="go")], [], _config(), cb)
        assert status_calls == []
