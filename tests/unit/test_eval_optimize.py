"""Tests for agent_harness.loops.eval_optimize."""

from unittest.mock import MagicMock

from agent_harness.loops.eval_optimize import _extract_score, run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolResult, Usage


def _config(stream: bool = False, max_turns: int = 10, completion_check: str | None = None) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=max_turns, stream=stream,
        completion_check=completion_check,
    )


def _response(content: str) -> Response:
    msg = Message(role="assistant", content=content)
    return Response(message=msg, usage=Usage(10, 5), stop_reason="end_turn")


class TestExtractScore:
    def test_extracts_score(self) -> None:
        assert _extract_score("Good work. SCORE: 8/10") == 8

    def test_no_score_returns_zero(self) -> None:
        assert _extract_score("No score here") == 0

    def test_extracts_from_multiline(self) -> None:
        assert _extract_score("Feedback\nSCORE: 9/10\nDone") == 9


class TestEvalOptimizeLoop:
    def test_passes_on_high_score(self) -> None:
        responses = [
            _response("great output"),
            _response("Excellent. SCORE: 9/10"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="write something")]
        result = run(chat_fn, messages, [], _config())
        assert "great output" in result
        assert chat_fn.call_count == 2

    def test_iterates_on_low_score(self) -> None:
        responses = [
            _response("weak draft"),
            _response("Needs work. SCORE: 3/10"),
            _response("improved draft"),
            _response("Much better. SCORE: 8/10"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="write")]
        result = run(chat_fn, messages, [], _config())
        assert "improved" in result
        assert chat_fn.call_count == 4

    def test_registered(self) -> None:
        from agent_harness.loops import registry
        assert "eval_optimize" in registry

    def test_forwards_stream_flag(self) -> None:
        responses = [_response("great output"), _response("Excellent. SCORE: 9/10")]
        chat_fn = MagicMock(side_effect=responses)
        run(chat_fn, [Message(role="user", content="go")], [], _config(stream=True))
        for call in chat_fn.call_args_list:
            assert call.kwargs["stream"] is True


class TestEvalOptimizeCompletionCheck:
    def test_accepts_pass_when_completion_check_passes(self) -> None:
        responses = [_response("great output"), _response("Excellent. SCORE: 9/10")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="PASS"))
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        result = run(chat_fn, [Message(role="user", content="go")], [], _config(completion_check="verify"), cb)
        assert "great output" in result
        on_tool_call.assert_called_once()

    def test_rejects_pass_and_retries_when_completion_check_fails(self) -> None:
        responses = [
            _response("draft"),
            _response("SCORE: 9/10"),
            _response("fixed draft"),
            _response("SCORE: 9/10"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="x", output="FAIL: tests red"),
                ToolResult(tool_call_id="x", output="PASS"),
            ],
        )
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        messages = [Message(role="user", content="go")]
        result = run(chat_fn, messages, [], _config(max_turns=5, completion_check="verify"), cb)
        assert "fixed draft" in result
        assert chat_fn.call_count == 4
        feedback_messages = [m.content or "" for m in messages if m.role == "user"]
        assert any("FAIL: tests red" in m for m in feedback_messages)

    def test_completion_check_none_keeps_existing_behavior(self) -> None:
        responses = [_response("great output"), _response("Excellent. SCORE: 9/10")]
        chat_fn = MagicMock(side_effect=responses)
        result = run(chat_fn, [Message(role="user", content="go")], [], _config())
        assert "great output" in result

    def test_fires_on_completion_status_true(self) -> None:
        responses = [_response("great output"), _response("Excellent. SCORE: 9/10")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="PASS: good"))
        status_calls = []
        cb = LoopCallbacks(on_tool_call=on_tool_call, on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="go")], [], _config(completion_check="verify"), cb)
        assert status_calls == [(True, "PASS: good")]

    def test_fires_on_completion_status_false_on_max_turns_without_pass(self) -> None:
        chat_fn = MagicMock(return_value=_response("SCORE: 2/10"))
        status_calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="go")], [], _config(max_turns=2, completion_check="verify"), cb)
        assert len(status_calls) == 1
        assert status_calls[0][0] is False

    def test_no_completion_status_call_when_completion_check_unset(self) -> None:
        responses = [_response("great output"), _response("Excellent. SCORE: 9/10")]
        chat_fn = MagicMock(side_effect=responses)
        status_calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="go")], [], _config(), cb)
        assert status_calls == []
