"""Tests for eval.cli."""

from unittest.mock import MagicMock, patch

from eval.cli import parse_args, resolve_rank_order


class TestParseArgs:
    def test_run_command(self) -> None:
        args = parse_args(["run", "eval/cases/hello", "--cells", "eval/cells/hello.yaml", "--out", "out.jsonl"])
        assert args.command == "run"
        assert args.cases_dir == "eval/cases/hello"
        assert args.cells == "eval/cells/hello.yaml"
        assert args.out == "out.jsonl"
        assert args.repeats == 1

    def test_run_command_with_repeats(self) -> None:
        args = parse_args([
            "run", "eval/cases/hello", "--cells", "eval/cells/hello.yaml",
            "--out", "out.jsonl", "--repeats", "5",
        ])
        assert args.repeats == 5

    def test_report_command(self) -> None:
        args = parse_args(["report", "out.jsonl"])
        assert args.command == "report"
        assert args.results == "out.jsonl"
        assert args.rank is None

    def test_report_command_with_rank(self) -> None:
        args = parse_args(["report", "out.jsonl", "--rank", "gate,stdev,signal,cost"])
        assert args.rank == "gate,stdev,signal,cost"


class TestResolveRankOrder:
    def test_default_order_when_none(self) -> None:
        order = resolve_rank_order(None)
        assert order == [
            ("gate_pass_rate", "desc"), ("stdev", "asc"),
            ("signal_score", "desc"), ("mean_cost", "asc"),
        ]

    def test_custom_order(self) -> None:
        order = resolve_rank_order("cost,gate")
        assert order == [("mean_cost", "asc"), ("gate_pass_rate", "desc")]

    def test_unknown_alias_raises(self) -> None:
        try:
            resolve_rank_order("not-a-real-metric")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "not-a-real-metric" in str(exc)


class TestCmdRun:
    @patch("eval.cli.append_result")
    @patch("eval.cli.run_repeated")
    @patch("eval.cli.load_cells")
    @patch("eval.cli.load_cases")
    def test_runs_every_case_against_every_cell(
        self, mock_load_cases: MagicMock, mock_load_cells: MagicMock,
        mock_run_repeated: MagicMock, mock_append_result: MagicMock,
    ) -> None:
        from eval.cli import main
        from eval.types import Case, Cell, RunResult

        mock_load_cases.return_value = [Case(id="c1", agent="a", prompt="p", graders=[])]
        mock_load_cells.return_value = [Cell(id="cell1", agent="a")]
        mock_run_repeated.return_value = [
            RunResult("c1", "cell1", 1, "x", None, 1, 0.01, [], True, None, "t"),
        ]

        main(["run", "eval/cases/x", "--cells", "eval/cells/x.yaml", "--out", "out.jsonl", "--repeats", "2"])

        mock_run_repeated.assert_called_once()
        assert mock_run_repeated.call_args.args[2] == 2
        mock_append_result.assert_called_once()


class TestCmdReport:
    @patch("eval.cli.render_table")
    @patch("eval.cli.load_results")
    def test_loads_and_renders(self, mock_load_results: MagicMock, mock_render_table: MagicMock) -> None:
        from eval.cli import main
        from eval.types import RunResult

        mock_load_results.return_value = [
            RunResult("c1", "cell1", 1, "x", None, 1, 0.01, [], True, None, "t"),
        ]
        main(["report", "out.jsonl"])
        mock_render_table.assert_called_once()
