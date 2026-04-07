"""Tests for agent_harness.loops.debate."""

from unittest.mock import MagicMock

from agent_harness.loops.debate import run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, Usage


def _config(max_turns: int = 3) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=max_turns,
    )


def _response(content: str) -> Response:
    msg = Message(role="assistant", content=content)
    return Response(message=msg, usage=Usage(10, 5), stop_reason="end_turn")


class TestDebateLoop:
    def test_produces_synthesis(self) -> None:
        """Debate should end with a synthesised answer."""
        responses = [
            _response("I argue FOR because X"),
            _response("I argue AGAINST because Y"),
            _response("Weighing both sides, the answer is Z"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="Should we do X?")]
        result = run(chat_fn, messages, [], _config(max_turns=1))
        assert "Z" in result
        # 1 round × 2 debaters + 1 synthesis = 3
        assert chat_fn.call_count == 3

    def test_multiple_rounds(self) -> None:
        """Multiple debate rounds before synthesis."""
        responses = [
            _response("FOR round 1"),
            _response("AGAINST round 1"),
            _response("FOR round 2, responding to AGAINST"),
            _response("AGAINST round 2, responding to FOR"),
            _response("Synthesis after 2 rounds"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="debate this")]
        result = run(chat_fn, messages, [], _config(max_turns=2))
        assert "Synthesis" in result
        assert chat_fn.call_count == 5  # 2 rounds × 2 + synthesis

    def test_on_response_called(self) -> None:
        responses = [
            _response("FOR"),
            _response("AGAINST"),
            _response("SYNTHESIS"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_response = MagicMock()
        cb = LoopCallbacks(on_response=on_response)
        run(chat_fn, [Message(role="user", content="go")], [], _config(max_turns=1), cb)
        assert on_response.call_count == 3

    def test_registered(self) -> None:
        from agent_harness.loops import registry
        assert "debate" in registry
