"""Tests for eval.cases."""

from pathlib import Path

from eval.cases import load_cases, load_cells

_CASE_YAML = """\
id: two-plus-two
agent: agents/hello
prompt: "What is 2+2? Reply with just the number."
graders:
  - name: contains
    kind: gate
    args:
      expected: "4"
"""

_CASE_WITH_OUTPUT_FILE_YAML = """\
id: matcher
agent: agents/column-matcher
prompt: "Match columns"
output_file: "data/experiment_runs/{cell_id}_r{run_index}.json"
graders:
  - name: column_match
    kind: gate
    args:
      expected: data/expected_matches.json
  - name: model
    kind: signal
    args:
      rubric: "Rate clarity 0-1"
"""

_CELLS_YAML = """\
- id: baseline
  agent: agents/hello
- id: variant-a
  agent: agents/hello
  instructions_override: eval/variants/a.md
  model: claude-haiku-4-5-20251001
  temperature: 0.0
"""


class TestLoadCases:
    def test_loads_single_case(self, tmp_path: Path) -> None:
        (tmp_path / "two_plus_two.yaml").write_text(_CASE_YAML)
        cases = load_cases(str(tmp_path))
        assert len(cases) == 1
        assert cases[0].id == "two-plus-two"
        assert cases[0].agent == "agents/hello"
        assert cases[0].graders[0].name == "contains"
        assert cases[0].graders[0].kind == "gate"
        assert cases[0].graders[0].args == {"expected": "4"}
        assert cases[0].output_file is None

    def test_loads_case_with_output_file_and_multiple_graders(self, tmp_path: Path) -> None:
        (tmp_path / "matcher.yaml").write_text(_CASE_WITH_OUTPUT_FILE_YAML)
        cases = load_cases(str(tmp_path))
        assert len(cases) == 1
        assert cases[0].output_file == "data/experiment_runs/{cell_id}_r{run_index}.json"
        assert len(cases[0].graders) == 2
        assert cases[0].graders[1].kind == "signal"

    def test_loads_multiple_files_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b.yaml").write_text(_CASE_YAML)
        (tmp_path / "a.yaml").write_text(_CASE_WITH_OUTPUT_FILE_YAML)
        cases = load_cases(str(tmp_path))
        assert [c.id for c in cases] == ["matcher", "two-plus-two"]

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        assert load_cases(str(tmp_path)) == []


class TestLoadCells:
    def test_loads_cells_from_file(self, tmp_path: Path) -> None:
        cells_path = tmp_path / "cells.yaml"
        cells_path.write_text(_CELLS_YAML)
        cells = load_cells(str(cells_path))
        assert len(cells) == 2
        assert cells[0].id == "baseline"
        assert cells[0].instructions_override is None
        assert cells[1].instructions_override == "eval/variants/a.md"
        assert cells[1].temperature == 0.0
