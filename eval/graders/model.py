"""LLM-as-judge grader — a single flexible function, not a per-rubric registry."""

from __future__ import annotations

from agent_harness.providers import registry as provider_registry
from agent_harness.types import Message
from eval.types import GradeResult

_JUDGE_PROMPT = """\
Rubric: {rubric}

Response to grade:
{response_text}

Reply with PASS or FAIL on the first line, then a one-line reason."""


def grade_with_model(
    response_text: str,
    output_file_content: str | None,
    rubric: str,
    judge_provider: str = "anthropic",
    judge_model: str = "claude-haiku-4-5-20251001",
) -> GradeResult:
    """Grade a response against a rubric using an LLM judge.

    Args:
        response_text: The agent's final chat response.
        output_file_content: Unused — the judge only sees the chat response.
        rubric: Free-text grading criteria.
        judge_provider: Provider to send the grading call to.
        judge_model: Model to use for grading.

    Returns:
        GradeResult — passed if the judge's reply starts with PASS. Detail
        carries the full judge response for inspection.
    """
    chat_fn = provider_registry[judge_provider]
    prompt = _JUDGE_PROMPT.format(rubric=rubric, response_text=response_text)
    result = chat_fn([Message(role="user", content=prompt)], tools=[], model=judge_model)
    judge_response = result.message.content or ""
    passed = judge_response.strip().upper().startswith("PASS")
    return GradeResult(passed=passed, score=1.0 if passed else 0.0, detail={"judge_response": judge_response})
