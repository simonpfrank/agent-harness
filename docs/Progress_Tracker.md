## Last Session (2026-08-10, plan critique + human-in-the-loop refinement)
**Status:** Ready for Next Phase
**Working on:** Resumed a session that stopped mid-verification. Code and tests for the "Plan critique + human-in-the-loop refinement" roadmap item (plan at `~/.claude/plans/abstract-doodling-wren.md`) were already fully written against the plan's design — `types.py` (`OnPlanApproval`, `LoopCallbacks.on_plan_approval`), `loops/plan_execute.py` (bounded critique/refine round, approval gate), `runtime.py` (`plan_prompt_fn` threading, `_on_plan_approval` wrapper with tracing), `cli.py` (`_plan_prompt` using the `Text`-wrapping markup-safety pattern) — plus the full test matrix the plan called for (`test_plan_execute.py::TestPlanCritique`/`TestPlanApprovalGate`, `test_runtime.py` plan-approval wiring tests, `test_cli.py::_plan_prompt` markup tests). What hadn't run yet was verification.
**Next step:** Done and verified. Found and fixed the actual reason things had stopped: `mypy --strict` failed with 4 errors in `test_plan_execute.py` — `Message.content` is `str | None`, and four assertions did a bare `"x" in m.content` / `in step_messages[0]` without narrowing. Fixed by building `step_messages` from `m.content or ""` instead of `m.content`. Re-ran full verification: `pytest tests/unit -q` → 507 passed; ruff clean; mypy --strict clean (83 files); radon shows no new D-or-worse on the three touched files. Manual real-run verification (plan's step 3): `agents/hello --loop plan_execute` against the live Anthropic API — critique round fired and approved the plan without revision, approval prompt correctly rendered step text containing brackets/backticks via `Text` (no markup corruption), rejecting with `n` blocked all step execution — confirmed via trace log (`plan_approval` event, `approved: false`, no subsequent `react_run` steps). `docs/roadmap.md` updated: item moved from "Plausible Future Capabilities" to "Done".
**Notes:** Also found two pre-existing environment issues while doing the manual verification, unrelated to this change, not fixed (out of scope): `python -m agent_harness.cli` produces zero output for any invocation (including `--help`) because `cli.py` has no `if __name__ == "__main__": main()` guard; the installed `agent-harness` console script fails with `ModuleNotFoundError: No module named 'agent_harness'` because its shebang (`.venv/bin/python3.13`) is a symlink to the Homebrew system Python rather than resolving inside the venv. Worked around both by calling `main()` directly via `python -c` for the manual verification run. Flagging for a future session — not blocking, since normal test/CI invocation doesn't go through either path.

---

## Last Session (2026-08-10, model registry consolidation)
**Status:** Ready for Next Phase
**Working on:** Consolidated scattered per-model metadata into one registry (`agent_harness/models.py::MODEL_REGISTRY`), replacing three separately-maintained tables — `budget.py::COST_TABLE`, `context.py::_CONTEXT_LIMITS`, `openai_provider.py::_SUPPORTED_RESPONSE_MODELS`/`_OLDER_GPT5_DEFAULT_MINIMAL_REASONING` — plus hand-duplicated model lists in tests. Motivated by a real, demonstrated bug: `COST_TABLE` had a priced entry for `("openai", "o4-mini")` while `openai_provider.py` hard-rejected all o1/o3/o4 models. Traced via git history: o4-mini support was genuinely built and validated in April (`89dc618`, real H1p3 experiment runs), then silently dropped when the Responses API split landed (`61d32d3`) — nobody removed the now-dead `COST_TABLE` entry. One scattered source of truth couldn't prevent that drift; a single `ModelSpec` per `(provider, model)` — cost and context together — makes a cost-only or context-only entry structurally impossible going forward.

**o-series (o1/o3/o4) decision, made explicitly with the user**: stays completely dropped, no registry entries, no quirk-handling code (the April `max_completion_tokens`/reasoning-param handling was already gone from the codebase, nothing dormant to preserve) — but the explicit `_EXCLUDED_MODEL_PREFIXES` rejection stays, so an o-series model config fails with a clear error rather than a confusing raw API failure three layers down.

**A second simplification fell out of removing the allowlist concept**: `_SUPPORTED_RESPONSE_MODELS` was never real per-model routing data — the only genuine routing signal is whether `base_url` is set (hosted OpenAI vs. an OpenAI-compatible backend like LM Studio). The allowlist was purely a redundant "have we decided to support this" gate — redundant because the agent's own `config.yaml` already decides which model gets used. Dropping it simplified `_response_endpoint_for_model` from three cases to two, and fixed all 10 of `test_provider_openai.py`'s failing tests as a side effect (they used `gpt-4o`/`gpt-4o-mini` as example models, which the user's earlier in-progress trim of the allowlist had excluded).

One real signal preserved rather than guessed: the user's own edit to `test_context.py` (asserting `gpt-5.6-luna`'s context limit as `400_000`, changed from a prior `gpt-5.4-mini` assertion) was honored as intent rather than papered over with a placeholder default — `gpt-5.6-luna` got a real `400_000` entry, not the "unconfirmed" 128k fallback used for its two siblings (`gpt-5.6-terra`/`gpt-5.6-sol`, no equivalent signal for those).

`agents/agent_budgets/instructions.md` updated to point its cross-reference step at the one file (`models.py::MODEL_REGISTRY`) instead of three, with an explicit note that o-series absence is deliberate, not a gap to flag.

Verified: `pytest tests/unit -q` → 492 passed (up from 458, all `test_provider_openai.py` failures now fixed); ruff clean; `mypy --strict` clean across 34 files; radon shows no D-or-worse. Manual: confirmed `o4-mini`/`o1-pro` still raise a clear `ValueError`; real end-to-end run of `gpt-4o-mini` (previously blocked) succeeded with correct cost tracking (`$0.0003/$0.10`).

---

## Prior work this session: two fixes, both from real user reports while using `agent_budgets`.

1. **CLI REPL empty-input crash** — `cli.py:182-188` sent bare-Enter input straight to the Anthropic API as `Message(role="user", content="")`, which the API rejects with an unhandled `400` traceback. Fixed: empty/whitespace-only input now re-prompts, same shape as the existing `exit`/`quit` special-case. TDD: failing test first (`test_repl_mode_skips_empty_input`), then fixed.

2. **Rich markup corruption bug** — `Console.input()`/`console.print()` parse `[...]` as style tags by default. The permission prompt's own hint text (`[o]nce / allow for [s]ession / ...`) was self-corrupting (user-reported screenshot showed the garbled output). Investigation found the same vulnerability class in `display.py` (`show_tool_call`, `show_tool_result`, `show_delta`, `show_thinking_delta`, `show_budget`) — higher-likelihood to actually fire there since `web_fetch`'s markdown output routinely contains `[link](url)` syntax and `edit_file`/`content_search` args routinely contain bracket-bearing code. User confirmed fixing the full scope, not just the reported prompt. Fix: wrap all dynamic/bracket-bearing content in `rich.text.Text(...)` (structurally immune to markup parsing regardless of the `markup` flag, and composable so static styling + dynamic content can still share one line); `markup=False` on the two now-fully-static input hint strings. TDD throughout, covered with real-content assertions (not just "no crash") via a `Console(record=True)` recorder pattern in `test_display.py`.

3. **`list_provider_models` tool + `agent_budgets` scope fix** — user's design critique: scoping `agent_budgets` to the harness's own "supported models" lists (`COST_TABLE`, `_CONTEXT_LIMITS`, `_SUPPORTED_RESPONSE_MODELS`) repeats the exact bug the provider-registry fix solved one layer up — those lists are exactly what might be incomplete, so an agent that scopes from them can never discover a model missing from all three. Confirmed both Anthropic and OpenAI SDKs expose real `models.list()` endpoints. Built `list_provider_models(provider: str) -> str` in `tools.py` (validates against the providers registry, calls the vendor SDK directly, TDD'd, wired into `network_exfiltration_blocker`). Explicitly confirmed with the user that this does **not** touch `_SUPPORTED_RESPONSE_MODELS` — that stays a hard runtime compatibility gate (`openai_provider.py`'s Responses-API routing), a different concern from "does this model currently exist at the vendor." `agent_budgets`'s `instructions.md`/`config.yaml` updated to call `list_provider_models` as the real scope source, with `content_search` now used only for the internal cross-table consistency check, not for scoping. Verified with a real run: correctly filtered noisy vendor output (embeddings/audio/image excluded) to mainline chat models, and surfaced genuine gaps invisible to the old approach (`gpt-4.1`, `gpt-5`, several current Claude models — none of which appear anywhere in this codebase, so `content_search` alone could never have found them). $0.0137 of $0.30 budget.

Tests: 472 unit passed, ruff/mypy --strict clean, 3 new real (zero-mock) integration tests against live Anthropic/OpenAI APIs (`TestListProviderModelsReal`), no mocks in `tests/integration/` (verified via grep gate check).

4. **`agent_budgets` REPL crash — dangling `tool_use` on budget exhaustion.** Real user report: agent hit its turn/cost limit mid tool-call ("Turn 15/15"), then a follow-up REPL prompt crashed with `anthropic.BadRequestError: tool_use ids were found without tool_result blocks`. Root cause in `loops/react.py::run`: the `on_budget` break happened right after `messages.append(response.message)`, *before* the turn's pending tool calls were executed — so a response with `stop_reason == "tool_use"` that also tripped the budget check left its `tool_use` block permanently unresolved in the message list, which is invalid for the next API call. Fix: defer the budget-exceeded break until *after* the turn's tool calls are resolved into `tool_result` messages (the budget check itself, `budget.record()`, still runs once per turn as before — only the `break` timing moved). Root cause found by updating an existing test (`test_on_budget_stops_loop` in `test_react_loop.py`) that only asserted `chat_fn.call_count`, never checked whether the pending tool call got resolved — added `test_on_budget_still_resolves_pending_tool_call` to lock in the correct behavior.

5. **Silent budget-exhaustion stop.** Related report: when the agent stops because it hit `max_turns`/`max_cost`, there was no clear signal distinguishing that from a normal per-turn budget status line — user only saw the same `"Turn N/M | $X.XX"` text every turn, exceeded or not. Fixed in `runtime.py::_make_callbacks`'s `on_budget`: when `budget.record()` returns exceeded, the shown line now reads `"...— stopping (budget limit reached, task may be incomplete)"`.

Both verified end-to-end with a real run (not just unit tests): `agents/hello --max-turns 1` forced into a multi-tool-call turn that exceeds budget mid-turn, followed by a second REPL prompt — confirmed the stopping notice appears, the second prompt runs cleanly with no crash, exit code 0.

Tests (this batch): 475 unit passed, ruff/mypy --strict clean, radon shows `react.py::run` at C (was previously lower; acceptable — project's own bar is "no D or worse").

6. **React loop turn/budget awareness** (roadmap item, added 2026-04-09, now resolved) — planned properly via plan mode rather than jumping straight to code, since it touched loop/callback/session-persistence architecture. Codebase survey confirmed react.py is the only loop with a genuine per-turn budget concept (others reuse `max_turns` for a different unit, or delegate to a nested `react_run`). The literal roadmap wording ("inject into the system prompt") would have been a real bug: `init_messages()` only rebuilds the system prompt when the message list is empty, so mutating the canonical `messages[0]` in place would bake a stale "Turn 8/10" note into any resumed session forever. Fix: `Budget.status_note()` (new method, TDD'd) computes a "You have N turn(s) remaining[, Estimated $X remaining]" line; wired through a new `LoopCallbacks.get_budget_status` field into `runtime.py::_make_callbacks`; `loops/react.py::_with_budget_note` builds a **disposable per-call overlay** (`call_messages`) each turn and passes that to `chat_fn`, while the canonical, session-persisted `messages` list is never touched. Confirmed both Anthropic and OpenAI provider converters extract the system message the same way regardless of source, so this works uniformly with no per-provider special-casing. Verified live: the note correctly decrements turn-by-turn in a real run (`--verbose` debug logs), and a saved session's system message was directly inspected and confirmed to carry no injected note. `docs/roadmap.md` updated, item moved to Done.

**Unrelated finding, not touched**: `agent_harness/providers/openai_provider.py` has separate uncommitted changes on disk (not made by me) that narrow `_SUPPORTED_RESPONSE_MODELS` and cause 10 pre-existing test failures in `test_provider_openai.py`. Flagged to the user and confirmed intentional/in-progress — left untouched, out of scope for this work.

## Last Session (2026-08-06)
**Status:** Ready for Next Phase
**Working on:** Four new tools (`web_fetch`, `edit_file`, `web_search` via Tavily, `content_search`) plus a new `agent_budgets` example agent that keeps `budget.py::COST_TABLE` honest against real published pricing. Plan at `/Users/simonfrank/.claude/plans/abstract-doodling-wren.md`. Scope corrected mid-plan: provider/model scope for `agent_budgets` comes from `agent_harness/providers/__init__.py`'s registry, not `COST_TABLE` itself (the table being checked can't also be the source of truth for what to check) — this exact design decision paid off in the real verification run below.
**Next step:** Done and verified end-to-end with a real run. Nothing left mid-build. `docs/features.md`/`docs/roadmap.md` updated to match.
**Notes:** Swapped `beautifulsoup4` for `trafilatura` mid-build (content-extraction, not just HTML->markdown reformatting — discards nav/ads/boilerplate). Verified actively maintained (release 2026-07-31) despite a 2019 first release, before committing to it. Real dependency cost: pulls in 8 packages including `lxml` (compiled C-extension) — flagged transparently, proceeded anyway since the maintenance/functionality case held up. `pyproject.toml` now declares `httpx`+`trafilatura` directly. `web_fetch`/`web_search` both wired into `network_exfiltration_blocker`'s `_has_network_intent` (previously only inspected `run_command`/`execute_code`) — verified via failing-test-first that skipping this would have silently bypassed the domain-approval safety net. `TAVILY_API_KEY` already present in `.env`, confirmed via a real (not skipped) integration test against the live Tavily API.

**Real end-to-end verification run (2026-08-06)** — ran `agent_budgets` for real against live Anthropic/OpenAI/Tavily. Confirmed working exactly as designed: scope came from the providers registry (agent explicitly checked both `anthropic` and `openai`, not just what happened to already be in `COST_TABLE`); the cross-table `content_search` check caught the *exact* known `o4-mini`/`_CONTEXT_LIMITS` gap flagged earlier this session; real pricing pages were fetched and compared, surfacing genuine drift (Anthropic's current model lineup — Sonnet 5/Opus 5 — vs. the codebase's stale `claude-*-4-6`/`4-5-20251001` identifiers); two `edit_file` calls correctly paused for human approval (`always_ask` in config), both denied in this run, and `git diff` on `budget.py`/`context.py` confirmed **zero actual file changes** — the deny genuinely blocked the write, not just logged it. The agent also correctly *declined* to propose a fix for the ambiguous Opus case, explaining that it involved a model-version policy decision beyond its scope — matches the "don't guess" instruction directly. Ran within budget: 10/15 turns, $0.13 of $0.30. No pricing fixes were actually applied to the repo — that's a deliberate human decision for a future session, not an oversight.

Tests: 453 unit passed, ruff/mypy --strict clean, no new radon D-or-worse, 3 new real (zero-mock) integration tests (`edit_file`, `web_fetch` via local HTTP server, `web_search` via live Tavily API) all passing.

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
