"""CLI entry point for the evaluation framework."""

from __future__ import annotations

import argparse

from eval.cases import load_cases, load_cells
from eval.report import rank, render_table, summarize
from eval.runner import run_repeated
from eval.storage import append_result, load_results

_RANK_ALIASES: dict[str, tuple[str, str]] = {
    "gate": ("gate_pass_rate", "desc"),
    "stdev": ("stdev", "asc"),
    "signal": ("signal_score", "desc"),
    "cost": ("mean_cost", "asc"),
    "turns": ("mean_turns", "asc"),
}

_DEFAULT_RANK_ORDER: list[tuple[str, str]] = [
    _RANK_ALIASES["gate"], _RANK_ALIASES["stdev"], _RANK_ALIASES["signal"], _RANK_ALIASES["cost"],
]


def resolve_rank_order(rank_spec: str | None) -> list[tuple[str, str]]:
    """Resolve a `--rank` CLI spec into ranking criteria.

    Args:
        rank_spec: Comma-separated alias list (e.g. "gate,stdev,signal,cost"),
            or None for the default order.

    Returns:
        Ordered list of `(field, direction)` tuples for `report.rank()`.

    Raises:
        ValueError: If an alias isn't recognized.
    """
    if rank_spec is None:
        return _DEFAULT_RANK_ORDER
    order = []
    for alias in rank_spec.split(","):
        if alias not in _RANK_ALIASES:
            raise ValueError(f"Unknown rank metric '{alias}' — choose from {sorted(_RANK_ALIASES)}")
        order.append(_RANK_ALIASES[alias])
    return order


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list. Defaults to `sys.argv[1:]`.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(description="Evaluation framework")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Run test cases against cells")
    run_parser.add_argument("cases_dir", help="Directory of case YAML files")
    run_parser.add_argument("--cells", required=True, help="Path to cells YAML file")
    run_parser.add_argument("--repeats", type=int, default=1, help="Repeats per (case, cell)")
    run_parser.add_argument("--out", required=True, help="JSONL output path")

    report_parser = sub.add_parser("report", help="Summarize results into a leaderboard")
    report_parser.add_argument("results", help="JSONL results path")
    report_parser.add_argument("--rank", default=None, help="Comma-separated rank order, e.g. gate,stdev,signal,cost")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the `eval` CLI."""
    args = parse_args(argv)
    if args.command == "run":
        cases = load_cases(args.cases_dir)
        cells = load_cells(args.cells)
        for cell in cells:
            for case in cases:
                for result in run_repeated(case, cell, args.repeats):
                    append_result(result, args.out)
    elif args.command == "report":
        results = load_results(args.results)
        summaries = summarize(results)
        ranked = rank(summaries, resolve_rank_order(args.rank))
        render_table(ranked)
    else:
        parse_args(["--help"])


if __name__ == "__main__":
    main()
