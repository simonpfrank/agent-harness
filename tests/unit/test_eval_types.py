"""Tests for eval.types."""

from eval.types import Case, Cell, GradeResult, GraderSpec, RunResult


class TestGraderSpec:
    def test_construction(self) -> None:
        spec = GraderSpec(name="contains", kind="gate", args={"expected": "4"})
        assert spec.name == "contains"
        assert spec.kind == "gate"
        assert spec.args == {"expected": "4"}


class TestCase:
    def test_construction_with_defaults(self) -> None:
        case = Case(
            id="two-plus-two",
            agent="agents/hello",
            prompt="What is 2+2?",
            graders=[GraderSpec(name="contains", kind="gate", args={"expected": "4"})],
        )
        assert case.id == "two-plus-two"
        assert case.output_file is None

    def test_construction_with_output_file(self) -> None:
        case = Case(
            id="matcher",
            agent="agents/column-matcher",
            prompt="Match columns",
            graders=[],
            output_file="data/experiment_runs/{cell_id}_r{run_index}.json",
        )
        assert case.output_file == "data/experiment_runs/{cell_id}_r{run_index}.json"


class TestCell:
    def test_construction_with_defaults(self) -> None:
        cell = Cell(id="baseline", agent="agents/hello")
        assert cell.instructions_override is None
        assert cell.provider is None
        assert cell.model is None
        assert cell.temperature is None

    def test_construction_with_overrides(self) -> None:
        cell = Cell(
            id="variant-a", agent="agents/hello",
            instructions_override="eval/variants/a.md",
            provider="anthropic", model="claude-haiku-4-5-20251001", temperature=0.0,
        )
        assert cell.instructions_override == "eval/variants/a.md"
        assert cell.temperature == 0.0


class TestGradeResult:
    def test_construction(self) -> None:
        result = GradeResult(passed=True, score=1.0, detail={"note": "ok"})
        assert result.passed is True
        assert result.score == 1.0
        assert result.detail == {"note": "ok"}


class TestRunResult:
    def test_construction(self) -> None:
        result = RunResult(
            case_id="two-plus-two",
            cell_id="baseline",
            run_index=1,
            response_text="4",
            output_file_content=None,
            turns=1,
            cost=0.001,
            grades=[{"grader": "contains", "kind": "gate", "passed": True, "score": 1.0, "detail": {}}],
            gate_passed=True,
            signal_score=None,
            timestamp="2026-08-03T12:00:00+00:00",
        )
        assert result.gate_passed is True
        assert result.signal_score is None
        assert result.grades[0]["grader"] == "contains"
