"""Shared dataclasses for the evaluation framework.

No internal imports. This is the dependency root for the `eval` package,
mirroring `agent_harness.types`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraderSpec:
    """A grader attached to a test case.

    Attributes:
        name: Grader identifier — a code grader's function name, or "model".
        kind: "gate" (disqualifying, pass/fail) or "signal" (quality score,
            only ranked among cells that already cleared every gate).
        args: Grader-specific keyword arguments, passed through as-is.
    """

    name: str
    kind: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Case:
    """A single evaluation test case.

    Attributes:
        id: Unique case identifier.
        agent: Path to the agent directory to run.
        prompt: The task prompt to send. May contain `{cell_id}`/`{run_index}`
            placeholders, resolved the same way as `output_file` — needed
            when the prompt must tell the agent where to write its output.
        graders: Graders to run against the result.
        output_file: Optional path template for file-based grading. May
            contain `{cell_id}`/`{run_index}` placeholders.
    """

    id: str
    agent: str
    prompt: str
    graders: list[GraderSpec]
    output_file: str | None = None


@dataclass
class Cell:
    """A configuration variant to run the same test cases against.

    Attributes:
        id: Human-readable cell label, e.g. "instructions_v3/haiku/t0.0".
        agent: Base agent directory (config.yaml/instructions.md loaded from here).
        instructions_override: Optional path to alternate instructions.md content.
        provider: Optional provider override.
        model: Optional model override.
        temperature: Optional temperature override.
    """

    id: str
    agent: str
    instructions_override: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None


@dataclass
class GradeResult:
    """The result of running one grader against one run.

    Attributes:
        passed: Whether the grader considers this a pass.
        score: A 0-1 quality/correctness score.
        detail: Structured diagnostic detail (e.g. missed/incorrect pairs).
    """

    passed: bool
    score: float
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """The full result of running one test case, in one cell, once.

    Attributes:
        case_id: Which test case this is.
        cell_id: Which cell this ran under.
        run_index: 1-based repeat index within the cell.
        response_text: The agent's final chat response text.
        output_file_content: Contents of the case's output_file, if configured.
        turns: LLM turns used.
        cost: Estimated USD cost.
        grades: One dict per grader, `{"grader", "kind", "passed", "score", "detail"}`.
        gate_passed: Whether every gate grader passed.
        signal_score: Mean signal-grader score, only set when gate_passed.
        timestamp: ISO-8601 timestamp of the run.
    """

    case_id: str
    cell_id: str
    run_index: int
    response_text: str
    output_file_content: str | None
    turns: int
    cost: float
    grades: list[dict[str, Any]]
    gate_passed: bool
    signal_score: float | None
    timestamp: str
