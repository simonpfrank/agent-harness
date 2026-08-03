# Evaluation Framework — `eval/`

**Status:** Built and verified end-to-end against the real Anthropic API
(2026-08-03) — see `eval/cases/column-matcher/pension-match.yaml` and
`eval/cells/column-matcher.yaml` (H0 vs. H4 from `docs/matcher_experiments.md`).

## Context

The gap this fills: `scripts/run_experiment.py` + `scripts/score_run.py` already
run column-matcher experiments across `(config, model)` cells, but the script
is hardcoded to one agent's output shape, requires hand-editing
`agents/column-matcher/` between sweeps, shells out to the CLI and
regex-scrapes trace files for cost/turns, and produces a flat CSV that's hard
to draw a conclusion from once more than one grader is involved.

`eval/` generalizes this: define test cases once, run them against any agent
(varying instructions/model/temperature as "cells"), grade with pluggable code
graders and an LLM-judge grader, and produce a ranked leaderboard instead of a
raw dump. It lives as a sibling top-level package next to `agent_harness/` —
a consumer of the framework (like `scripts/` already is), not part of it.

## Architecture

```
eval/
  types.py           # Case, GraderSpec, Cell, GradeResult, RunResult
  cases.py           # load_cases(dir) -> list[Case]; load_cells(path) -> list[Cell]
  storage.py         # append_result/load_results (JSONL, source of truth); to_csv (derived projection)
  runner.py          # run_case_once(case, cell, run_index) -> RunResult; run_repeated(...)
  graders/
    __init__.py      # build_grader_registry() (built-ins) + discover_code_graders(dir) (custom, mirrors tools.py)
    code/
      contains.py    # reference grader: substring match on response text
      column_match.py # imports scripts.score_run — the matcher grader, lifted not rewritten
    model.py          # single LLM-as-judge function via agent_harness.providers.registry
  report.py           # summarize() (gate/signal aggregation), rank() (lexicographic), render_table()/render_markdown()
  cli.py              # `python -m eval run ...` / `python -m eval report ...`
```

## Design decisions

**Gate vs. signal graders.** Code graders (deterministic) are gates —
disqualifying, pass/fail. The model grader is a signal — a quality score used
only to rank among cells that already cleared every gate. A cell failing a
gate never outranks one that passes, no matter how good its signal score
looks. This resolves the "how do we conclude anything when a model grader and
several code scorers each carry an unknown weight" problem without inventing
a blended score that hides the value judgment. See `eval/report.py::rank()` —
disqualified cells always sort last, regardless of the requested order.

**Ranking is lexicographic, not blended.** `rank(summaries, order)` takes an
ordered list of `(field, direction)` tie-breaks — e.g. `gate_pass_rate desc →
stdev asc → signal_score desc → mean_cost asc` (the CLI default, aliased as
`--rank gate,stdev,signal,cost`). This mirrors how `docs/matcher_experiments.md`
already ranks configs by hand (mean_correct + stdev, tie-break cost) — made
explicit and re-runnable instead of eyeballed per round.

**JSONL as source of truth, CSV as a derived projection.** `storage.py`
writes one JSON line per run (full structured detail — itemized misses,
judge responses). `to_csv()` flattens selected fields for spreadsheet use, and
can be regenerated from the JSONL at any time — schema changes never break an
existing CSV.

**Instructions/system-prompt variants are a runtime override, not a folder
copy.** `Cell.instructions_override` points at alternate `instructions.md`
content; `runner.py` swaps it into `AgentConfig.instructions` before calling
`prepare_runtime()`. No agent-folder duplication needed to A/B test prompt
wording.

**Non-interactive by construction.** `run_case_once` calls `prepare_runtime`
with `permission_prompt_fn=deny_permission` (existing, `runtime.py:190`,
built for exactly this — "delegated runs that cannot prompt") and
`show_output=False, trace_enabled=False`.

**Repeats are independent trials.** `_clear_memory()` deletes the agent's
`memory/*.md` before each run (generalized from
`run_experiment.py::_clear_memory`) — otherwise `save_memory`/`recall_memory`
tools would leak state across repeats, and "N independent trials" wouldn't be.

## Small additive changes to `agent_harness/`

- `Budget` gained read-only `turns`/`total_cost` properties (previously only
  `.summary()`, a formatted string, was public).
- `PreparedRuntime` gained a `budget: Budget` field (the `Budget` instance
  `prepare_runtime()` already builds internally, now exposed).

Both let the eval runner read exact cost/turn numbers directly, instead of
regex-scraping trace files like `run_experiment.py` does, or building a second
`Budget`/`COST_TABLE` lookup.

## Usage

```bash
.venv/bin/python -m eval run eval/cases/column-matcher \
  --cells eval/cells/column-matcher.yaml --repeats 3 --out /tmp/results.jsonl

.venv/bin/python -m eval report /tmp/results.jsonl --rank gate,stdev,signal,cost
```

Case file shape (`eval/cases/<name>/*.yaml`, one file per case):

```yaml
id: pension-column-match
agent: agents/column-matcher
prompt: "Match columns between data/pension_input.xlsx and data/pension_reference.xlsx..."
output_file: "data/experiment_runs/{cell_id}_r{run_index}.json"
graders:
  - name: column_match
    kind: gate
    args:
      expected: data/expected_matches.json
  - name: model
    kind: signal
    args:
      rubric: "Rate how clearly the agent explained its matching signals, 0-1."
```

Cells file shape (`eval/cells/<name>.yaml`, a list):

```yaml
- id: baseline
  agent: agents/column-matcher
- id: variant-a
  agent: agents/column-matcher
  instructions_override: eval/variants/column-matcher-v2.md
  temperature: 0.0
```

## Deferred idea — testing external coding assistants (not built)

Raised mid-build: extend this beyond `agent_harness` agents to benchmark the
coding tools actually used day to day — Claude Code, Codex CLI, and VS
Code/GitHub Copilot. Feasibility varies:

- **Claude Code**: `claude -p "prompt" --output-format json` — scriptable,
  structured output.
- **Codex CLI**: `codex exec "prompt"` — scriptable, non-interactive.
- **GitHub Copilot**: has a CLI path too — a VS Code command-line entry point
  (`code chat "<prompt>"` plus mode flags — ask/edit/agent — and an
  add-file-style option) that also accepts piped stdin, e.g.
  `python app.py | code chat "why does it fail"`.

The natural seam is a `Subject` protocol in `eval/runner.py` — today
`run_case_once` hardcodes "load an `AgentConfig`, call `prepare_runtime`" as
the only way to produce a `RunResult`. A `Subject` would be anything that
takes a prompt and returns `(response_text, output_file_content,
cost/turns-if-available)`; graders only ever look at `response_text`/
`output_file_content`, so they wouldn't need to change at all. Not built —
just don't design `runner.py` in a way that makes adding this later a
rewrite. Revisit when there's an actual case to compare tool effectiveness,
not before.

## What's not built

- Regression detection (diff a run against a stored baseline) — natural
  next step once the JSONL history has enough real runs to compare against.
- A `--gate-threshold` CLI flag (currently `report.summarize()`'s default of
  `1.0` — every gate grader must pass every run — is hardcoded at the call
  site in `cli.py`).
- The `Subject` abstraction above.
