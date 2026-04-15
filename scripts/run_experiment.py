"""Run column-matcher experiments across (config, model) cells.

For each cell, runs N times, clears memory between runs, and appends
one CSV row per run to docs/experiment_results.csv.

Usage:
    .venv/bin/python -m scripts.run_experiment \\
        --config H0 --provider openai --model gpt-4o-mini --runs 5
    .venv/bin/python -m scripts.run_experiment \\
        --config H4 --provider anthropic --model claude-haiku-4-5-20251001 \\
        --runs 5 --temperature 0.0
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

from scripts.score_run import score

AGENT_DIR = Path("agents/column-matcher")
EXPECTED_PATH = Path("data/expected_matches.json")
RUNS_DIR = Path("data/experiment_runs")
RESULTS_CSV = Path("docs/experiment_results.csv")
INPUT_XLSX = "data/pension_input.xlsx"
REFERENCE_XLSX = "data/pension_reference.xlsx"
CONTEXT_MD = "data/context.md"

_BUDGET_RE = re.compile(r"Turn (\d+)/\d+ \| \$([0-9.]+)")


def _clear_memory() -> None:
    """Delete all .md files in the agent's memory folder."""
    memory_dir = AGENT_DIR / "memory"
    if memory_dir.is_dir():
        for md in memory_dir.glob("*.md"):
            md.unlink()


def _newest_trace_after(start: float) -> Path | None:
    """Return the newest trace file modified after start timestamp."""
    logs = AGENT_DIR / "logs"
    if not logs.is_dir():
        return None
    candidates = [
        p for p in logs.glob("*.trace.jsonl") if p.stat().st_mtime >= start
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_trace(trace: Path) -> tuple[float, int]:
    """Return (cost_usd, turns) from the last budget event in a trace."""
    cost = 0.0
    turns = 0
    for line in trace.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "budget":
            match = _BUDGET_RE.search(event.get("summary", ""))
            if match:
                turns = int(match.group(1))
                cost = float(match.group(2))
    return cost, turns


def _build_prompt(output_path: Path) -> str:
    return (
        f"Match columns between {INPUT_XLSX} (incoming) and "
        f"{REFERENCE_XLSX} (reference). Read {CONTEXT_MD} for domain terms. "
        f"Write the final JSON result to {output_path}."
    )


def run_once(
    config_name: str,
    provider: str,
    model: str,
    run_index: int,
    temperature: float | None,
) -> dict:
    """Run the agent once and return a result dict."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RUNS_DIR / f"{config_name}_{provider}_{model}_r{run_index}.json"
    if output_path.exists():
        output_path.unlink()

    _clear_memory()
    start = time.time()

    cmd = [
        ".venv/bin/python", "-m", "agent_harness", "run",
        str(AGENT_DIR), _build_prompt(output_path),
        "--provider", provider, "--model", model,
    ]
    if temperature is not None:
        cmd += ["--temperature", str(temperature)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    trace = _newest_trace_after(start)
    cost, turns = _parse_trace(trace) if trace else (0.0, 0)

    if not output_path.exists():
        return {
            "config": config_name, "provider": provider, "model": model,
            "run": run_index, "correct": 0, "false_positives": 0,
            "cost": cost, "turns": turns,
            "error": f"No output file. Exit {proc.returncode}. stderr head: {proc.stderr[:200]}",
        }

    output = json.loads(output_path.read_text())
    expected = json.loads(EXPECTED_PATH.read_text())
    result = score(output, expected)
    return {
        "config": config_name, "provider": provider, "model": model,
        "run": run_index, "correct": result.correct,
        "false_positives": result.false_positives,
        "cost": cost, "turns": turns, "error": "",
    }


def _write_row(row: dict) -> None:
    """Append one row to the results CSV, writing header if new."""
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    is_new = not RESULTS_CSV.exists()
    with RESULTS_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Config label e.g. H0, H4")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=None)
    args = parser.parse_args(argv)

    corrects: list[int] = []
    costs: list[float] = []
    for i in range(1, args.runs + 1):
        print(f"[{args.config} / {args.model}] run {i}/{args.runs}...", flush=True)
        row = run_once(args.config, args.provider, args.model, i, args.temperature)
        _write_row(row)
        print(
            f"  correct={row['correct']}/11 fp={row['false_positives']} "
            f"cost=${row['cost']:.4f} turns={row['turns']} "
            f"{('ERR: ' + row['error']) if row['error'] else ''}",
            flush=True,
        )
        if not row["error"]:
            corrects.append(row["correct"])
            costs.append(row["cost"])

    if corrects:
        print(
            f"\n[{args.config} / {args.model}] N={len(corrects)}  "
            f"mean={statistics.mean(corrects):.2f}  "
            f"stdev={statistics.stdev(corrects) if len(corrects) > 1 else 0.0:.2f}  "
            f"total_cost=${sum(costs):.4f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
