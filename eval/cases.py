"""Load test cases and cells from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from eval.types import Case, Cell, GraderSpec


def load_cases(cases_dir: str) -> list[Case]:
    """Load all test cases from a directory of YAML files, one case per file.

    Args:
        cases_dir: Directory containing case `.yaml` files.

    Returns:
        Cases sorted by filename. Empty list if the directory has no
        `.yaml` files (or doesn't exist).
    """
    path = Path(cases_dir)
    if not path.is_dir():
        return []
    cases: list[Case] = []
    for yaml_file in sorted(path.glob("*.yaml")):
        raw: dict[str, Any] = yaml.safe_load(yaml_file.read_text())
        graders = [GraderSpec(**g) for g in raw["graders"]]
        cases.append(Case(
            id=raw["id"],
            agent=raw["agent"],
            prompt=raw["prompt"],
            graders=graders,
            output_file=raw.get("output_file"),
        ))
    return cases


def load_cells(cells_path: str) -> list[Cell]:
    """Load a list of cells from a single YAML file.

    Args:
        cells_path: Path to a YAML file containing a list of cell mappings.

    Returns:
        Parsed cells, in file order.
    """
    raw: list[dict[str, Any]] = yaml.safe_load(Path(cells_path).read_text())
    return [Cell(**cell) for cell in raw]
