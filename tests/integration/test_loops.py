"""Integration tests for all loop patterns with mock providers."""

from unittest.mock import MagicMock

from agent_harness.config import load
from agent_harness.loops import registry as loop_registry
from agent_harness.types import (
    LoopCallbacks,
    Message,
    Response,
    ToolCall,
    ToolResult,
    Usage,
)


def _response(content: str, tool_calls: list[ToolCall] | None = None) -> Response:
    stop = "tool_use" if tool_calls else "end_turn"
    msg = Message(role="assistant", content=content, tool_calls=tool_calls)
    return Response(message=msg, usage=Usage(10, 5), stop_reason=stop)


class TestAllLoopsRegistered:
    def test_seven_loops_available(self) -> None:
        expected = {"react", "plan_execute", "rewoo", "reflection", "eval_optimize", "ralph", "debate"}
        assert expected.issubset(set(loop_registry.keys()))


class TestReWOOIntegration:
    def test_plan_and_solve(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "test.txt"})
        responses = [_response("reading", tool_calls=[tc]), _response("file says hello")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool = MagicMock(return_value=ToolResult(tool_call_id="tc_1", output="hello"))
        cb = LoopCallbacks(on_tool_call=on_tool)

        cfg = load("agents/hello")
        messages = [Message(role="user", content="read test.txt")]
        result = loop_registry["rewoo"](chat_fn, messages, [{"name": "read_file"}], cfg, cb)
        assert "hello" in result.lower()


class TestReflectionIntegration:
    def test_critique_and_refine(self) -> None:
        responses = [_response("draft"), _response("DONE")]
        chat_fn = MagicMock(side_effect=responses)
        cfg = load("agents/hello")
        messages = [Message(role="user", content="write something")]
        result = loop_registry["reflection"](chat_fn, messages, [], cfg)
        assert "draft" in result


class TestEvalOptimizeIntegration:
    def test_score_passes(self) -> None:
        responses = [_response("good output"), _response("SCORE: 9/10")]
        chat_fn = MagicMock(side_effect=responses)
        cfg = load("agents/hello")
        messages = [Message(role="user", content="write")]
        result = loop_registry["eval_optimize"](chat_fn, messages, [], cfg)
        assert "good output" in result


class TestRalphIntegration:
    def test_retries_until_done(self) -> None:
        responses = [_response("failed"), _response("success DONE")]
        chat_fn = MagicMock(side_effect=responses)
        cfg = load("agents/hello")
        messages = [Message(role="system", content="sys"), Message(role="user", content="do it")]
        result = loop_registry["ralph"](chat_fn, messages, [], cfg)
        assert "DONE" in result


class TestDebateIntegration:
    def test_produces_synthesis(self) -> None:
        responses = [_response("FOR"), _response("AGAINST"), _response("balanced synthesis")]
        chat_fn = MagicMock(side_effect=responses)
        cfg = load("agents/hello")
        cfg_debate = type(cfg)(**{**cfg.__dict__, "max_turns": 1})
        messages = [Message(role="user", content="debate X")]
        result = loop_registry["debate"](chat_fn, messages, [], cfg_debate)
        assert "synthesis" in result.lower()
