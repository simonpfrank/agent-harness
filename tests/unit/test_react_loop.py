"""Tests for agent_harness.loops.react."""

from unittest.mock import MagicMock

from agent_harness.loops.react import run
from agent_harness.types import (
    AgentConfig,
    Attachment,
    LoopCallbacks,
    Message,
    Response,
    ToolCall,
    ToolResult,
    Usage,
)


def _config(max_turns: int = 10, stream: bool = False, thrash_threshold: int = 3) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test",
        instructions="test",
        max_turns=max_turns,
        stream=stream,
        thrash_threshold=thrash_threshold,
    )


def _response(
    content: str,
    stop_reason: str = "end_turn",
    tool_calls: list[ToolCall] | None = None,
) -> Response:
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
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        result = run(chat_fn, messages, [], _config(), callbacks=cb)
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
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        run(chat_fn, messages, [], _config(max_turns=3), callbacks=cb)
        assert chat_fn.call_count == 3


class TestBudgetStatusInjection:
    def test_injects_note_into_call_messages_only(self) -> None:
        chat_fn = MagicMock(return_value=_response("hi"))
        get_budget_status = MagicMock(return_value="You have 3 turn(s) remaining.")
        cb = LoopCallbacks(get_budget_status=get_budget_status)
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="hi"),
        ]
        original_rest = list(messages[1:])
        run(chat_fn, messages, [], _config(), callbacks=cb)

        call_messages = chat_fn.call_args[0][0]
        assert call_messages[0].role == "system"
        assert call_messages[0].content == (
            "You are a helpful assistant.\n\nYou have 3 turn(s) remaining."
        )
        assert call_messages[1:] == original_rest

    def test_canonical_messages_never_mutated(self) -> None:
        """Regression test: the stored system message must never carry the
        note, or a resumed session would replay a stale budget line forever."""
        chat_fn = MagicMock(return_value=_response("hi"))
        get_budget_status = MagicMock(return_value="You have 3 turn(s) remaining.")
        cb = LoopCallbacks(get_budget_status=get_budget_status)
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="hi"),
        ]
        run(chat_fn, messages, [], _config(), callbacks=cb)

        assert messages[0].content == "You are a helpful assistant."

    def test_no_injection_when_callback_absent(self) -> None:
        chat_fn = MagicMock(return_value=_response("hi"))
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="hi"),
        ]
        run(chat_fn, messages, [], _config())

        call_messages = chat_fn.call_args[0][0]
        assert call_messages is messages
        assert call_messages[0].content == "You are a helpful assistant."

    def test_no_injection_when_no_system_message(self) -> None:
        chat_fn = MagicMock(return_value=_response("hi"))
        get_budget_status = MagicMock(return_value="You have 3 turn(s) remaining.")
        cb = LoopCallbacks(get_budget_status=get_budget_status)
        messages = [Message(role="user", content="hi")]
        run(chat_fn, messages, [], _config(), callbacks=cb)

        call_messages = chat_fn.call_args[0][0]
        assert call_messages is messages


class TestAttachmentPruning:
    def test_only_most_recent_attachment_stays_live(self) -> None:
        tc1 = ToolCall(id="tc_1", name="view_image", arguments={"path": "a.png"})
        tc2 = ToolCall(id="tc_2", name="view_image", arguments={"path": "b.png"})
        attachment1 = Attachment(kind="image", media_type="image/png", data="AAAA", filename="a.png")
        attachment2 = Attachment(kind="image", media_type="image/png", data="BBBB", filename="b.png")
        responses = [
            _response("viewing a", stop_reason="tool_use", tool_calls=[tc1]),
            _response("viewing b", stop_reason="tool_use", tool_calls=[tc2]),
            _response("done"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="tc_1", output="Viewing a.png", attachment=attachment1),
                ToolResult(tool_call_id="tc_2", output="Viewing b.png", attachment=attachment2),
            ]
        )
        messages = [Message(role="user", content="look at these")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)

        run(chat_fn, messages, [], _config(), callbacks=cb)

        final_call_messages = chat_fn.call_args_list[-1][0][0]
        attachment_bearing = [
            m for m in final_call_messages if m.tool_result is not None and m.tool_result.attachment is not None
        ]
        assert len(attachment_bearing) == 1
        assert attachment_bearing[0].tool_result.attachment.filename == "b.png"

    def test_canonical_messages_keep_all_attachments(self) -> None:
        tc1 = ToolCall(id="tc_1", name="view_image", arguments={"path": "a.png"})
        tc2 = ToolCall(id="tc_2", name="view_image", arguments={"path": "b.png"})
        attachment1 = Attachment(kind="image", media_type="image/png", data="AAAA", filename="a.png")
        attachment2 = Attachment(kind="image", media_type="image/png", data="BBBB", filename="b.png")
        responses = [
            _response("viewing a", stop_reason="tool_use", tool_calls=[tc1]),
            _response("viewing b", stop_reason="tool_use", tool_calls=[tc2]),
            _response("done"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="tc_1", output="Viewing a.png", attachment=attachment1),
                ToolResult(tool_call_id="tc_2", output="Viewing b.png", attachment=attachment2),
            ]
        )
        messages = [Message(role="user", content="look at these")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)

        run(chat_fn, messages, [], _config(), callbacks=cb)

        attachment_bearing = [
            m for m in messages if m.tool_result is not None and m.tool_result.attachment is not None
        ]
        assert len(attachment_bearing) == 2


class TestRunStreaming:
    def test_forwards_stream_flag(self) -> None:
        chat_fn = MagicMock(return_value=_response("hi"))
        run(chat_fn, [Message(role="user", content="hi")], [], _config(stream=True))
        assert chat_fn.call_args.kwargs["stream"] is True

    def test_forwards_stream_false_by_default(self) -> None:
        chat_fn = MagicMock(return_value=_response("hi"))
        run(chat_fn, [Message(role="user", content="hi")], [], _config())
        assert chat_fn.call_args.kwargs["stream"] is False

    def test_forwards_delta_callbacks(self) -> None:
        chat_fn = MagicMock(return_value=_response("hi"))
        on_delta = MagicMock()
        on_thinking_delta = MagicMock()
        cb = LoopCallbacks(on_delta=on_delta, on_thinking_delta=on_thinking_delta)
        run(chat_fn, [Message(role="user", content="hi")], [], _config(stream=True), callbacks=cb)
        assert chat_fn.call_args.kwargs["on_delta"] is on_delta
        assert chat_fn.call_args.kwargs["on_thinking_delta"] is on_thinking_delta


class TestRunCallbacks:
    def test_on_response_called(self) -> None:
        resp = _response("hi")
        chat_fn = MagicMock(return_value=resp)
        on_response = MagicMock()
        cb = LoopCallbacks(on_response=on_response)
        run(chat_fn, [Message(role="user", content="hi")], [], _config(), callbacks=cb)
        on_response.assert_called_once_with(resp)

    def test_on_budget_stops_loop(self) -> None:
        tc = ToolCall(id="tc_1", name="test", arguments={})
        chat_fn = MagicMock(
            return_value=_response("go", stop_reason="tool_use", tool_calls=[tc])
        )
        on_tool_call = MagicMock(
            return_value=ToolResult(tool_call_id="tc_1", output="ok")
        )
        on_budget = MagicMock(return_value=True)
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call, on_budget=on_budget)
        run(chat_fn, messages, [], _config(), callbacks=cb)
        assert chat_fn.call_count == 1

    def test_on_budget_still_resolves_pending_tool_call(self) -> None:
        """A tool_use response must always get its tool_result, even when budget
        is exceeded on the same turn — otherwise the next API call sees a
        dangling tool_use and the provider rejects the whole conversation."""
        tc = ToolCall(id="tc_1", name="test", arguments={})
        chat_fn = MagicMock(
            return_value=_response("go", stop_reason="tool_use", tool_calls=[tc])
        )
        on_tool_call = MagicMock(
            return_value=ToolResult(tool_call_id="tc_1", output="ok")
        )
        on_budget = MagicMock(return_value=True)
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call, on_budget=on_budget)
        run(chat_fn, messages, [], _config(), callbacks=cb)
        on_tool_call.assert_called_once_with(tc)
        assert messages[-1].role == "tool"
        assert messages[-1].tool_result is not None
        assert messages[-1].tool_result.tool_call_id == "tc_1"


def _nudges(messages: list[Message]) -> list[Message]:
    return [m for m in messages if m.role == "user" and m.content and "Thrash guard" in m.content]


class TestThrashDetection:
    def test_error_streak_triggers_one_nudge_after_the_turn(self) -> None:
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        responses = [
            _response("try", stop_reason="tool_use", tool_calls=[tc]),
            _response("try", stop_reason="tool_use", tool_calls=[tc]),
            _response("try", stop_reason="tool_use", tool_calls=[tc]),
            _response("done"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="tc_1", error="boom"),
                ToolResult(tool_call_id="tc_1", error="boom"),
                ToolResult(tool_call_id="tc_1", error="boom"),
            ],
        )
        messages = [Message(role="user", content="search for x")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        run(chat_fn, messages, [], _config(thrash_threshold=3), callbacks=cb)
        nudges = _nudges(messages)
        assert len(nudges) == 1
        # nudge sits right after the 3rd (final) error result, before the next assistant turn
        idx = messages.index(nudges[0])
        prior_result = messages[idx - 1].tool_result
        assert messages[idx - 1].role == "tool"
        assert prior_result is not None
        assert prior_result.error == "boom"
        assert messages[idx + 1].role == "assistant"
        assert messages[idx + 1].content == "done"

    def test_below_threshold_no_nudge(self) -> None:
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        responses = [
            _response("try", stop_reason="tool_use", tool_calls=[tc]),
            _response("done"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="tc_1", error="boom"))
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        run(chat_fn, messages, [], _config(thrash_threshold=3), callbacks=cb)
        assert _nudges(messages) == []

    def test_threshold_zero_disables_detection(self) -> None:
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        responses = [_response("try", stop_reason="tool_use", tool_calls=[tc])] * 3 + [_response("done")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="tc_1", error="boom"))
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        run(chat_fn, messages, [], _config(thrash_threshold=0), callbacks=cb)
        assert _nudges(messages) == []

    def test_duplicate_args_triggers_nudge(self) -> None:
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        responses = [_response("try", stop_reason="tool_use", tool_calls=[tc])] * 3 + [_response("done")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="tc_1", output="no results"))
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        run(chat_fn, messages, [], _config(thrash_threshold=3), callbacks=cb)
        assert len(_nudges(messages)) == 1

    def test_on_thrash_detected_called_with_tool_and_detail(self) -> None:
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        responses = [_response("try", stop_reason="tool_use", tool_calls=[tc])] * 3 + [_response("done")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="tc_1", error="boom"))
        on_thrash_detected = MagicMock()
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call, on_thrash_detected=on_thrash_detected)
        run(chat_fn, messages, [], _config(thrash_threshold=3), callbacks=cb)
        on_thrash_detected.assert_called_once()
        args = on_thrash_detected.call_args[0]
        assert args[0] == "search"
        assert isinstance(args[1], str)

    def test_no_crash_when_on_thrash_detected_unset(self) -> None:
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        responses = [_response("try", stop_reason="tool_use", tool_calls=[tc])] * 3 + [_response("done")]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(return_value=ToolResult(tool_call_id="tc_1", error="boom"))
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        result = run(chat_fn, messages, [], _config(thrash_threshold=3), callbacks=cb)
        assert result == "done"

    def test_multi_tool_call_turn_nudge_positioned_after_both_results(self) -> None:
        """A turn with two tool calls where thrashing is detected on the
        second must not inject the nudge between the two tool_result
        messages — both results must stay contiguous, matching how a
        provider correlates tool_use/tool_result pairs for one turn."""
        search_1 = ToolCall(id="tc_1", name="search", arguments={"q": "x"})
        read = ToolCall(id="tc_2", name="read_file", arguments={"path": "a"})
        search_2 = ToolCall(id="tc_3", name="search", arguments={"q": "x"})
        responses = [
            _response("try", stop_reason="tool_use", tool_calls=[search_1]),
            _response("try both", stop_reason="tool_use", tool_calls=[read, search_2]),
            _response("done"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        on_tool_call = MagicMock(
            side_effect=[
                ToolResult(tool_call_id="tc_1", output="no results"),
                ToolResult(tool_call_id="tc_2", output="file contents"),
                ToolResult(tool_call_id="tc_3", output="no results"),
            ],
        )
        messages = [Message(role="user", content="go")]
        cb = LoopCallbacks(on_tool_call=on_tool_call)
        run(chat_fn, messages, [], _config(thrash_threshold=2), callbacks=cb)
        nudges = _nudges(messages)
        assert len(nudges) == 1
        idx = messages.index(nudges[0])
        # the two tool-role messages from the second turn are contiguous,
        # immediately preceding the nudge — not split by it
        last_result = messages[idx - 1].tool_result
        prev_result = messages[idx - 2].tool_result
        assert messages[idx - 1].role == "tool"
        assert last_result is not None
        assert last_result.tool_call_id == "tc_3"
        assert messages[idx - 2].role == "tool"
        assert prev_result is not None
        assert prev_result.tool_call_id == "tc_2"
