# Streaming, Parallel Agents & API Layer — Roadmap

**Status:** Active roadmap design
**Parent roadmap item:** `Streaming / Parallel / Async epic` in `docs/roadmap.md`

Purpose: map where parallelism lives, where streaming lives, where async genuinely pays off, and where a future API layer slots in — all while keeping the harness simple.

## Context

The harness today is fully synchronous, single-threaded. `ChatFn` returns a complete `Response`; loops mutate a shared message list in place; `run_agent` tool calls a sub-agent and blocks. Fine for single-agent experiments. Three connected pressures are pushing on it:

1. **Streaming** — silent 30s waits in the REPL; no way to see a slow model (e.g. Qwen3-4B thinking) make progress; no abort mid-generation; no progressive tool dispatch.
2. **Parallelism** — not just for speed. With a free local model, parallel enables *different outcomes*: fan out narrow-focus agents, let a foundation model adjudicate. Also useful at work where cloud inference is on someone else's budget.
3. **API layer (future)** — a FastAPI surface would let a separate UI project consume the harness. Inescapably async at its boundary.

Key files: `agent_harness/providers/anthropic.py`, `openai_provider.py` (both blocking), `agent_harness/loops/*.py` (all sync, mutate messages list), `agent_harness/routing.py` (`run_agent`, `handoff_agent`, global `_call_depth`), `agent_harness/tools.py` (sync tool registry), `agent_harness/cli.py`.

---

## The organising idea: hybrid local + foundation

The pattern worth building around:

- **Workers:** cheap local model (4B MLX, thinking or vision variants). Narrow context, focused task, run many in parallel. Cost ~zero.
- **Adjudicator / reducer:** foundation model. Sees only the workers' outputs, not their raw inputs. Does judgement, synthesis, final selection.

This keeps cloud costs low, uses parallelism for outcomes (not just speed), and is the most honest justification for the refactor work below. Every design decision that follows should ask: *does this make the worker-adjudicator pattern cleaner?*

---

## Part 1 — Where streaming lives

### Levels

- **L1 — Provider boundary (Anthropic/OpenAI):** swap `messages.create()` for `messages.stream()`. This is where text deltas originate.
- **L2 — Loop layer:** decide whether to buffer deltas or forward them.
- **L3 — Callback / sink:** where deltas are displayed (CLI) or published (future SSE endpoint).

### Options

**A. Stdout-only streaming (L1 + L3, L2 untouched)**
- Provider emits text chunks via a new `on_text_chunk(agent_id, chunk)` callback.
- Still returns a complete `Response` at the end — loops don't change.
- CLI prints as chunks arrive; in parallel runs, prefix with `agent_id`.
- **Scope:** ~1 day. Pure UX win for CLI + Qwen-thinking visibility.

**B. Event-stream ChatFn (L1 + L2 rework)**
- `ChatFn` returns `Iterator[ChatEvent]`: `TextDelta | ToolCallStart | ToolCallDelta | ToolCallEnd | UsageUpdate | Done(Response)`.
- Loops consume the iterator. This is the proper seam for an SSE API endpoint — just forward events.
- Breaking change to `ChatFn`; loops adapted one at a time.

**C. Speculative tool dispatch (requires B)**
- Dispatch tools as soon as `ToolCallEnd` fires, even while the model keeps streaming. Deferred — premature until Phases 1–2 reveal it matters.

### Thinking tokens
- **CLI:** off by default. Noise. (Exhibit A: Qwen3-4B spending 30s tying itself in knots over strawberries.)
- **API / UI:** include as a separate event type (`ThinkingDelta`). Frontend collapses by default, expands for debugging. Easy given event-stream (B).

---

## Part 2 — Where parallelism lives

### Levels

- **LP1 — Inside a single agent's turn:** parallel tool calls within one response. Orthogonal to multi-agent work. Out of scope for now.
- **LP2 — Across sub-agent calls:** orchestrator fans out to N workers. This is the big one. Enables the hybrid pattern.
- **LP3 — Across top-level sessions:** multiple independent users/sessions running simultaneously. Only relevant once the API layer exists.

### Options

**D. `run_agents_parallel(tasks)` tool (LP2)**
- New tool next to `run_agent`. Takes N `(agent_name, message)` pairs, runs via `ThreadPoolExecutor`, returns results in order.
- Each sub-agent gets its own isolated context (own message list, own budget, own memory scope).
- Additive — existing `run_agent` stays. Orchestrator agents opt in.
- Required plumbing: `_call_depth` → `contextvars.ContextVar` so threads don't collide; per-sub-agent `RunContext` for memory_dir/tool_timeout.

**E. Per-agent RunContext (enables D cleanly, required for LP3)**
- Dataclass: call_depth, budget, memory_dir, tool_timeout, callbacks, message list, agent_id.
- Thread through loops and tool calls; retire module globals.
- Unlocks LP2 cleanly and LP3 later.

**G. Orchestration patterns (once D/E exist)**
Cheap to build on top:
- **Parallel fan-out + adjudicator** — the hybrid pattern. N local workers, cloud model picks. Applicable to column-matching, extraction, classification.
- **Best-of-N** — same prompt, different temperatures/models, scorer picks best.
- **Race / first-wins** — cheap + expensive model together, first correct wins.
- **Map-reduce** — split doc → N workers → reducer.
- **Parallel debate** — N answer simultaneously, judge picks.
- **Router** — cheap classifier picks specialist, in parallel with pre-warming.
- **Planner + worker pool** — dynamic task list, bounded workers drain queue. More powerful, less predictable, needs budget per branch. Defer until static fan-out validates.

### CLI output for parallel agents
Simple answer: prefix every line with `[agent_id]` and a colour. No panes, no curses, no rabbit hole. Two hours of work.

For richer views (live dashboard, per-agent panels): push to the UI side, don't build it into the CLI.

---

## Part 3 — Where async actually pays off

"Everyone builds in async by default" is a weak reason. Let's separate where it genuinely helps from where it's refactor pain:

| Layer | Async genuinely useful? | Why |
|---|---|---|
| FastAPI endpoints | **Yes, mandatory** | FastAPI *is* async. Non-negotiable if we add the API. |
| SSE streaming to client | **Yes** | Native fit. Forwarding event-stream events over SSE is trivial async. |
| Parallel agent fan-out | **No strong need** | ThreadPoolExecutor works fine. Inference is I/O-bound waiting on an HTTP call; threads release the GIL. Async would be cleaner but not faster. |
| Provider calls (internal) | **Neutral** | Anthropic/OpenAI SDKs offer async clients. If we go async at the boundary, using them internally is consistent. If not, sync is fine. |
| Loops | **No** | Nothing benefits. Would just be infectious async colour. |
| Tools (local code, subprocess) | **No** | Tools are often CPU or blocking I/O. Wrapping them in `run_in_executor` is noise. |

### Recommendation
**Async at the boundary, sync in the core.** When the FastAPI layer arrives:
- Endpoints are `async def`, serve SSE.
- They drive the sync core via `asyncio.to_thread(run_agent, …)`.
- Core stays sync and readable.

This preserves the "readable in an afternoon" property. If we later find bottlenecks (we probably won't — LLM calls dwarf everything), revisit per-provider async clients. **Don't pre-emptively paint the whole codebase async.**

---

## Part 4 — API layer (future, captured not built)

Deferred but on the roadmap so we don't design it into a corner.

**Shape when we build it:**
- FastAPI app with one SSE endpoint: `POST /sessions/{id}/messages` → stream of `ChatEvent`s.
- Session list/get/delete endpoints backed by existing `session.py` (swap JSON files for SQLite when multi-session load matters).
- Auth: deferred. Local-only first, add bearer token later.
- Endpoints are async; internals sync via `asyncio.to_thread`.
- **UI lives in a separate repo.** This repo exposes an API, nothing more.

**Prerequisites already in phased plan below:**
- Event-stream ChatFn (B) — so SSE is a straight forward-the-events job.
- RunContext (E) — so parallel sessions don't collide.

**Not prerequisite, safely deferred:**
- Auth, persistence upgrade, rate limiting, multi-tenancy.

**Another concrete motivation, added 2026-08-03 (from RAG design discussion):** a
browser-based chat client is the natural home for rendering retrieved images
properly — no terminal-capability guessing, no block-art fidelity ceiling like
the CLI's `rich-pixels` fallback has. Fits the existing event-seam design
without change: "here's a retrieved image" is just another event type a
future SSE layer forwards, same as `TextDelta`/`ThinkingDelta` — CLI keeps
`rich-pixels` as its cheap fallback, both consumers sit behind the same
callback/event seam rather than needing separate plumbing. Not a reason to
build the API layer now — just another data point for when it does get built.

---

## Part 5 — Crazy end (explicitly parked)

- Agent mesh with pub/sub bus — overkill.
- Distributed workers across processes — only if CPU-heavy tools become a bottleneck (pandas profiling at scale, maybe).
- Speculative execution — run likely-needed agent while user types.
- Live reflection interrupt — critic watches actor's stream, interrupts on error.

Revisit if and when something concrete demands them.

---

## Phased roadmap

### Phase 1 — Streaming + parallel, minimum viable (days)
- Streaming option **A**: `on_text_chunk(agent_id, chunk)` callback. CLI prints progressively with agent prefix.
- **D**: `run_agents_parallel` tool via `ThreadPoolExecutor`.
- `_call_depth` → `contextvars`.
- Prefix+colour CLI output for multi-agent runs.
- Files touched: `providers/anthropic.py`, `providers/openai_provider.py`, `tools.py` (new tool), `routing.py`, `cli.py` (display callbacks).

### Phase 2 — Event stream + RunContext (week-ish)
- **E**: introduce `RunContext`; thread through loops and tools; retire module globals.
- **B**: upgrade `ChatFn` to event-stream. Loops adapted one at a time.
- Add `ThinkingDelta` event type (still suppressed in CLI by default).

### Phase 3 — Hybrid patterns as first-class loops/tools
- `fan_out_adjudicate(workers, adjudicator, task)` — the hybrid pattern.
- `best_of_n`, `race` as new loops or tools.
- Rebuild `debate` on parallel primitives.

### Phase 4 — FastAPI layer (when there's a reason)
- SSE endpoint forwarding event-stream events.
- Session CRUD.
- Async at boundary, sync core via `asyncio.to_thread`.
- UI stays in a separate repo.

### Explicitly deferred
- Full async core migration (F).
- Dynamic planner agents.
- Message bus (H).
- Speculative tool dispatch (C).
- Thinking-token UI polish (until UI exists).

---

## Outstanding decisions

1. **Phase 1 scope:** do you want stdout streaming and `run_agents_parallel` bundled, or land them separately?
   **Resolved (2026-08-03):** landed separately. Streaming (option A, callback-based) plus extended thinking shipped for the Anthropic provider; `run_agents_parallel`/`contextvars` work not started.
2. **Local adjudicator experiments:** which existing agent is the best testbed for the hybrid pattern? (Column-matcher is the obvious candidate but you flagged that's handled in the other session.)
3. **Thinking events in Phase 1:** include in the callback now (even if CLI hides them), or wait for Phase 2's event stream?
   **Resolved (2026-08-03):** included now, not deferred. `on_thinking_delta(agent_id, chunk)` exists on `LoopCallbacks` and is wired for the Anthropic provider; CLI still hides thinking by default (`show_thinking: false`), matching the "off by default, noise" stance above, but it's now a persisted per-agent config field rather than unavailable.
4. **Async migration stance:** confirm "async at boundary, sync core" is acceptable — we won't pre-emptively async the loops/providers.

## Phase 1 implementation notes (2026-08-03)

Delivered for the Anthropic provider only (OpenAI untouched; `validate_config`
rejects `stream`/`thinking` on any other provider):
- `Message` gained `thinking`/`thinking_blocks`; `LoopCallbacks` gained
  `on_delta`/`on_thinking_delta` with signature `(agent_id, chunk)` per this
  doc's L3 sink design (`agent_id` unused until parallel agents exist).
- `AgentConfig.stream` and `AgentConfig.show_thinking` are persisted
  `config.yaml` fields, with `--stream`/`--show-thinking` CLI overrides.
- `provider_kwargs.thinking: {budget_tokens: N}` enables extended thinking,
  independent of `stream` — validated (budget ≥1024, < max_tokens,
  incompatible with `temperature`/`top_p`) before the request goes out.
- `chat_fn` still returns a complete `Response` at the end — loops don't
  change shape, matching option A exactly. `on_response` skips the CLI's
  final markdown re-print when `stream` is true, since deltas already
  printed it live.
- Known gap, accepted deliberately: `with_retry` still wraps the whole
  streaming call, so a transient error after some deltas have printed can
  duplicate output on retry. Not fixed — revisit only if it proves painful.
- Full plan: `/Users/simonfrank/.claude/plans/abstract-doodling-wren.md`.

## Phase 1 follow-up: OpenAI-modern streaming (2026-08-03)

Extended option A to OpenAI's Responses API (the only endpoint hosted
"modern" models — `gpt-4o`, `gpt-4o-mini`, `gpt-5.x` — use; confirmed via SDK
introspection that `client.responses.stream()` has its own accumulator,
`get_final_response()`, same shape as Anthropic's). No reasoning/thinking
content extraction added — OpenAI reasoning models still only expose the
existing `reasoning_effort` input knob, no readable output content.

- `openai_provider.chat()` gained the same `stream`/`on_delta` kwargs as
  Anthropic, dispatching `response.output_text.delta` events.
- Chat Completions (the `base_url`/local-backend fallback) explicitly
  rejects `stream=True` with a clear `ValueError` — both at the provider
  boundary and in `runtime.validate_config` — rather than silently ignoring
  it or guessing at chunk reassembly for that endpoint.
- `validate_config`'s stream guard now allows `provider in ("anthropic",
  "openai")`, with an extra rejection when `openai` + `provider_kwargs.base_url`
  are combined.
- Unit-verified (28 provider tests + validate_config tests, all green;
  ruff/mypy/radon clean, no new D-or-worse complexity).
- **Not fully integration-verified**: the real-API OpenAI streaming test was
  written and run, but failed with `insufficient_quota` (OpenAI account has
  no credits) — a billing issue, not a code defect. The error was a
  retryable `api_error` (429), not `BadRequestError`, meaning the request
  reached OpenAI and was shaped correctly; it just couldn't complete. Revisit
  once the account has credits.
