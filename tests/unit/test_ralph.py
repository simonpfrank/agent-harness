"""Tests for agent_harness.loops.ralph."""

from unittest.mock import MagicMock

from agent_harness.loops.ralph import run
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall, ToolResult, Usage


def _config(max_turns: int = 5, completion_check: str | None = None) -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="test",
        agent_dir="/tmp/test", instructions="test", max_turns=max_turns,
        completion_check=completion_check,
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


class TestBudgetExceededStopsRetrying:
    def test_stops_outer_loop_once_budget_exceeded(self) -> None:
        """Budget already exceeded: the current attempt still runs (matches
        react.py's own "always at least one call" pattern), but no further
        attempt starts afterward."""
        chat_fn = MagicMock(return_value=_response("still failing"))
        cb = LoopCallbacks(is_budget_exceeded=lambda: True)
        messages = [Message(role="user", content="do it")]
        run(chat_fn, messages, [], _config(max_turns=5), cb)
        assert chat_fn.call_count == 1

    def test_continues_when_budget_not_exceeded(self) -> None:
        chat_fn = MagicMock(return_value=_response("still failing"))
        cb = LoopCallbacks(is_budget_exceeded=lambda: False)
        messages = [Message(role="user", content="do it")]
        run(chat_fn, messages, [], _config(max_turns=3), cb)
        assert chat_fn.call_count == 3

    def test_no_callback_wired_keeps_existing_behavior(self) -> None:
        chat_fn = MagicMock(return_value=_response("still failing"))
        messages = [Message(role="user", content="do it")]
        run(chat_fn, messages, [], _config(max_turns=3))
        assert chat_fn.call_count == 3


class TestRalphCompletionCheck:
    def test_accepts_done_when_check_passes(self) -> None:
        chat_fn = MagicMock(return_value=_response("Task complete. DONE"))
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="PASS"))
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        messages = [Message(role="user", content="do it")]
        result = run(chat_fn, messages, [], _config(completion_check="verify"), cb)
        assert "DONE" in result
        on_tool_call.assert_called_once()

    def test_feeds_failure_back_into_same_attempt_not_fresh_context(self) -> None:
        call_messages: list[list[Message]] = []

        def tracking_chat(msgs: list[Message], *a: object, **kw: object) -> Response:
            call_messages.append(list(msgs))
            return _response("Task complete. DONE")

        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="x", output="FAIL: not yet"),
                ToolResult(tool_call_id="x", output="PASS"),
            ],
        )
        cb = LoopCallbacks(on_tool_call=on_tool_call, is_budget_exceeded=lambda: False)
        system = Message(role="system", content="sys")
        user = Message(role="user", content="do it")
        result = run(tracking_chat, [system, user], [], _config(max_turns=5, completion_check="verify"), cb)

        assert "DONE" in result
        assert len(call_messages) == 2
        # Second react_run call happens within the SAME attempt: it carries
        # the failure feedback appended to the first attempt's messages,
        # not a fresh system+user-only restart.
        assert len(call_messages[1]) > len(call_messages[0])
        feedback = [m.content or "" for m in call_messages[1] if m.role == "user"]
        assert any("FAIL: not yet" in m for m in feedback)

    def test_stops_when_shared_budget_exhausted_mid_verification_retry(self) -> None:
        chat_fn = MagicMock(return_value=_response("Task complete. DONE"))
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="FAIL: never passes"))
        cb = LoopCallbacks(on_tool_call=on_tool_call, is_budget_exceeded=lambda: True)
        messages = [Message(role="user", content="do it")]
        run(chat_fn, messages, [], _config(max_turns=5, completion_check="verify"), cb)
        # Budget already exceeded before the first check even runs a second time —
        # exactly one react_run call, one completion_check call, then stop.
        assert chat_fn.call_count == 1
        assert on_tool_call.call_count == 1

    def test_fires_on_completion_status_true(self) -> None:
        chat_fn = MagicMock(return_value=_response("Task complete. DONE"))
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="x", output="PASS: good"))
        status_calls = []
        cb = LoopCallbacks(on_tool_call=on_tool_call, on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="do it")], [], _config(completion_check="verify"), cb)
        assert status_calls == [(True, "PASS: good")]

    def test_fires_on_completion_status_false_when_max_attempts_exhausted(self) -> None:
        chat_fn = MagicMock(return_value=_response("still failing"))
        status_calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="do it")], [], _config(max_turns=2, completion_check="verify"), cb)
        assert len(status_calls) == 1
        assert status_calls[0][0] is False

    def test_no_completion_status_call_when_completion_check_unset(self) -> None:
        chat_fn = MagicMock(return_value=_response("Task complete. DONE"))
        status_calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: status_calls.append((v, d)))
        run(chat_fn, [Message(role="user", content="do it")], [], _config(), cb)
        assert status_calls == []
