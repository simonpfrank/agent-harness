"""Tests for eval.runner."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from eval.runner import _clear_memory, run_case_once, run_repeated
from eval.types import Case, Cell, GraderSpec

VALID_AGENT = "tests/data/valid_agent"


def _mock_runtime(response_text: str = "4", turns: int = 1, cost: float = 0.001) -> MagicMock:
    runtime = MagicMock()
    runtime.init_messages.return_value = []
    runtime.run_messages.return_value = response_text
    runtime.budget.turns = turns
    runtime.budget.total_cost = cost
    return runtime


class TestClearMemory:
    def test_deletes_md_files(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "note.md").write_text("some memory")
        _clear_memory(str(tmp_path))
        assert not (memory_dir / "note.md").exists()

    def test_no_memory_dir_no_error(self, tmp_path: Path) -> None:
        _clear_memory(str(tmp_path))  # should not raise


class TestRunCaseOnce:
    @patch("eval.runner.prepare_runtime")
    def test_basic_run_with_contains_gate(self, mock_prepare_runtime: MagicMock) -> None:
        mock_prepare_runtime.return_value = _mock_runtime(response_text="The answer is 4.")
        case = Case(
            id="two-plus-two", agent=VALID_AGENT, prompt="What is 2+2?",
            graders=[GraderSpec(name="contains", kind="gate", args={"expected": "4"})],
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        result = run_case_once(case, cell, run_index=1)

        assert result.case_id == "two-plus-two"
        assert result.cell_id == "baseline"
        assert result.run_index == 1
        assert result.response_text == "The answer is 4."
        assert result.turns == 1
        assert result.cost == 0.001
        assert result.gate_passed is True
        assert result.grades[0]["grader"] == "contains"

    @patch("eval.runner.prepare_runtime")
    def test_gate_failure_sets_gate_passed_false(self, mock_prepare_runtime: MagicMock) -> None:
        mock_prepare_runtime.return_value = _mock_runtime(response_text="The answer is 5.")
        case = Case(
            id="two-plus-two", agent=VALID_AGENT, prompt="What is 2+2?",
            graders=[GraderSpec(name="contains", kind="gate", args={"expected": "4"})],
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        result = run_case_once(case, cell, run_index=1)
        assert result.gate_passed is False

    @patch("eval.runner.grade_with_model")
    @patch("eval.runner.prepare_runtime")
    def test_signal_score_none_when_gate_fails(
        self, mock_prepare_runtime: MagicMock, mock_grade_with_model: MagicMock,
    ) -> None:
        from eval.types import GradeResult

        mock_prepare_runtime.return_value = _mock_runtime(response_text="wrong")
        mock_grade_with_model.return_value = GradeResult(passed=True, score=0.9, detail={})
        case = Case(
            id="c1", agent=VALID_AGENT, prompt="p",
            graders=[
                GraderSpec(name="contains", kind="gate", args={"expected": "4"}),
                GraderSpec(name="model", kind="signal", args={"rubric": "quality"}),
            ],
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        result = run_case_once(case, cell, run_index=1)
        assert result.gate_passed is False
        assert result.signal_score is None

    @patch("eval.runner.grade_with_model")
    @patch("eval.runner.prepare_runtime")
    def test_signal_score_averaged_when_gate_passes(
        self, mock_prepare_runtime: MagicMock, mock_grade_with_model: MagicMock,
    ) -> None:
        from eval.types import GradeResult

        mock_prepare_runtime.return_value = _mock_runtime(response_text="The answer is 4.")
        mock_grade_with_model.return_value = GradeResult(passed=True, score=0.8, detail={})
        case = Case(
            id="c1", agent=VALID_AGENT, prompt="p",
            graders=[
                GraderSpec(name="contains", kind="gate", args={"expected": "4"}),
                GraderSpec(name="model", kind="signal", args={"rubric": "quality"}),
            ],
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        result = run_case_once(case, cell, run_index=1)
        assert result.gate_passed is True
        assert result.signal_score == 0.8
        mock_grade_with_model.assert_called_once()

    @patch("eval.runner.prepare_runtime")
    def test_applies_instructions_override(self, mock_prepare_runtime: MagicMock) -> None:
        mock_prepare_runtime.return_value = _mock_runtime()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("Custom variant instructions.")
            variant_path = f.name

        case = Case(id="c1", agent=VALID_AGENT, prompt="p", graders=[])
        cell = Cell(id="variant-a", agent=VALID_AGENT, instructions_override=variant_path)

        run_case_once(case, cell, run_index=1)
        passed_config = mock_prepare_runtime.call_args.args[0]
        assert passed_config.instructions == "Custom variant instructions."
        Path(variant_path).unlink()

    @patch("eval.runner.prepare_runtime")
    def test_applies_provider_model_temperature_overrides(self, mock_prepare_runtime: MagicMock) -> None:
        mock_prepare_runtime.return_value = _mock_runtime()
        case = Case(id="c1", agent=VALID_AGENT, prompt="p", graders=[])
        cell = Cell(
            id="variant-b", agent=VALID_AGENT,
            provider="openai", model="gpt-4o-mini", temperature=0.2,
        )

        run_case_once(case, cell, run_index=1)
        passed_config = mock_prepare_runtime.call_args.args[0]
        assert passed_config.provider == "openai"
        assert passed_config.model == "gpt-4o-mini"
        assert passed_config.provider_kwargs["temperature"] == 0.2

    @patch("eval.runner.prepare_runtime")
    def test_prompt_placeholders_resolved_same_as_output_file(
        self, mock_prepare_runtime: MagicMock, tmp_path: Path,
    ) -> None:
        mock_runtime = _mock_runtime()
        mock_prepare_runtime.return_value = mock_runtime
        case = Case(
            id="c1", agent=VALID_AGENT,
            prompt=f"Write your answer to {tmp_path}/{{cell_id}}_r{{run_index}}.json",
            graders=[],
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        run_case_once(case, cell, run_index=2)
        sent_prompt = mock_runtime.run_messages.call_args.kwargs["prompt"]
        assert sent_prompt == f"Write your answer to {tmp_path}/baseline_r2.json"

    @patch("eval.runner.prepare_runtime")
    def test_reads_output_file_when_configured(self, mock_prepare_runtime: MagicMock, tmp_path: Path) -> None:
        mock_prepare_runtime.return_value = _mock_runtime()
        output_path = tmp_path / "baseline_r1.json"
        output_path.write_text('{"matches": []}')

        case = Case(
            id="c1", agent=VALID_AGENT, prompt="p", graders=[],
            output_file=str(tmp_path / "{cell_id}_r{run_index}.json"),
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        result = run_case_once(case, cell, run_index=1)
        assert result.output_file_content == '{"matches": []}'

    @patch("eval.runner.prepare_runtime")
    def test_missing_output_file_leaves_content_none(self, mock_prepare_runtime: MagicMock, tmp_path: Path) -> None:
        mock_prepare_runtime.return_value = _mock_runtime()
        case = Case(
            id="c1", agent=VALID_AGENT, prompt="p", graders=[],
            output_file=str(tmp_path / "{cell_id}_r{run_index}.json"),
        )
        cell = Cell(id="baseline", agent=VALID_AGENT)

        result = run_case_once(case, cell, run_index=1)
        assert result.output_file_content is None

    @patch("eval.runner.prepare_runtime")
    def test_permission_prompt_denies_by_default(self, mock_prepare_runtime: MagicMock) -> None:
        mock_prepare_runtime.return_value = _mock_runtime()
        case = Case(id="c1", agent=VALID_AGENT, prompt="p", graders=[])
        cell = Cell(id="baseline", agent=VALID_AGENT)

        run_case_once(case, cell, run_index=1)
        call_kwargs = mock_prepare_runtime.call_args.kwargs
        assert call_kwargs["show_output"] is False
        assert call_kwargs["trace_enabled"] is False


class TestRunRepeated:
    @patch("eval.runner.prepare_runtime")
    def test_runs_n_times_with_increasing_index(self, mock_prepare_runtime: MagicMock) -> None:
        mock_prepare_runtime.return_value = _mock_runtime()
        case = Case(id="c1", agent=VALID_AGENT, prompt="p", graders=[])
        cell = Cell(id="baseline", agent=VALID_AGENT)

        results = run_repeated(case, cell, 3)
        assert [r.run_index for r in results] == [1, 2, 3]
