"""Aggregate run results into a ranked, gate-aware leaderboard."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from itertools import groupby

from rich.console import Console
from rich.table import Table

from eval.types import RunResult

console = Console()


@dataclass
class CellSummary:
    """Aggregated results for one cell across all its runs.

    Attributes:
        cell_id: Which cell this summarizes.
        gate_pass_rate: Fraction of runs where every gate grader passed.
        stdev: Stdev of the per-run gate score, across runs (determinism).
        signal_score: Mean signal-grader score, only from gate-passing runs.
            None if no signal graders ran.
        mean_cost: Mean estimated USD cost per run.
        mean_turns: Mean LLM turns per run.
        disqualified: Whether gate_pass_rate fell below the required threshold.
    """

    cell_id: str
    gate_pass_rate: float
    stdev: float
    signal_score: float | None
    mean_cost: float
    mean_turns: float
    disqualified: bool


def _gate_score(result: RunResult) -> float:
    """Mean score across a run's gate graders, falling back to gate_passed."""
    gate_scores = [float(g["score"]) for g in result.grades if g["kind"] == "gate"]
    if gate_scores:
        return sum(gate_scores) / len(gate_scores)
    return 1.0 if result.gate_passed else 0.0


def summarize(results: list[RunResult], gate_threshold: float = 1.0) -> list[CellSummary]:
    """Group run results by cell and aggregate into summaries.

    Args:
        results: Run results, any order, any mix of cells.
        gate_threshold: Minimum gate_pass_rate required to not be disqualified.

    Returns:
        One CellSummary per distinct cell_id.
    """
    summaries: list[CellSummary] = []
    sorted_results = sorted(results, key=lambda r: r.cell_id)
    for cell_id, group_iter in groupby(sorted_results, key=lambda r: r.cell_id):
        group = list(group_iter)
        gate_scores = [_gate_score(r) for r in group]
        signal_scores = [r.signal_score for r in group if r.signal_score is not None]
        gate_pass_rate = sum(1 for r in group if r.gate_passed) / len(group)
        summaries.append(CellSummary(
            cell_id=cell_id,
            gate_pass_rate=gate_pass_rate,
            stdev=statistics.stdev(gate_scores) if len(gate_scores) > 1 else 0.0,
            signal_score=(sum(signal_scores) / len(signal_scores)) if signal_scores else None,
            mean_cost=sum(r.cost for r in group) / len(group),
            mean_turns=sum(r.turns for r in group) / len(group),
            disqualified=gate_pass_rate < gate_threshold,
        ))
    return summaries


def rank(summaries: list[CellSummary], order: list[tuple[str, str]]) -> list[CellSummary]:
    """Sort summaries lexicographically, with disqualified cells always last.

    Args:
        summaries: Cell summaries to sort.
        order: Ordered list of `(field, "asc" | "desc")` tie-break criteria.

    Returns:
        Sorted summaries — never blends metrics into one score.
    """
    def sort_key(summary: CellSummary) -> tuple[object, ...]:
        key: tuple[object, ...] = (summary.disqualified,)
        for field, direction in order:
            value = getattr(summary, field)
            if value is None:
                value = float("-inf") if direction == "desc" else float("inf")
            key += (-value if direction == "desc" else value,)
        return key

    return sorted(summaries, key=sort_key)


def render_table(summaries: list[CellSummary]) -> None:
    """Render a leaderboard to the console.

    Args:
        summaries: Cell summaries, ideally pre-sorted via `rank()`.
    """
    table = Table(title="Eval Leaderboard")
    table.add_column("Cell")
    table.add_column("Gate", justify="right")
    table.add_column("Stdev", justify="right")
    table.add_column("Signal", justify="right")
    table.add_column("Cost/run", justify="right")
    table.add_column("Turns", justify="right")
    for s in summaries:
        label = s.cell_id + ("  DISQUALIFIED" if s.disqualified else "")
        signal_str = f"{s.signal_score:.2f}" if s.signal_score is not None else "-"
        table.add_row(
            label, f"{s.gate_pass_rate:.2f}", f"{s.stdev:.2f}", signal_str,
            f"${s.mean_cost:.4f}", f"{s.mean_turns:.1f}",
        )
    console.print(table)


def render_markdown(summaries: list[CellSummary]) -> str:
    """Render a leaderboard as a markdown table for durable logs.

    Args:
        summaries: Cell summaries, ideally pre-sorted via `rank()`.

    Returns:
        Markdown table string.
    """
    lines = ["| Cell | Gate | Stdev | Signal | Cost/run | Turns |", "|---|---|---|---|---|---|"]
    for s in summaries:
        label = s.cell_id + (" ⚠️ DISQUALIFIED" if s.disqualified else "")
        signal_str = f"{s.signal_score:.2f}" if s.signal_score is not None else "-"
        lines.append(
            f"| {label} | {s.gate_pass_rate:.2f} | {s.stdev:.2f} | {signal_str} "
            f"| ${s.mean_cost:.4f} | {s.mean_turns:.1f} |",
        )
    return "\n".join(lines)
