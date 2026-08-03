"""Tests for eval.report."""

from eval.report import CellSummary, rank, render_markdown, render_table, summarize
from eval.types import RunResult


def _run(
    cell_id: str,
    run_index: int,
    gate_score: float,
    gate_passed: bool,
    signal_score: float | None,
    cost: float = 0.01,
    turns: int = 3,
) -> RunResult:
    return RunResult(
        case_id="c1",
        cell_id=cell_id,
        run_index=run_index,
        response_text="x",
        output_file_content=None,
        turns=turns,
        cost=cost,
        grades=[{"grader": "contains", "kind": "gate", "passed": gate_passed, "score": gate_score, "detail": {}}],
        gate_passed=gate_passed,
        signal_score=signal_score,
        timestamp="2026-08-03T12:00:00+00:00",
    )


class TestSummarize:
    def test_gate_pass_rate(self) -> None:
        results = [
            _run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None),
            _run("cell-a", 2, gate_score=0.0, gate_passed=False, signal_score=None),
        ]
        summaries = summarize(results)
        assert len(summaries) == 1
        assert summaries[0].gate_pass_rate == 0.5

    def test_stdev_of_gate_score(self) -> None:
        results = [
            _run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None),
            _run("cell-a", 2, gate_score=0.5, gate_passed=True, signal_score=None),
        ]
        summaries = summarize(results)
        assert summaries[0].stdev > 0.0

    def test_signal_score_only_from_non_none_runs(self) -> None:
        results = [
            _run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=0.9),
            _run("cell-a", 2, gate_score=0.0, gate_passed=False, signal_score=None),
        ]
        summaries = summarize(results)
        assert summaries[0].signal_score == 0.9

    def test_signal_score_none_when_no_signals_recorded(self) -> None:
        results = [_run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None)]
        summaries = summarize(results)
        assert summaries[0].signal_score is None

    def test_disqualified_below_threshold(self) -> None:
        results = [
            _run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None),
            _run("cell-a", 2, gate_score=0.0, gate_passed=False, signal_score=None),
        ]
        summaries = summarize(results, gate_threshold=1.0)
        assert summaries[0].disqualified is True

    def test_not_disqualified_at_threshold(self) -> None:
        results = [_run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None)]
        summaries = summarize(results, gate_threshold=1.0)
        assert summaries[0].disqualified is False

    def test_mean_cost_and_turns(self) -> None:
        results = [
            _run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None, cost=0.01, turns=2),
            _run("cell-a", 2, gate_score=1.0, gate_passed=True, signal_score=None, cost=0.03, turns=4),
        ]
        summaries = summarize(results)
        assert summaries[0].mean_cost == 0.02
        assert summaries[0].mean_turns == 3.0

    def test_groups_multiple_cells_separately(self) -> None:
        results = [
            _run("cell-a", 1, gate_score=1.0, gate_passed=True, signal_score=None),
            _run("cell-b", 1, gate_score=1.0, gate_passed=True, signal_score=None),
        ]
        summaries = summarize(results)
        assert {s.cell_id for s in summaries} == {"cell-a", "cell-b"}


class TestRank:
    def test_lexicographic_order_by_signal_score_desc(self) -> None:
        summaries = [
            CellSummary("low", 1.0, 0.0, 0.5, 0.01, 3.0, disqualified=False),
            CellSummary("high", 1.0, 0.0, 0.9, 0.01, 3.0, disqualified=False),
        ]
        ranked = rank(summaries, [("signal_score", "desc")])
        assert [s.cell_id for s in ranked] == ["high", "low"]

    def test_disqualified_always_sorts_last(self) -> None:
        summaries = [
            CellSummary("disqualified-but-great", 0.5, 0.0, 0.99, 0.01, 3.0, disqualified=True),
            CellSummary("qualified-ok", 1.0, 0.0, 0.5, 0.01, 3.0, disqualified=False),
        ]
        ranked = rank(summaries, [("signal_score", "desc")])
        assert ranked[0].cell_id == "qualified-ok"
        assert ranked[1].cell_id == "disqualified-but-great"

    def test_tie_break_on_second_metric(self) -> None:
        summaries = [
            CellSummary("cheap", 1.0, 0.0, 0.8, 0.01, 3.0, disqualified=False),
            CellSummary("expensive", 1.0, 0.0, 0.8, 0.05, 3.0, disqualified=False),
        ]
        ranked = rank(summaries, [("signal_score", "desc"), ("mean_cost", "asc")])
        assert [s.cell_id for s in ranked] == ["cheap", "expensive"]


class TestRenderMarkdown:
    def test_contains_cell_ids(self) -> None:
        summaries = [CellSummary("baseline", 1.0, 0.0, 0.8, 0.01, 3.0, disqualified=False)]
        markdown = render_markdown(summaries)
        assert "baseline" in markdown


class TestRenderTable:
    def test_no_crash(self) -> None:
        summaries = [CellSummary("baseline", 1.0, 0.0, 0.8, 0.01, 3.0, disqualified=False)]
        render_table(summaries)
