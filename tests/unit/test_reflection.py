"""Tests for agent_harness.loops.reflection."""

from unittest.mock import MagicMock

from agent_harness.loops.reflection import run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, Usage


def _config(max_turns: int = 10) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=max_turns,
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
