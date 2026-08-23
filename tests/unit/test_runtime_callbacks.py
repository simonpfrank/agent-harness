"""Tests for agent_harness.runtime_callbacks."""

from unittest.mock import MagicMock, patch

from agent_harness.runtime_callbacks import make_callbacks
from agent_harness.types import LoopCallbacks, Message, OutputSink, Response, ToolCall, ToolResult, Usage


def _callbacks(*, stream: bool, show_thinking: bool, show_output: bool = True) -> LoopCallbacks:
    return make_callbacks(
        budget=MagicMock(),
        hooks=MagicMock(),
        permissions=MagicMock(),
        tracer=MagicMock(),
        tool_registry={},
        max_output_chars=10_000,
        show_output=show_output,
        stream=stream,
        show_thinking=show_thinking,
    )


class TestOnDelta:
    @patch("agent_harness.runtime_callbacks.show_delta")
    def test_shows_delta_when_show_output(self, mock_show_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        mock_show_delta.assert_called_once_with("hi")

    @patch("agent_harness.runtime_callbacks.show_delta")
    def test_hidden_when_show_output_false(self, mock_show_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=False)
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        mock_show_delta.assert_not_called()


class TestOnThinkingDelta:
    @patch("agent_harness.runtime_callbacks.show_thinking_delta")
    def test_shows_when_show_thinking_true(self, mock_show_thinking_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=True, show_output=True)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_called_once_with("pondering")

    @patch("agent_harness.runtime_callbacks.show_thinking_delta")
    def test_hidden_when_show_thinking_false(self, mock_show_thinking_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_not_called()

    @patch("agent_harness.runtime_callbacks.show_thinking_delta")
    def test_hidden_when_show_output_false_even_if_show_thinking_true(
        self, mock_show_thinking_delta: MagicMock,
    ) -> None:
        cb = _callbacks(stream=True, show_thinking=True, show_output=False)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_not_called()


class TestOnResponse:
    @patch("agent_harness.runtime_callbacks.show_response")
    def test_skips_show_response_when_streaming(self, mock_show_response: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        response = Response(
            message=Message(role="assistant", content="hi"),
            usage=Usage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
        assert cb.on_response is not None
        cb.on_response(response)
        mock_show_response.assert_not_called()

    @patch("agent_harness.runtime_callbacks.show_response")
    def test_shows_response_when_not_streaming(self, mock_show_response: MagicMock) -> None:
        cb = _callbacks(stream=False, show_thinking=False, show_output=True)
        response = Response(
            message=Message(role="assistant", content="hi"),
            usage=Usage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
        assert cb.on_response is not None
        cb.on_response(response)
        mock_show_response.assert_called_once_with(response)


class TestOnBudget:
    @patch("agent_harness.runtime_callbacks.show_budget")
    def test_shows_plain_summary_when_not_exceeded(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = False
        budget.summary.return_value = "Turn 3/15 | $0.05/$0.30"
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        exceeded = cb.on_budget(Usage(10, 5))
        assert exceeded is False
        shown = mock_show_budget.call_args.args[0]
        assert "Turn 3/15 | $0.05/$0.30" in shown

    @patch("agent_harness.runtime_callbacks.show_budget")
    def test_flags_stop_when_exceeded(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = True
        budget.summary.return_value = "Turn 15/15 | $0.2372/$0.30"
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        exceeded = cb.on_budget(Usage(10, 5))
        assert exceeded is True
        shown = mock_show_budget.call_args.args[0]
        assert "Turn 15/15 | $0.2372/$0.30" in shown
        assert "stopping" in shown.lower()

    @patch("agent_harness.runtime_callbacks.show_budget")
    def test_includes_token_counts_in_k(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = False
        budget.summary.return_value = "Turn 1/15 | $0.00/$0.30"
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        cb.on_budget(Usage(2130, 346))
        shown = mock_show_budget.call_args.args[0]
        assert "2.1k in" in shown
        assert "0.3k out" in shown

    @patch("agent_harness.runtime_callbacks.show_budget")
    def test_no_token_counts_when_show_output_false(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = False
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False,
        )
        assert cb.on_budget is not None
        cb.on_budget(Usage(2130, 346))
        mock_show_budget.assert_not_called()


class TestGetBudgetStatus:
    def test_wired_to_budget_status_note(self) -> None:
        budget = MagicMock()
        budget.status_note.return_value = "You have 3 turn(s) remaining."
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.get_budget_status is not None
        assert cb.get_budget_status() == "You have 3 turn(s) remaining."
        budget.status_note.assert_called_once()


class TestIsBudgetExceeded:
    def test_wired_to_budget_is_exceeded(self) -> None:
        budget = MagicMock()
        budget.is_exceeded.return_value = True
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.is_budget_exceeded is not None
        assert cb.is_budget_exceeded() is True
        budget.is_exceeded.assert_called_once()


class TestOnCompletionStatus:
    @patch("agent_harness.runtime_callbacks.show_completion_status")
    def test_calls_show_completion_status_when_show_output(self, mock_show: MagicMock) -> None:
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_completion_status is not None
        cb.on_completion_status(True, "PASS: good")
        mock_show.assert_called_once_with(True, "PASS: good")

    @patch("agent_harness.runtime_callbacks.show_completion_status")
    def test_hidden_when_show_output_false(self, mock_show: MagicMock) -> None:
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False,
        )
        assert cb.on_completion_status is not None
        cb.on_completion_status(True, "PASS: good")
        mock_show.assert_not_called()

    def test_records_trace_event(self) -> None:
        tracer = MagicMock()
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=False,
        )
        assert cb.on_completion_status is not None
        cb.on_completion_status(False, "FAIL: red")
        tracer.record.assert_called_once_with("completion_status", verified=False, detail="FAIL: red")


class TestOnThrashDetected:
    @patch("agent_harness.runtime_callbacks.show_thrash_warning")
    def test_calls_show_thrash_warning_when_show_output(self, mock_show: MagicMock) -> None:
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_thrash_detected is not None
        cb.on_thrash_detected("search", "thrashing")
        mock_show.assert_called_once_with("search", "thrashing")

    @patch("agent_harness.runtime_callbacks.show_thrash_warning")
    def test_hidden_when_show_output_false(self, mock_show: MagicMock) -> None:
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False,
        )
        assert cb.on_thrash_detected is not None
        cb.on_thrash_detected("search", "thrashing")
        mock_show.assert_not_called()

    def test_records_trace_event(self) -> None:
        tracer = MagicMock()
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=False,
        )
        assert cb.on_thrash_detected is not None
        cb.on_thrash_detected("search", "thrashing")
        tracer.record.assert_called_once_with("thrash_detected", tool="search", detail="thrashing")


class TestOnPlanApproval:
    def test_none_when_no_plan_prompt_fn(self) -> None:
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_plan_approval is None

    def test_wired_to_plan_prompt_fn_and_traced(self) -> None:
        tracer = MagicMock()
        plan_prompt_fn = MagicMock(return_value=True)
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=True,
            plan_prompt_fn=plan_prompt_fn,
        )
        assert cb.on_plan_approval is not None
        result = cb.on_plan_approval(["Step one", "Step two"])
        assert result is True
        plan_prompt_fn.assert_called_once_with(["Step one", "Step two"])
        tracer.record.assert_called_with("plan_approval", steps=["Step one", "Step two"], approved=True)

    def test_records_denied_decision(self) -> None:
        tracer = MagicMock()
        plan_prompt_fn = MagicMock(return_value=False)
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=True,
            plan_prompt_fn=plan_prompt_fn,
        )
        assert cb.on_plan_approval is not None
        assert cb.on_plan_approval(["Step one"]) is False
        tracer.record.assert_called_with("plan_approval", steps=["Step one"], approved=False)


class TestOutputSink:
    """OutputSink fires alongside (not instead of) the existing console
    display — even when show_output=False, since that's exactly the case a
    non-terminal driver (e.g. an API server) uses."""

    def test_on_delta_fires_regardless_of_show_output(self) -> None:
        on_delta = MagicMock()
        sink = OutputSink(on_delta=on_delta)
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, output_sink=sink,
        )
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        on_delta.assert_called_once_with("default", "hi")

    def test_on_thinking_delta_fires_even_when_show_thinking_false(self) -> None:
        on_thinking_delta = MagicMock()
        sink = OutputSink(on_thinking_delta=on_thinking_delta)
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, show_thinking=False, output_sink=sink,
        )
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        on_thinking_delta.assert_called_once_with("default", "pondering")

    def test_on_tool_call_and_result_fire_on_success(self) -> None:
        hooks = MagicMock()
        hooks.run_before_tool.side_effect = lambda tc: tc
        hooks.run_after_tool.side_effect = lambda _tc, result: result
        permissions = MagicMock()
        permissions.check.return_value = True
        registry = {"read_file": lambda **_kw: "contents"}
        on_tool_call = MagicMock()
        on_tool_result = MagicMock()
        sink = OutputSink(on_tool_call=on_tool_call, on_tool_result=on_tool_result)
        cb = make_callbacks(
            budget=MagicMock(), hooks=hooks, permissions=permissions, tracer=MagicMock(),
            tool_registry=registry, max_output_chars=10_000, show_output=False, output_sink=sink,
        )
        assert cb.on_tool_call is not None
        tc = ToolCall(id="tc", name="read_file", arguments={})
        result = cb.on_tool_call(tc)
        on_tool_call.assert_called_once_with(tc)
        on_tool_result.assert_called_once_with(result)

    def test_on_tool_result_fires_when_denied_by_hooks(self) -> None:
        hooks = MagicMock()
        hooks.run_before_tool.return_value = None
        on_tool_result = MagicMock()
        sink = OutputSink(on_tool_result=on_tool_result)
        cb = make_callbacks(
            budget=MagicMock(), hooks=hooks, permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, output_sink=sink,
        )
        assert cb.on_tool_call is not None
        result = cb.on_tool_call(ToolCall(id="tc", name="run_command", arguments={}))
        on_tool_result.assert_called_once_with(result)
        assert isinstance(result, ToolResult)
        assert result.error == "Blocked by safety hook"

    def test_on_budget_fires_with_summary_string(self) -> None:
        budget = MagicMock()
        budget.record.return_value = False
        budget.summary.return_value = "Turn 1/15 | $0.00/$0.30"
        on_budget = MagicMock()
        sink = OutputSink(on_budget=on_budget)
        cb = make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, output_sink=sink,
        )
        assert cb.on_budget is not None
        cb.on_budget(Usage(10, 5))
        on_budget.assert_called_once()
        assert "Turn 1/15" in on_budget.call_args.args[0]

    def test_on_completion_status_fires(self) -> None:
        on_completion_status = MagicMock()
        sink = OutputSink(on_completion_status=on_completion_status)
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, output_sink=sink,
        )
        assert cb.on_completion_status is not None
        cb.on_completion_status(True, "PASS: good")
        on_completion_status.assert_called_once_with(True, "PASS: good")

    def test_on_thrash_detected_fires(self) -> None:
        on_thrash_detected = MagicMock()
        sink = OutputSink(on_thrash_detected=on_thrash_detected)
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, output_sink=sink,
        )
        assert cb.on_thrash_detected is not None
        cb.on_thrash_detected("search", "thrashing")
        on_thrash_detected.assert_called_once_with("search", "thrashing")

    def test_none_output_sink_is_inert_cli_path_unaffected(self) -> None:
        cb = make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=False, output_sink=None,
        )
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")  # must not raise
