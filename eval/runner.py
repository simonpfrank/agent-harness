"""Runs test cases against agent_harness agents, applying cell overrides and grading results."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_harness import config as config_loader
from agent_harness.runtime import deny_permission, prepare_runtime
from agent_harness.types import AgentConfig
from eval.graders import registry as code_grader_registry
from eval.graders.model import grade_with_model
from eval.types import Case, Cell, GraderSpec, RunResult


def _clear_memory(agent_dir: str) -> None:
    """Delete all `.md` files in the agent's memory folder.

    Ensures repeated runs of the same cell are independent trials — an agent
    with `save_memory`/`recall_memory` tools would otherwise carry state
    across repeats.

    Args:
        agent_dir: Agent directory whose `memory/` subfolder gets cleared.
    """
    memory_dir = Path(agent_dir) / "memory"
    if memory_dir.is_dir():
        for md in memory_dir.glob("*.md"):
            md.unlink()


def _apply_cell_overrides(config: AgentConfig, cell: Cell) -> None:
    """Apply a cell's config overrides in place.

    Args:
        config: Loaded agent configuration, mutated in place.
        cell: Cell whose overrides should be applied.
    """
    if cell.instructions_override:
        config.instructions = Path(cell.instructions_override).read_text()
    if cell.provider:
        config.provider = cell.provider
    if cell.model:
        config.model = cell.model
    if cell.temperature is not None:
        config.provider_kwargs["temperature"] = cell.temperature


def _run_grader(spec: GraderSpec, response_text: str, output_file_content: str | None) -> dict[str, Any]:
    """Run one grader against a result and return its dict representation.

    Args:
        spec: Which grader to run and with what args.
        response_text: The agent's final chat response.
        output_file_content: Contents of the case's output file, if any.

    Returns:
        Flat dict combining the grader's identity and its GradeResult fields.
    """
    if spec.name == "model":
        result = grade_with_model(response_text, output_file_content, **spec.args)
    else:
        grader_fn = code_grader_registry[spec.name]
        result = grader_fn(response_text, output_file_content, **spec.args)
    return {
        "grader": spec.name,
        "kind": spec.kind,
        "passed": result.passed,
        "score": result.score,
        "detail": result.detail,
    }


def run_case_once(case: Case, cell: Cell, run_index: int) -> RunResult:
    """Run one test case once, under one cell's configuration, and grade it.

    Args:
        case: The test case to run.
        cell: The configuration variant to run it under.
        run_index: 1-based repeat index, used to resolve `case.output_file`.

    Returns:
        The graded result of this single run.
    """
    config = config_loader.load(cell.agent)
    _apply_cell_overrides(config, cell)
    _clear_memory(config.agent_dir)

    runtime = prepare_runtime(
        config,
        permission_prompt_fn=deny_permission,
        show_output=False,
        trace_enabled=False,
    )
    prompt = case.prompt.format(cell_id=cell.id, run_index=run_index)
    messages = runtime.init_messages()
    response_text = runtime.run_messages(messages, prompt=prompt)

    output_file_content = None
    if case.output_file:
        output_path = Path(case.output_file.format(cell_id=cell.id, run_index=run_index))
        if output_path.exists():
            output_file_content = output_path.read_text()

    grades = [_run_grader(spec, response_text, output_file_content) for spec in case.graders]
    gate_passed = all(g["passed"] for g in grades if g["kind"] == "gate")
    signal_scores = [g["score"] for g in grades if g["kind"] == "signal"]
    signal_score = (sum(signal_scores) / len(signal_scores)) if signal_scores and gate_passed else None

    return RunResult(
        case_id=case.id,
        cell_id=cell.id,
        run_index=run_index,
        response_text=response_text,
        output_file_content=output_file_content,
        turns=runtime.budget.turns,
        cost=runtime.budget.total_cost,
        grades=grades,
        gate_passed=gate_passed,
        signal_score=signal_score,
        timestamp=datetime.now(tz=UTC).isoformat(),
    )


def run_repeated(case: Case, cell: Cell, n: int) -> list[RunResult]:
    """Run a test case `n` times under one cell.

    Args:
        case: The test case to run.
        cell: The configuration variant to run it under.
        n: Number of repeats.

    Returns:
        One RunResult per repeat, in order.
    """
    return [run_case_once(case, cell, i) for i in range(1, n + 1)]
