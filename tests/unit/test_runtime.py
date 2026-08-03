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
