## Last Session (2026-08-03)
**Status:** In Progress
**Working on:** New `eval/` package — general-purpose evaluation framework (test cases, code + model graders with gate/signal split, JSONL storage, ranked leaderboard report), replacing the ad hoc `scripts/run_experiment.py` pattern. Plan approved and saved at `/Users/simonfrank/.claude/plans/abstract-doodling-wren.md`. Streaming + extended thinking work (Anthropic + OpenAI-modern) from earlier this session is done — see the plan file history / `docs/streaming-plan.md` for that.
**Next step:** Build order per the plan: `eval/types.py` -> `Budget`/`PreparedRuntime` additive changes -> `eval/storage.py` -> `eval/cases.py` -> `eval/graders/code/*` + discovery -> `eval/graders/model.py` -> `eval/runner.py` -> `eval/report.py` -> `eval/cli.py` -> `docs/eval_framework.md` + `docs/roadmap.md` update -> capstone column-matcher suite + real run.
**Notes:** `column_match` grader reuses `scripts/score_run.py::score()` almost verbatim (per user's explicit ask for "a matcher evaluator in the new approach") rather than reimplementing comparison logic. `eval/` is a sibling top-level package, not inside `agent_harness/` — deliberate, matches how `scripts/` already consumes the framework rather than extending it.
**Notes:** Resolves `docs/streaming-plan.md`'s outstanding decisions #1 and #3. `on_delta`/`on_thinking_delta` callbacks take `(agent_id, chunk)` to match the roadmap's L3 sink design without a future breaking change; parallel-agent/RunContext work itself is explicitly out of scope. Extended thinking stays Anthropic-only (OpenAI has no readable reasoning-content extraction, only the pre-existing `reasoning_effort` knob). Streaming is now valid for `anthropic` and `openai` (Responses API models only — rejected for OpenAI's Chat Completions/`base_url` path, both at the provider boundary and in `validate_config`).
Verified: `.venv/bin/pytest tests/unit -q` (excluding two pre-existing unrelated failures in test_value_overlap.py/test_profile_data.py from a missing openpyxl/expat dependency) -> `326 passed`. `.venv/bin/ruff check agent_harness tests` -> `All checks passed!`. `env MYPYPATH=. .venv/bin/mypy --strict --explicit-package-bases agent_harness tests` -> `Success: no issues found in 71 source files`. `radon cc --min D agent_harness` -> only the pre-existing accepted D (`_to_anthropic_messages`), no new D/worse.
Integration: Anthropic streaming + thinking real-API tests pass (`tests/integration/test_end_to_end.py::TestStreamingIntegration`, 2/2). Full `tests/integration -q` run: `56 passed, 6 failed`, all 6 pre-existing OpenAI failures from `insufficient_quota` (account has no credits), unrelated to code. The new OpenAI streaming integration test (`TestOpenAIStreamingIntegration`) was written and run but also hit `insufficient_quota` — the error was a retryable `api_error` (429), not `BadRequestError`, meaning the request reached OpenAI correctly shaped; it just couldn't complete. **Not fully integration-verified end-to-end** — revisit once the OpenAI account has credits.

---

# Progress Tracker

## Phase 1 — A Working Agent ✅

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| types.py | ✅ (10) | ✅ | ⏭️ N/A |
| tools.py + discovery | ✅ (24) | ✅ | ✅ |
| budget.py | ✅ (6) | ✅ | ✅ |
| display.py | ✅ (7) | ✅ | ⏭️ N/A |
| providers/anthropic.py | ✅ (11) | ✅ | ✅ (4) |
| providers/openai_provider.py | ✅ (25) | ✅ | ✅ (6) |
| providers/retry.py | ✅ (via provider tests) | ✅ | ✅ |
| config.py | ✅ (9) | ✅ | ✅ |
| cli.py + overrides | ✅ (20) | ✅ | ⏭️ N/A |
| 7 example agents | ⏭️ N/A | ✅ | ✅ (smoke tested) |

## Phase 2 — Security and Reliability ✅

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| hooks.py | ✅ (48) | ✅ | ✅ (5) |
| network.py | ✅ (via hooks) | ✅ | ✅ |
| permissions.py | ✅ (9) | ✅ | ✅ (3) |
| log.py | ✅ (4) | ✅ | ✅ (1) |
| trace.py | ✅ (4) | ✅ | ✅ (1) |

## Phase 3 — Multi-Provider and Loop Patterns ✅

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| loops/react.py | ✅ (6) | ✅ | ✅ (2) |
| loops/plan_execute.py | ✅ (7) | ✅ | ✅ (1) |
| loops/rewoo.py | ✅ (5) | ✅ | ✅ (1) |
| loops/reflection.py | ✅ (5) | ✅ | ✅ (2) |
| loops/eval_optimize.py | ✅ (6) | ✅ | ✅ (2) |
| loops/ralph.py | ✅ (5) | ✅ | ✅ (1) |
| loops/debate.py | ✅ (4) | ✅ | ✅ (1) |
| loops/common.py | ⏭️ N/A | ✅ | ✅ (via loops) |
| context.py | ✅ (8) | ✅ | ⏭️ N/A |

## Phase 4 — Memory, Routing, and Agent Building ✅

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| session.py | ✅ (4) | ✅ | ✅ (1) |
| memory.py | ✅ (7) | ✅ | ✅ (1) |
| routing.py | ✅ (7) | ✅ | ✅ (1) |
| scaffold.py | ✅ (6) | ✅ | ⏭️ N/A |
| skills.py | ✅ (6) | ✅ | ✅ (2) |

## Phase 5 — Polish and Examples ✅

| Component | Status |
|-----------|--------|
| 7 example agents | ✅ All run successfully |
| 2 custom tools (tools/) | ✅ |
| 2 shared skills (skills/) | ✅ |
| CLI entry point | ✅ |
| CLI config overrides | ✅ |
| README | ✅ |
| MIT License | ✅ |
| example_runs.md | ✅ |

## Phase 6 — OWASP Hardening and Observability ✅

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| Memory poisoning defence | ✅ (2) | ✅ | ✅ (1) |
| Cascading depth limit | ✅ (2) | ✅ | ✅ (1) |
| Structured traces (JSONL) | ✅ (4) | ✅ | ✅ (1) |
| Context-loaded event | ⏭️ N/A | ✅ | ✅ (via traces) |

### Quality Gates
- ruff: ✅ All checks passed
- mypy --strict: ✅ No issues (32 files)
- radon cc --min C: ✅ 1 D-rated function (acceptable — Anthropic message translation)
- Tests: ✅ 296 total (240 unit + 56 integration)
- Integration mock check: ✅ Zero mocks in tests/integration/

## Phase 7 — Streaming and Extended Thinking ✅

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| Anthropic streaming + thinking | ✅ (25) | ✅ | ✅ (2) |
| OpenAI-modern streaming (Responses API) | ✅ (28) | ✅ | 🟡 written, blocked on account credits |
| LoopCallbacks on_delta/on_thinking_delta | ✅ | ✅ | ✅ (via providers) |
| stream/show_thinking config + CLI flags | ✅ | ✅ | ⏭️ N/A |
| Session persistence of thinking blocks | ✅ | ✅ | ⏭️ N/A |

### Quality Gates
- ruff: ✅ All checks passed
- mypy --strict: ✅ No issues (71 files)
- radon cc --min D: ✅ same 1 accepted D as before, no regression
- Tests: 326 unit passed (2 pre-existing unrelated failures excluded), 56 integration passed / 6 failed (OpenAI `insufficient_quota`, account issue not code)

## Phase 8 — Evaluation Framework (`eval/`) 🟡 In Progress

| Component | Unit Tests | Code | Integration Tests |
|-----------|-----------|------|-------------------|
| eval/types.py | ✅ (7) | ✅ | ⏭️ N/A |
| Budget/PreparedRuntime additions | ✅ (3) | ✅ | ⏭️ N/A |
| eval/storage.py | ✅ (5) | ✅ | ⏭️ N/A |
| eval/cases.py | ✅ (5) | ✅ | ⏭️ N/A |
| eval/graders/code (+ discovery) | ✅ (11) | ✅ | ⏭️ N/A |
| eval/graders/model.py | ✅ (4) | ✅ | ⏭️ N/A |
| eval/runner.py | ✅ (12) | ✅ | ❌ |
| eval/report.py | ✅ (13) | ✅ | ⏭️ N/A |
| eval/cli.py | ✅ (9) | ✅ | ⏭️ N/A |
| Column-matcher capstone suite | ⏭️ N/A | ✅ | ✅ (1, real API, H0 + H4 cells) |

### Environment fix (2026-08-03)

The capstone's first real run failed — not a code bug, but a pre-existing
`expat` C-extension mismatch on the Python 3.14.5 Homebrew bottle (linked
against macOS's system `libexpat`, missing a symbol `pyexpat` expected —
macOS 26.2's bundled libexpat hasn't caught up). This broke `openpyxl`/
`pandas.read_excel` entirely, which is why `test_value_overlap.py` and part
of `test_profile_data.py` were already failing/excluded all session before
this was even diagnosed. **Fix:** recreated `.venv` against `python@3.13`
(already installed via Homebrew, confirmed working `pyexpat`) — old venv
preserved at `.venv-py314-backup` pending cleanup. Reinstalled via
`pip install -e ".[dev]"` plus `pandas`/`openpyxl`/`pandas-stubs`. This
picked up newer unpinned versions of several deps (anthropic 0.89→0.120,
openai 2.30→2.52, mypy 1.20→2.3, pytest/ruff/rich bumped) — verified none of
this broke anything already built. One follow-on issue: numpy's latest
release (2.5.1) ships stubs using Python 3.12+ `type` statement syntax,
which fails mypy's `python_version = "3.11"` target (`pyproject.toml`) —
pinned `numpy==2.4.4` (previously-working version) to resolve; unrelated to
the Python 3.13 switch itself.

**Verified on the fixed environment:**
- `.venv/bin/pytest tests/unit -q` → `428 passed` (no exclusions needed —
  `test_value_overlap.py`/`test_profile_data.py` pass now too).
- `.venv/bin/ruff check agent_harness eval tests` → `All checks passed!`
- `env MYPYPATH=. .venv/bin/mypy --strict --explicit-package-bases agent_harness eval tests` → `Success: no issues found in 92 source files`
- `.venv/bin/pytest tests/integration -q` → `57 passed, 7 failed` — all 7
  failures are OpenAI `insufficient_quota` (account credits), unrelated.
  Every Anthropic-backed test passed, including the new capstone.

### Quality Gates (core eval/ package)
- ruff: ✅ All checks passed
- mypy --strict: ✅ No issues (92 files)
- radon cc --min D: ✅ same 1 pre-existing accepted D, no new D/worse (`discover_code_graders`/`summarize` both C, matching `discover_tools`'s own C rating)
- Tests: ✅ 428 unit passed, 57 integration passed (7 OpenAI-credit failures excluded, unrelated)
