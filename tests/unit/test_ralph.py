"""Tests for agent_harness.loops.ralph."""

from unittest.mock import MagicMock

from agent_harness.loops.ralph import run
from agent_harness.types import AgentConfig, Message, Response, ToolCall, Usage


def _config(max_turns: int = 5) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=max_turns,
    )


def _response(content: str, tool_calls: list[ToolCall] | None = None) -> Response:
    msg = Message(role="assistant", content=content, tool_calls=tool_calls)
    return Response(message=msg, usage=Usage(10, 5), stop_reason="end_turn" if not tool_calls else "tool_use")


class TestRalphLoop:
    def test_succeeds_on_first_try(self) -> None:
        """If react run produces DONE, return immediately."""
        chat_fn = MagicMock(return_value=_response("Task complete. DONE"))
        messages = [Message(role="user", content="do it")]
        result = run(chat_fn, messages, [], _config())
        assert "DONE" in result

    def test_retries_on_failure(self) -> None:
        """If no DONE, retry with fresh context."""
        responses = [
            _response("I tried but failed"),
            _response("Got it this time. DONE"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="do it")]
        result = run(chat_fn, messages, [], _config())
        assert "DONE" in result
        assert chat_fn.call_count == 2

    def test_max_attempts_stops(self) -> None:
        """Stops after max_turns attempts."""
        chat_fn = MagicMock(return_value=_response("still failing"))
        messages = [Message(role="user", content="do it")]
        run(chat_fn, messages, [], _config(max_turns=3))
        assert chat_fn.call_count == 3

    def test_fresh_context_each_retry(self) -> None:
        """Each retry should start with just the system + user messages."""
        call_messages: list[list[Message]] = []

        def tracking_chat(msgs: list[Message], *a: object, **kw: object) -> Response:
            call_messages.append(list(msgs))
            return _response("failed again")

        system = Message(role="system", content="sys")
        user = Message(role="user", content="do it")
        run(tracking_chat, [system, user], [], _config(max_turns=3))

        # Each call should have same number of initial messages (system + user)
        for msgs in call_messages:
            assert msgs[0].role == "system"
            assert msgs[-1].role == "user"

    def test_registered(self) -> None:
        from agent_harness.loops import registry
        assert "ralph" in registry
