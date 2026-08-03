"""Tests for eval.graders code discovery and built-in code graders."""

import json
import tempfile
from pathlib import Path

from eval.graders import CodeGrader
from eval.graders.code.column_match import column_match
from eval.graders.code.contains import contains


class TestDiscoverCodeGraders:
    def test_discovers_custom_grader(self) -> None:
        from eval.graders import discover_code_graders

        registry: dict[str, CodeGrader] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            grader_file = Path(tmpdir) / "always_pass.py"
            grader_file.write_text(
                "from eval.types import GradeResult\n\n"
                "def always_pass(response_text: str, output_file_content: str | None) -> GradeResult:\n"
                '    """Always passes."""\n'
                "    return GradeResult(passed=True, score=1.0, detail={})\n"
            )
            discover_code_graders(tmpdir, base_registry=registry)
            assert "always_pass" in registry
            result = registry["always_pass"]("hi", None)
            assert result.passed is True

    def test_missing_dir_no_error(self) -> None:
        from eval.graders import discover_code_graders

        registry: dict[str, CodeGrader] = {}
        discover_code_graders("/nonexistent/graders/dir", base_registry=registry)
        assert registry == {}

    def test_skips_functions_without_return_annotation(self) -> None:
        from eval.graders import discover_code_graders

        registry: dict[str, CodeGrader] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            grader_file = Path(tmpdir) / "bad_grader.py"
            grader_file.write_text(
                "def bad_grader(x):\n"
                '    """No type hints."""\n'
                "    return x\n"
            )
            discover_code_graders(tmpdir, base_registry=registry)
            assert "bad_grader" not in registry

    def test_skips_private_functions(self) -> None:
        from eval.graders import discover_code_graders

        registry: dict[str, CodeGrader] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            grader_file = Path(tmpdir) / "helper.py"
            grader_file.write_text(
                "def _private(x: str) -> str:\n"
                '    """Private helper."""\n'
                "    return x\n"
            )
            discover_code_graders(tmpdir, base_registry=registry)
            assert "_private" not in registry

    def test_build_grader_registry_includes_builtins(self) -> None:
        from eval.graders import build_grader_registry

        registry = build_grader_registry()
        assert "contains" in registry
        assert "column_match" in registry

    def test_discovers_builtin_graders_correctly(self) -> None:
        """Discovery against the real eval/graders/code/ dir must not be
        confused by column_match.py's `from scripts import score_run` import
        — it should register `contains` and `column_match`, not `score_run`."""
        from eval.graders import discover_code_graders

        registry: dict[str, CodeGrader] = {}
        discover_code_graders("eval/graders/code", base_registry=registry)
        assert "contains" in registry
        assert "column_match" in registry
        assert "score_run" not in registry
        assert "score" not in registry


class TestContainsGrader:
    def test_passes_when_substring_present(self) -> None:
        result = contains("The answer is 4.", None, expected="4")
        assert result.passed is True
        assert result.score == 1.0

    def test_fails_when_substring_absent(self) -> None:
        result = contains("The answer is 5.", None, expected="4")
        assert result.passed is False
        assert result.score == 0.0

    def test_case_insensitive(self) -> None:
        result = contains("The Answer is OK", None, expected="ok")
        assert result.passed is True


class TestColumnMatchGrader:
    def test_perfect_match_passes(self, tmp_path: Path) -> None:
        expected_path = tmp_path / "expected.json"
        expected_path.write_text(json.dumps({
            "matches": [{"input": "UniqueID", "reference": "Record ID"}],
        }))
        output = json.dumps({
            "matches": [{"input_column": "UniqueID", "reference_column": "Record ID"}],
        })
        result = column_match("", output, expected=str(expected_path))
        assert result.passed is True
        assert result.score == 1.0
        assert result.detail["correct"] == 1
        assert result.detail["false_positives"] == 0

    def test_false_positive_fails(self, tmp_path: Path) -> None:
        expected_path = tmp_path / "expected.json"
        expected_path.write_text(json.dumps({
            "matches": [{"input": "UniqueID", "reference": "Record ID"}],
        }))
        output = json.dumps({
            "matches": [{"input_column": "UniqueID", "reference_column": "Wrong Column"}],
        })
        result = column_match("", output, expected=str(expected_path))
        assert result.passed is False
        assert result.detail["false_positives"] == 1
        assert result.detail["missed_expected"] == [("UniqueID", "Record ID")]

    def test_missing_output_treated_as_empty(self, tmp_path: Path) -> None:
        expected_path = tmp_path / "expected.json"
        expected_path.write_text(json.dumps({"matches": []}))
        result = column_match("", None, expected=str(expected_path))
        assert result.passed is True
        assert result.score == 0.0
