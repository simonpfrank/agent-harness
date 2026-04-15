"""Tests for tools.value_overlap."""

import json
from pathlib import Path

import pandas as pd

from tools.value_overlap import _normalize, value_overlap


class TestNormalize:
    def test_strips_and_lowers(self) -> None:
        assert _normalize([" Hello ", "WORLD"]) == {"hello", "world"}

    def test_drops_empty_and_nan(self) -> None:
        assert _normalize(["", "nan", None, "x"]) == {"x"}


class TestValueOverlap:
    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_finds_three_value_overlap(self, tmp_path: Path) -> None:
        ref = tmp_path / "ref.csv"
        inp = tmp_path / "inp.csv"
        self._write_csv(ref, [
            {"Primary Amount": "1842.05"}, {"Primary Amount": "125.26"},
            {"Primary Amount": "28.57"}, {"Primary Amount": "500.00"},
            {"Primary Amount": "99.99"},
        ])
        self._write_csv(inp, [
            {"Current Monthly Benefit": "1842.05"}, {"Current Monthly Benefit": "125.26"},
            {"Current Monthly Benefit": "28.57"}, {"Current Monthly Benefit": "10.0"},
            {"Current Monthly Benefit": "7.5"},
        ])
        result = json.loads(value_overlap(str(ref), str(inp), threshold=3))
        assert len(result["candidates"]) == 1
        cand = result["candidates"][0]
        assert cand["reference"] == "Primary Amount"
        assert cand["input"] == "Current Monthly Benefit"
        assert cand["overlap"] == 3

    def test_skips_below_threshold(self, tmp_path: Path) -> None:
        ref = tmp_path / "ref.csv"
        inp = tmp_path / "inp.csv"
        self._write_csv(ref, [{"A": v} for v in ["1", "2", "3", "4", "5"]])
        self._write_csv(inp, [{"B": v} for v in ["1", "2", "9", "8", "7"]])
        result = json.loads(value_overlap(str(ref), str(inp), threshold=3))
        assert result["candidates"] == []

    def test_case_insensitive(self, tmp_path: Path) -> None:
        ref = tmp_path / "ref.csv"
        inp = tmp_path / "inp.csv"
        self._write_csv(ref, [{"Sex": v} for v in ["M", "F", "M", "F", "M"]])
        self._write_csv(inp, [{"Gender": v} for v in ["m", "f", "m", "f", "m"]])
        result = json.loads(value_overlap(str(ref), str(inp), threshold=2))
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["overlap"] == 2

    def test_sorted_by_overlap(self, tmp_path: Path) -> None:
        ref = tmp_path / "ref.csv"
        inp = tmp_path / "inp.csv"
        pd.DataFrame({
            "Amount": ["100", "200", "300", "400", "500"],
            "State": ["FL", "CA", "TX", "NY", "WA"],
        }).to_csv(ref, index=False)
        pd.DataFrame({
            "Benefit": ["100", "200", "300", "999", "888"],
            "State": ["FL", "CA", "TX", "NY", "WA"],
        }).to_csv(inp, index=False)
        result = json.loads(value_overlap(str(ref), str(inp), threshold=3))
        assert len(result["candidates"]) == 2
        assert result["candidates"][0]["overlap"] >= result["candidates"][1]["overlap"]

    def test_reads_pension_files(self) -> None:
        ref_path = Path("data/pension_reference.xlsx")
        inp_path = Path("data/pension_input.xlsx")
        if not (ref_path.exists() and inp_path.exists()):
            import pytest
            pytest.skip("pension test data not available")

        result = json.loads(value_overlap(str(ref_path), str(inp_path), threshold=3))
        refs = {c["reference"] for c in result["candidates"]}
        assert "Zipcode" in refs
        assert "Primary Amount" in refs
        assert "Secondary Amount" in refs
