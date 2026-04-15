"""Score a column-matcher output against ground truth.

Usage:
    python -m scripts.score_run <output.json> <expected_matches.json>

Reusable library: `score(output_dict, expected_dict) -> ScoreResult`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScoreResult:
    """Summary of how an agent output compares to ground truth."""

    correct: int
    total_expected: int
    false_positives: int
    missed_expected: list[tuple[str, str]]
    incorrect_claims: list[tuple[str, str]]


def score(output: dict, expected: dict) -> ScoreResult:
    """Compare agent output matches against ground-truth pairs.

    Args:
        output: Agent output JSON with a "matches" list of
            {input_column, reference_column} dicts.
        expected: Ground-truth JSON with a "matches" list of
            {input, reference} dicts.

    Returns:
        ScoreResult with correct count, false positives, and miss details.
    """
    expected_pairs = {(m["input"], m["reference"]) for m in expected["matches"]}
    claimed_pairs = {
        (m["input_column"], m["reference_column"])
        for m in output.get("matches", [])
    }

    correct_pairs = expected_pairs & claimed_pairs
    incorrect_pairs = claimed_pairs - expected_pairs
    missed_pairs = expected_pairs - claimed_pairs

    return ScoreResult(
        correct=len(correct_pairs),
        total_expected=len(expected_pairs),
        false_positives=len(incorrect_pairs),
        missed_expected=sorted(missed_pairs),
        incorrect_claims=sorted(incorrect_pairs),
    )


def main(argv: list[str]) -> int:
    """CLI entry point. Prints a human-readable score summary."""
    if len(argv) != 3:
        print("Usage: score_run.py <output.json> <expected.json>", file=sys.stderr)
        return 1
    output = json.loads(Path(argv[1]).read_text())
    expected = json.loads(Path(argv[2]).read_text())
    result = score(output, expected)
    print(f"Correct: {result.correct}/{result.total_expected}")
    print(f"False positives: {result.false_positives}")
    if result.missed_expected:
        print("Missed:")
        for inp, ref in result.missed_expected:
            print(f"  - {inp!r} -> {ref!r}")
    if result.incorrect_claims:
        print("Incorrect claims:")
        for inp, ref in result.incorrect_claims:
            print(f"  - {inp!r} -> {ref!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
