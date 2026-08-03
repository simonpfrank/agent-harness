"""Column-matcher grader — reuses scripts.score_run.score() almost verbatim.

Imports the `scripts.score_run` module (not its `score` function directly) so
that auto-discovery in `eval.graders.discover_code_graders` — which registers
the first public, type-annotated function it finds in a file — doesn't
mistake the imported `score()` for this file's grader.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.types import GradeResult
from scripts import score_run


def column_match(response_text: str, output_file_content: str | None, expected: str) -> GradeResult:
    """Compare a column-matcher output file against ground-truth matches.

    Args:
        response_text: Unused — the column-matcher's real output is a file.
        output_file_content: JSON content of the agent's output file.
        expected: Path to the ground-truth `expected_matches.json` file.

    Returns:
        GradeResult — passes only if every expected match was found with
        zero false positives. Detail carries the itemized misses/incorrect
        claims from `ScoreResult`.
    """
    output = json.loads(output_file_content) if output_file_content else {}
    expected_data = json.loads(Path(expected).read_text())
    result = score_run.score(output, expected_data)
    passed = result.false_positives == 0 and result.correct == result.total_expected
    return GradeResult(
        passed=passed,
        score=(result.correct / result.total_expected) if result.total_expected else 0.0,
        detail={
            "correct": result.correct,
            "total_expected": result.total_expected,
            "false_positives": result.false_positives,
            "missed_expected": result.missed_expected,
            "incorrect_claims": result.incorrect_claims,
        },
    )
