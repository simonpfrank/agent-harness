"""Tests for eval.storage."""

import csv
import tempfile
from pathlib import Path

from eval.storage import append_result, load_results, to_csv
from eval.types import RunResult


def _result(case_id: str = "case-1", run_index: int = 1) -> RunResult:
    return RunResult(
        case_id=case_id,
        cell_id="baseline",
        run_index=run_index,
        response_text="4",
        output_file_content=None,
        turns=1,
        cost=0.001,
        grades=[{"grader": "contains", "kind": "gate", "passed": True, "score": 1.0, "detail": {}}],
        gate_passed=True,
        signal_score=None,
        timestamp="2026-08-03T12:00:00+00:00",
    )


class TestAppendAndLoad:
    def test_round_trip_single_result(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        append_result(_result(), path)
        loaded = load_results(path)
        assert len(loaded) == 1
        assert loaded[0].case_id == "case-1"
        assert loaded[0].grades[0]["grader"] == "contains"
        Path(path).unlink()

    def test_appends_multiple_results(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        append_result(_result(run_index=1), path)
        append_result(_result(run_index=2), path)
        loaded = load_results(path)
        assert len(loaded) == 2
        assert loaded[1].run_index == 2
        Path(path).unlink()

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "results" / "out.jsonl")
            append_result(_result(), path)
            assert Path(path).exists()

    def test_missing_file_returns_empty(self) -> None:
        assert load_results("/nonexistent/path.jsonl") == []


class TestToCsv:
    def test_writes_flat_rows(self) -> None:
        results = [_result(case_id="a"), _result(case_id="b")]
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            out_path = f.name
        to_csv(results, out_path)
        with open(out_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["case_id"] == "a"
        assert rows[0]["cost"] == "0.001"
        assert rows[0]["gate_passed"] == "True"
        Path(out_path).unlink()
