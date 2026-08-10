"""Tests for agent_harness.runtime."""

from unittest.mock import MagicMock, patch

from agent_harness.budget import Budget
from agent_harness.config import load as load_config
from agent_harness.permissions import PermissionDecision
from agent_harness.runtime import _make_callbacks, prepare_runtime
from agent_harness.types import LoopCallbacks, Message, Response, Usage

VALID_AGENT = "tests/data/valid_agent"


def _callbacks(*, stream: bool, show_thinking: bool, show_output: bool = True) -> LoopCallbacks:
    return _make_callbacks(
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
    @patch("agent_harness.runtime.show_delta")
    def test_shows_delta_when_show_output(self, mock_show_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        mock_show_delta.assert_called_once_with("hi")

    @patch("agent_harness.runtime.show_delta")
    def test_hidden_when_show_output_false(self, mock_show_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=False)
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        mock_show_delta.assert_not_called()


class TestOnThinkingDelta:
    @patch("agent_harness.runtime.show_thinking_delta")
    def test_shows_when_show_thinking_true(self, mock_show_thinking_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=True, show_output=True)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_called_once_with("pondering")

    @patch("agent_harness.runtime.show_thinking_delta")
    def test_hidden_when_show_thinking_false(self, mock_show_thinking_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_not_called()

    @patch("agent_harness.runtime.show_thinking_delta")
    def test_hidden_when_show_output_false_even_if_show_thinking_true(
        self, mock_show_thinking_delta: MagicMock,
    ) -> None:
        cb = _callbacks(stream=True, show_thinking=True, show_output=False)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_not_called()


class TestOnResponse:
    @patch("agent_harness.runtime.show_response")
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

    @patch("agent_harness.runtime.show_response")
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
    @patch("agent_harness.runtime.show_budget")
    def test_shows_plain_summary_when_not_exceeded(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = False
        budget.summary.return_value = "Turn 3/15 | $0.05/$0.30"
        cb = _make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        exceeded = cb.on_budget(Usage(10, 5))
        assert exceeded is False
        mock_show_budget.assert_called_once_with("Turn 3/15 | $0.05/$0.30")

    @patch("agent_harness.runtime.show_budget")
    def test_flags_stop_when_exceeded(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = True
        budget.summary.return_value = "Turn 15/15 | $0.2372/$0.30"
        cb = _make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        exceeded = cb.on_budget(Usage(10, 5))
        assert exceeded is True
        shown = mock_show_budget.call_args.args[0]
        assert "Turn 15/15 | $0.2372/$0.30" in shown
        assert "stopping" in shown.lower()


class TestGetBudgetStatus:
    def test_wired_to_budget_status_note(self) -> None:
        budget = MagicMock()
        budget.status_note.return_value = "You have 3 turn(s) remaining."
        cb = _make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.get_budget_status is not None
        assert cb.get_budget_status() == "You have 3 turn(s) remaining."
        budget.status_note.assert_called_once()


class TestOnPlanApproval:
    def test_none_when_no_plan_prompt_fn(self) -> None:
        cb = _make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_plan_approval is None

    def test_wired_to_plan_prompt_fn_and_traced(self) -> None:
        tracer = MagicMock()
        plan_prompt_fn = MagicMock(return_value=True)
        cb = _make_callbacks(
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
        cb = _make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=True,
            plan_prompt_fn=plan_prompt_fn,
        )
        assert cb.on_plan_approval is not None
        assert cb.on_plan_approval(["Step one"]) is False
        tracer.record.assert_called_with("plan_approval", steps=["Step one"], approved=False)


class TestPreparedRuntimeBudget:
    def test_exposes_budget_instance(self) -> None:
        config = load_config(VALID_AGENT)
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
            show_output=False,
            trace_enabled=False,
        )
        assert isinstance(runtime.budget, Budget)
        assert runtime.budget.turns == 0
        assert runtime.budget.total_cost == 0.0
