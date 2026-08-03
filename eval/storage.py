"""Result storage — JSONL as source of truth, CSV as a derived projection."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from eval.types import RunResult

_CSV_FIELDS = ["case_id", "cell_id", "run_index", "turns", "cost", "gate_passed", "signal_score", "timestamp"]


def append_result(result: RunResult, path: str) -> None:
    """Append one run result as a JSONL line.

    Args:
        result: The run result to persist.
        path: JSONL file path. Parent directories are created if needed.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(result)) + "\n")


def load_results(path: str) -> list[RunResult]:
    """Load all run results from a JSONL file.

    Args:
        path: JSONL file path.

    Returns:
        List of results, or an empty list if the file doesn't exist.
    """
    p = Path(path)
    if not p.exists():
        return []
    results: list[RunResult] = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        results.append(RunResult(**json.loads(line)))
    return results


def to_csv(results: list[RunResult], out_path: str) -> None:
    """Write a flat CSV projection of run results for spreadsheet use.

    Args:
        results: Run results to project. Nested fields (grades, response
            text, output file content) are omitted — see the JSONL source
            for full detail.
        out_path: CSV file path to write.
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for result in results:
            row = asdict(result)
            writer.writerow({name: row[name] for name in _CSV_FIELDS})
