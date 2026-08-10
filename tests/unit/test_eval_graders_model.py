"""Tests for eval.graders.model."""

from unittest.mock import MagicMock, patch

from agent_harness.types import Message, Response, Usage
from eval.graders.model import grade_with_model


def _response(text: str) -> Response:
    return Response(
        message=Message(role="assistant", content=text),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


class TestGradeWithModel:
    @patch("eval.graders.model.provider_registry")
    def test_pass_verdict(self, mock_registry: MagicMock) -> None:
        chat_fn = MagicMock(return_value=_response("PASS - clear and correct"))
        mock_registry.__getitem__.return_value = chat_fn

        result = grade_with_model(
            "The answer is 4.", None, rubric="Is the answer correct?"
        )
        assert result.passed is True
        assert result.score == 1.0
        assert "PASS" in result.detail["judge_response"]

    @patch("eval.graders.model.provider_registry")
    def test_fail_verdict(self, mock_registry: MagicMock) -> None:
        chat_fn = MagicMock(return_value=_response("FAIL - answer is wrong"))
        mock_registry.__getitem__.return_value = chat_fn

        result = grade_with_model(
            "The answer is 5.", None, rubric="Is the answer correct?"
        )
        assert result.passed is False
        assert result.score == 0.0

    @patch("eval.graders.model.provider_registry")
    def test_uses_configured_judge_provider_and_model(
        self, mock_registry: MagicMock
    ) -> None:
        chat_fn = MagicMock(return_value=_response("PASS"))
        mock_registry.__getitem__.return_value = chat_fn

        grade_with_model(
            "hi",
            None,
            rubric="rubric text",
            judge_provider="openai",
            judge_model="gpt-5-mini",
        )
        mock_registry.__getitem__.assert_called_once_with("openai")
        call_kwargs = chat_fn.call_args.kwargs
        assert call_kwargs["model"] == "gpt-5-mini"

    @patch("eval.graders.model.provider_registry")
    def test_rubric_and_response_included_in_prompt(
        self, mock_registry: MagicMock
    ) -> None:
        chat_fn = MagicMock(return_value=_response("PASS"))
        mock_registry.__getitem__.return_value = chat_fn

        grade_with_model("the response text", None, rubric="the rubric text")
        messages = chat_fn.call_args.args[0]
        assert "the rubric text" in messages[0].content
        assert "the response text" in messages[0].content
