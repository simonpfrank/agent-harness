"""Profile columns in a CSV or Excel file for data analytics."""

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
_DATE_PATTERNS = [
    (r"\d{4}-\d{2}-\d{2}", "YYYY-MM-DD"),
    (r"\d{2}/\d{2}/\d{4}", "DD/MM/YYYY"),
    (r"\d{2}-\d{2}-\d{4}", "DD-MM-YYYY"),
]


def _read_file(file_path: str, max_rows: int) -> pd.DataFrame:
    """Read CSV or Excel into a DataFrame, all columns as strings."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    ext = path.suffix.lower()
    if ext == ".csv":
        return _read_csv(path, max_rows)
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(file_path, dtype=str, nrows=max_rows)
    raise ValueError(f"Unsupported file type: {ext}")


def _read_csv(path: Path, max_rows: int) -> pd.DataFrame:
    """Try multiple encodings to read a CSV."""
    for enc in _ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False, nrows=max_rows)
            df.columns = df.columns.str.strip()
            return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Could not decode {path}")


def _is_numeric(val: str) -> bool:
    """Check if a string value is numeric."""
    try:
        float(val.replace(",", ""))
        return True
    except (ValueError, AttributeError):
        return False


def _detect_type(values: list[str]) -> str:
    """Detect column data type from non-empty values."""
    if not values:
        return "empty"
    numeric = sum(1 for v in values if _is_numeric(v))
    if numeric == len(values):
        return "numeric"
    dates = sum(1 for v in values if any(re.match(p, v) for p, _ in _DATE_PATTERNS))
    if dates == len(values):
        return "date"
    if numeric > 0 or dates > 0:
        return "mixed"
    return "text"


def _detect_pattern(values: list[str], data_type: str) -> str:
    """Detect value pattern."""
    if not values:
        return ""
    if data_type == "numeric":
        return "numeric"
    if data_type == "date":
        for val in values[:5]:
            for regex, label in _DATE_PATTERNS:
                if re.match(regex, val):
                    return label
        return "varied"
    if len(values) >= 2 and all(re.match(r"^[A-Z]+\d+$", v) for v in values[:5]):
        return "AAA999"
    return "varied"


def _characteristics(values: list[str], total: int) -> list[str]:
    """Generate characteristic flags."""
    chars: list[str] = []
    populated = len(values)
    if total > 0 and populated / total < 0.5:
        chars.append("sparse")
    unique = len(set(values))
    if unique == populated and populated > 1:
        chars.append("all_unique")
    if unique > 100:
        chars.append("high_cardinality")
    return chars


def _numeric_stats(values: list[str]) -> dict[str, float] | None:
    """Compute min, max, mean for numeric values."""
    nums: list[float] = []
    for v in values:
        try:
            nums.append(float(v.replace(",", "")))
        except (ValueError, AttributeError):
            continue
    if not nums:
        return None
    return {
        "min": round(min(nums), 2),
        "max": round(max(nums), 2),
        "mean": round(sum(nums) / len(nums), 2),
    }


def _profile_column(series: "pd.Series[str]") -> dict[str, Any]:
    """Profile a single column."""
    total = len(series)
    non_empty = [str(v).strip() for v in series if pd.notna(v) and str(v).strip()]
    populated = len(non_empty)
    unique_count = len(set(non_empty)) if non_empty else 0
    data_type = _detect_type(non_empty)
    return {
        "name": str(series.name),
        "data_type": data_type,
        "population_rate": round(populated / total, 2) if total > 0 else 0.0,
        "unique_count": unique_count,
        "unique_percent": round(unique_count / populated * 100, 1) if populated > 0 else 0.0,
        "pattern": _detect_pattern(non_empty, data_type),
        "sample_values": non_empty[:5],
        "characteristics": _characteristics(non_empty, total),
        "stats": _numeric_stats(non_empty) if data_type == "numeric" else None,
    }


def profile_data(file_path: str, max_sample_rows: int = 1000, remove_columns: str = "") -> str:
    """Profile columns in a CSV or Excel file, returning JSON metadata.

    Args:
        file_path: Path to a CSV or Excel file.
        max_sample_rows: Maximum rows to read for profiling.
        remove_columns: Comma-separated column names to exclude (case-insensitive).

    Returns:
        JSON string with per-column metadata including data types and patterns.
    """
    df = _read_file(file_path, max_sample_rows)
    if remove_columns:
        exclude = {name.strip().lower() for name in remove_columns.split(",")}
        df = df[[c for c in df.columns if c.lower() not in exclude]]
    columns = [_profile_column(df[col]) for col in df.columns]
    result = {
        "file": file_path,
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "columns": columns,
    }
    return json.dumps(result, indent=2)
