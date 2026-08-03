"""A simple reference code grader — checks for a substring in the response."""

from __future__ import annotations

from eval.types import GradeResult


def contains(response_text: str, output_file_content: str | None, expected: str) -> GradeResult:
    """Pass if `expected` appears in the response text, case-insensitive.

    Args:
        response_text: The agent's final chat response.
        output_file_content: Unused — this grader only looks at chat text.
        expected: Substring to look for.

    Returns:
        GradeResult with pass/fail and the searched-for string in detail.
    """
    passed = expected.lower() in response_text.lower()
    return GradeResult(passed=passed, score=1.0 if passed else 0.0, detail={"expected": expected})
