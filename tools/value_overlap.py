"""Compute pairwise sample-value overlap between two data files."""

import json
from pathlib import Path
from typing import Any

import pandas as pd

_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]


def _read(file_path: str, max_rows: int) -> pd.DataFrame:
    """Read a CSV or Excel file as strings, trying multiple encodings for CSV."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(file_path, dtype=str, nrows=max_rows)
    if ext == ".csv":
        for enc in _ENCODINGS:
            try:
                return pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False, nrows=max_rows)
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Could not decode {path}")
    raise ValueError(f"Unsupported file type: {ext}")


def _normalize(values: list[Any]) -> set[str]:
    """Return a set of stripped, lower-cased, non-empty strings."""
    result: set[str] = set()
    for v in values:
        if v is None:
            continue
        s = str(v).strip().lower()
        if s and s != "nan":
            result.add(s)
    return result


def _sample_values_per_column(df: pd.DataFrame) -> dict[str, list[str]]:
    """Return column -> list of non-empty sample string values."""
    cols: dict[str, list[str]] = {}
    for name in df.columns:
        series = df[str(name)].dropna()
        cols[str(name).strip()] = [str(v) for v in series.tolist()]
    return cols


def value_overlap(reference_file: str, input_file: str, threshold: int = 3) -> str:
    """Find pairs of columns whose sample values overlap by at least `threshold`.

    Reads both files, extracts sample values per column, and returns a candidate
    list sorted by overlap count. Deterministic — no LLM. Use the output as a
    candidate list before deciding final matches.

    Args:
        reference_file: Path to the reference CSV or Excel file.
        input_file: Path to the incoming CSV or Excel file.
        threshold: Minimum number of overlapping sample values to emit a candidate.

    Returns:
        JSON string with a "candidates" list. Each candidate is
        {input, reference, overlap, shared_values}.

    Example:
        >>> # value_overlap("data/reference.xlsx", "data/input.xlsx", threshold=3)
        >>> # returns pairs of columns sharing >=3 sample values
    """
    ref_df = _read(reference_file, max_rows=1000)
    inp_df = _read(input_file, max_rows=1000)

    ref_cols = {name: _normalize(vals) for name, vals in _sample_values_per_column(ref_df).items()}
    inp_cols = {name: _normalize(vals) for name, vals in _sample_values_per_column(inp_df).items()}

    candidates: list[dict[str, Any]] = []
    for ref_name, ref_values in ref_cols.items():
        if not ref_values:
            continue
        for inp_name, inp_values in inp_cols.items():
            if not inp_values:
                continue
            shared = ref_values & inp_values
            if len(shared) >= threshold:
                candidates.append({
                    "input": inp_name,
                    "reference": ref_name,
                    "overlap": len(shared),
                    "shared_values": sorted(shared),
                })

    candidates.sort(key=lambda c: c["overlap"], reverse=True)
    return json.dumps({"candidates": candidates})
