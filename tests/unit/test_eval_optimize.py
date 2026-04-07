"""Tests for agent_harness.loops.eval_optimize."""

from unittest.mock import MagicMock

from agent_harness.loops.eval_optimize import _extract_score, run
from agent_harness.types import AgentConfig, Message, Response, Usage


def _config() -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=10,
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
