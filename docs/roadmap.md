# Roadmap / Todo

Durable list of things we've identified but haven't done yet. One section per item, dated when added. Add rather than edit — keep the history, **except** the Priority Order list directly below, which is a living summary expected to be freely reordered/pruned each session, not append-only.

When an item ships, move it to the **Done** section at the bottom with a commit reference and the date.

---

## Priority Order

Ranked list of everything currently committed to build (drawn from `Near-term Improvements` and `Plausible Future Capabilities` below — `Ideas`/`Scoped out`/`Rejected` stay unranked, not commitments). Ranking logic: quick wins first, then dependency order within a track. See each item's own detail section for the *why*.

**Track A — Interface/access expansion** (multi-device, multi-task future — Echo/phone/Reachy, not just CLI): shipped — see "HTTP API server" in Done below.

**Track B — Single-task execution speed/quality:**
1. Parallel tool-call execution within a turn — shipped, see Done below.
2. Parallel sub-agent fan-out — still no concrete driver, stays deferred

**Shelved (2026-08-19), not in this ranking:** Adaptive re-planning — a full design exists (see Ideas below) but was pulled *during* plan mode when a direct check found zero example agents actually use `loop: plan_execute` yet. Investing in adaptation logic for an unused code path is exactly the "no code-level tweaks without hard evidence" mistake this project already corrected once (the prompt-override-file retraction). Next step before this returns to Priority Order: build and actually run a real `plan_execute`-based agent, see if the static-plan limitation genuinely bites.

**Deprioritized, no pressing need (2026-08-15):** CLI REPL single-keypress prompts, CLI REPL `#` type-ahead tool invocation — left scoped below for whenever a real need surfaces. `!` prefix for inline shell stays as an optional quick win, not urgent.

---

## Near-term Improvements

### CLI REPL: single-keypress prompt responses, no Enter required (added 2026-08-10)

**What:** Permission/domain prompts currently need Enter after the
letter. User asked whether a single keypress could answer immediately.

**Why:** Real feature, not a tweak — flagged as such rather than
freehanded. `Console.input()`/`input()` are line-buffered by design;
true no-Enter response means bypassing them with raw terminal mode,
which is platform-specific (`termios`/`tty` on macOS/Linux, `msvcrt` on
Windows). Needs a careful fallback for non-interactive stdin — piped
input into these exact prompts is used throughout this project's own
test suite and manual verification workflow, so raw-tty reading can't be
the only path. Also changes how `_permission_prompt`/`_domain_prompt`
get unit-tested (currently mocks `_console.input` directly). Worth
planning properly before implementing, not a quick patch.

**Status note (2026-08-15):** deprioritized — no pressing need, letter+Enter is fine for now. Left scoped here for whenever a real driver surfaces.

---

### CLI REPL: `!` prefix for inline shell commands (added 2026-08-13)

**What:** A REPL line starting with `!` runs as a plain shell command
locally (print the output) instead of being sent to the agent as a
prompt — same convention already used by this very Claude Code session's
own `!` mechanism for running a command directly.

**Why:** User-requested, small and self-contained — no new input
infrastructure needed, since it's still one line-buffered `Console.input()`
call, just a prefix check before deciding whether to hand the line to
`runtime.run_messages()` or to `run_command`/`subprocess` directly.

**Scope in roadmap terms:** CLI-only change, `cli.py`'s REPL loop. No
dependency on the `#`-tool-invocation item below — genuinely separable,
can be built alone.

### CLI REPL: `#` prefix for direct tool invocation, with live type-ahead filtering (added 2026-08-13)

**What:** A REPL line starting with `#` invokes a tool directly — bypassing
the LLM for that turn — with a live-narrowing, fuzzy-filterable list of
available tools (built-in and MCP-discovered) as the user types, arrow-key
selectable.

**Why:** User-requested. Genuinely two different pieces of work bundled
under one ask, worth keeping separate when scoping/building:
1. **Bare `#toolname args`, no live filtering** (type the full line, hit
   Enter) — small, self-contained, no new input infrastructure. Parse the
   prefix, look up the tool in `runtime.tool_registry`, call it, print the
   result.
2. **Live type-ahead as `#` is typed** (list narrows in real time) — the
   genuinely hard part. `Console.input()` is line-buffered; a
   live-updating filter menu needs real keystroke-level input control,
   which is the *exact same* underlying gap already scoped in the
   "single-keypress prompt responses" item directly above (raw terminal
   mode, `termios`/`tty` vs `msvcrt`, non-interactive-stdin fallback for
   this project's own piped-input test/verification workflow). A library
   like `prompt_toolkit` is the natural fit for both — solves cross-platform
   raw input once and ships completion-menu widgets out of the box —
   rather than building two separate one-off raw-terminal solutions.
   **Recommendation, not yet decided: bundle this with the no-Enter-keypress
   item as one "REPL input upgrade" investment**, not two.

**Open design question, raised directly by the user rather than glossed
over:** how does `#toolname` prompt for arguments the user didn't supply?
A model calling a tool has the full conversation as context to infer
arguments from; a human typing `#read_file` at the prompt doesn't. The
harness already generates a JSON-Schema-shaped `input_schema` per tool
(`tools.py::generate_schema`, and MCP tools ship their own via
`mcp_client.py::McpManager.list_tools()`) — the natural answer is walking
that schema's `required` fields and prompting for each one not already
supplied on the `#toolname` line (same interactive-`Console.input()`
pattern as `_permission_prompt`/`_plan_prompt`), but this isn't designed
yet — genuinely open, not a detail to hand-wave past when this gets built.

**Scope in roadmap terms:** not designed yet. Depends on (or should be
bundled with) the no-Enter-keypress item for its live-filtering half;
the argument-prompting design above needs its own thought regardless of
which input mechanism is chosen.

**Status note (2026-08-15):** deprioritized — this was speculative ("being creative"), not a driven need. Left scoped here for whenever a real requirement surfaces.

---

## Plausible Future Capabilities

**Superseded by the `Priority Order` section at the top of this file (2026-08-15)** — the "build order" note below is kept as historical record of the sequencing decisions made along the way, not the current authoritative order.

**Build order (decided 2026-08-13, updated 2026-08-15 after multimodal shipped):**
1. ~~Step-level evidence for evals~~ — **delayed** before being designed;
   see its entry below for why (same "no real driving case yet" call as
   prompt caching).
2. ~~MCP client support~~ — **shipped 2026-08-13**, see Done below.
3. ~~Image handling / multimodal~~ — **shipped 2026-08-15** (built ahead of
   its original slot — decided 2026-08-13 to skip Parallel sub-agent
   fan-out and treat async/concurrency as its own future phase rather than
   a single-item priority, which moved multimodal up). See "Multimodal
   file handling" in Done below.
4. **Deferred to an "async phase"**, not scheduled as an individual item:
   Parallel sub-agent fan-out — real value but pushes concurrency into a
   deliberately synchronous core; still no concrete driving use case in
   this repo (`orchestrator` calls `run_agent` serially). Revisit once
   there's a real reason to take on concurrency as a project, not as a
   one-off feature.

Not part of the sequence: **API/async boundary** is a standing design constraint ("if an API is ever added, keep async at the boundary"), not a buildable task — it activates only if something else creates a reason for an external API; conceptually the same "async phase" bucket as parallel fan-out above. **Lazy tool schema loading** doesn't clear this file's own benefit-vs-complexity bar (see its entry below) and isn't scheduled.

### Parallel sub-agent fan-out (added 2026-04-16)

**Status:** Active roadmap design

**What:** Run multiple delegated agents in parallel, primarily for fan-out / adjudication workflows and execution-time improvements.

**Why:** This is the most plausible parallelism win for the harness. It may improve wall-clock time and unlock useful experimentation patterns without pushing concurrency into every part of the runtime.

**Scope in roadmap terms:** sub-agent fan-out first, not parallel tool calls inside a single turn.

**Deep-dive design:** `docs/streaming-plan.md`

**Note (2026-08-15):** reaffirmed as deferred — Track B #2, same track as
parallel tool-call execution (Track B #1, below/in the Scoped-out-of-MCP
backlog), separate from the interface-expansion track (shipped — see
"HTTP API server" in Done). Still no concrete driver.

### Evaluation framework (added 2026-04-16, shipped 2026-08-03)

Run agents against test cases and score quality. Shipped as the `eval/` package — test case definitions, pluggable code + model graders with a gate/signal split, JSONL storage, and a ranked leaderboard. Replaces the ad hoc `scripts/run_experiment.py` pattern; `scripts/score_run.py`'s comparison logic was reused, not rewritten, as the `column_match` grader. Design doc: `docs/eval_framework.md`. Deferred: extending it to benchmark external coding assistants (Claude Code, Codex CLI, Copilot) via a `Subject` abstraction — captured in that doc, not built.

### Lazy tool schema loading (added 2026-04-16)

Send a compact list of tool names and descriptions first, then load full schemas on demand only when the model chooses a tool.

**Note (2026-08-13):** re-examined this against real numbers and it's weaker
than it sounds. Measured schema size across every example agent: the
busiest (`column-matcher-reflective`, 8 tools) is ~435 tokens; the full
13-tool builtin set is ~900 — under a cent per turn on Haiku, dwarfed by
message-history growth. Bigger problem: it doesn't map onto how
Anthropic/OpenAI tool-calling actually works — the full JSON schema has to
be in the request for the model to emit valid structured arguments, so
"list names, fetch schema on demand" would need a fake round-trip
(`describe_tool` meta-tool, then the real call next turn) — an extra turn
of latency/cost on every tool call to save less than a cent. Doesn't clear
this file's own filter (benefit > added complexity). Prompt caching (below)
targets the same underlying waste — repeatedly-sent static content — without
the round-trip. Leaving this here rather than deleting since the history is
useful, but it shouldn't be picked up without a stronger case than this.

### Prompt caching (added 2026-08-13)

**Status:** confirmed for roadmap, deliberately delayed — revisit once
we're building more meaty agents (more tools, longer instructions,
longer multi-turn conversations) than the current example set.

**What:** mark the static parts of a request (system prompt, tool
schemas) as cacheable so repeated turns in the same conversation don't
re-bill the same tokens at full input rate. Anthropic-only in terms of
code changes — OpenAI's Chat Completions/Responses API caches
automatically above 1024 tokens, no client change needed there.

**Scope:** small — `anthropic.py::_to_anthropic_messages` (system prompt
becomes a content-block list with `cache_control: {"type": "ephemeral"}`),
`_to_anthropic_tools` (same marker on the last tool entry),
`types.py::Usage` (+`cache_creation_input_tokens`/`cache_read_input_tokens`,
parsed in `_to_response`), `models.py`/`budget.py` (cache read/write rates
per model — reads ~0.1x input rate, writes ~1.25x — `Budget.record()` uses
them instead of the flat input rate). ~100-150 lines across 4 files, one
sitting, plus a real two-call integration test.

**Why delayed, not built now:** checked real numbers before committing.
Anthropic's minimum cacheable block is 1024 tokens (2048 for Haiku).
Measured every example agent's system-prompt + tool-schema size — most
are nowhere close (`hello`: ~80 tokens instructions + ~300 tokens tools).
Only the two biggest, `agent_budgets` (~1250 tokens instructions) and
`column-matcher` (~1090), would trigger caching at all today. Cache
*writes* also cost 1.25x on the first call, so it only pays off across
multiple turns reusing the same static prefix (true for `react`/
`plan_execute`) — a one-shot single-turn agent would come out slightly
worse, not better. Build this once agents exist that actually clear the
1024-token floor and run enough turns to recoup the write premium.

### Step-level evidence for evals (added 2026-08-06)

**Status:** promoted from Ideas, not designed yet

**What:** Grade intermediate steps of a multi-step run, not just the final
response/output file — deterministic or model-graded per step — plus
latency/cost/token breakdown per step, so a failure can be attributed to
exactly where in a workflow it happened rather than just "the final answer
was wrong."

**Why:** `eval/report.py`'s current design only grades the final
`response_text`/`output_file` per run. For a multi-step loop (`plan_execute`,
`reflection`, `rewoo`), a wrong final answer doesn't say which step broke it.

**Scope in roadmap terms:** needs the runner to capture intermediate trace
events (not just the final `RunResult`), and the grader interface to accept
a step/stage identifier. Extend the existing `eval/` package's structures
rather than building a parallel system.

**Deep-dive design:** none yet — extend `docs/eval_framework.md` when scoped.

**Note (2026-08-13): delayed before being designed.** Started planning
this first per the build order above, then realized mid-plan that the
right call was to delay the *entire* item, not just its grader-facing
half — there are zero existing eval cases exercising a multi-step loop
(`plan_execute`/`reflection`/`rewoo`) to validate a design against; the
one real case (`eval/cases/column-matcher/pension-match.yaml`) runs plain
`react`. Same "no real driving case yet" call as prompt caching. Revisit
once a real multi-step eval case exists.

### Image handling — send and receive encoded images (added 2026-08-06)

**Status:** confirmed for roadmap

**What:** send images to the model as vision input (base64-encoded content
blocks), and handle images arriving through the pipeline via tool results
(e.g. a screenshot tool, or RAG image retrieval per `docs/rag-plan.md`) so
they can be round-tripped back into the model as vision input too. Flagging
the "receive" half is my reading of what was asked for — correct me if that
wasn't the intent.

**Why:** `Message.content` is `str | None` today — no image content-block
support anywhere in either provider (`_to_anthropic_messages`,
`_to_openai_messages`/`_to_openai_input`). This is the "vision" gap already
identified during the RAG design work — distinct from RAG's own
retrieval-side multimodal support (Chroma finding a similar image isn't the
same as the model being able to see it).

**Scope in roadmap terms:** real, multi-file work, not small — new
`Message` field(s) for image content, base64/MIME handling, and
provider-specific content-block construction on both providers. Already
flagged as the "genuinely major hassle" item during the RAG conversation,
as distinct from the cheap CLI-image-display piece.

**Superseded, shipped 2026-08-15:** requirements broadened from "images"
to "images, documents, and general file input/output" and fully specced
in `docs/multimodal-plan.md`, then built end to end. See "Multimodal
file handling" in Done below for the summary. This entry stays for
history; `docs/multimodal-plan.md` has the full PRD + spec.

### Budget-verification tooling + agent_budgets (added 2026-08-06, shipped 2026-08-06)

**What:** Four new tools — `edit_file` (targeted search-replace),
`web_fetch` (trafilatura-based content extraction), `web_search`
(Tavily-based), `content_search` (grep-equivalent) — plus a new example
agent, `agent_budgets`, that checks `budget.py::COST_TABLE` against real
published vendor pricing and proposes fixes for human review.

**Why:** `COST_TABLE` was verified earlier this session to be entirely
hand-maintained with zero update mechanism — an unlisted model silently
costs $0.00. Resolves "no targeted edit tool" and "no content search" from
"What a decent coding agent would need" (below) as a side effect, since
`agent_budgets` needed both to do its job.

**Real design correction during planning, not just scope:** the first
draft derived the agent's provider/model scope from `COST_TABLE` itself —
wrong, since the table being checked can't also define what to check.
Scope comes from `agent_harness/providers/__init__.py`'s registry instead.

**Verified in a real run** (see `docs/Progress_Tracker.md`, 2026-08-06):
correctly checked both `anthropic` and `openai`, caught the known
`o4-mini`/`_CONTEXT_LIMITS` cross-table gap, fetched real pricing, and two
proposed `edit_file` calls correctly paused for human approval — denied in
this run, confirmed via `git diff` that no file was actually changed.
Agent also declined to guess on an ambiguous case rather than force a fix.

**Deep-dive:** `docs/features.md` (Tools section), plan file history at
`/Users/simonfrank/.claude/plans/abstract-doodling-wren.md`.

---

## Scoped out of MCP client support — backlog

Deliberately cut during MCP client planning/build (2026-08-13), each with
the reason it was cut — recorded here rather than lost in a closed plan
file, so they have a durable home to come back to.

### MCP server support

The harness exposing its own tools/agents *as* an MCP server, for another
host (VS Code, another agent) to call into — the reverse direction of what
shipped. **Cut:** distinct, larger scope from "consume external servers as
tools." The package choice (`fastmcp-slim[client]`, upgradeable to full
`fastmcp`) was made specifically so this is a lower-cost follow-on later —
same importable API, install-only change, not a rebuild.

### HTTP/SSE transport for remote MCP servers

MCP client support only implemented stdio (local subprocess) servers.
**Cut:** no concrete remote server to validate against yet, and real auth
(bearer token at minimum, OAuth 2.1 per spec for full compliance) can't be
meaningfully built or tested speculatively — same discipline as delaying
prompt caching/step-evidence until there's a real driving case.

### Run-abort on unsurvivable tool failure

MCP client support ships a narrower version of this: `McpManager` tracks
per-server connection health and fails fast (no doomed retry) once a
server's transport connection is known dead, but this stays contained
inside `mcp_client.py` — a normal tool-error message fed back through the
existing `execute_tool()` path, same as any other tool error. **Cut (the
bigger version):** a genuine "abort the whole run" signal would need new
plumbing through `LoopCallbacks`/every loop, not just the MCP client —
bigger, cross-cutting change not needed to solve the actual problem
(wasting turns retrying a dead server).

---

## Ideas

These are captured so they are not lost. They are not commitments.

### Adaptive re-planning (design settled 2026-08-15, shelved 2026-08-19)

**Shelved mid-plan-mode, not abandoned — a real design exists, just not
enough evidence yet to justify building it.** `plan_execute.py` plans
once, does a bounded pre-execution critique/refine round on the plan
*text*, then commits — nothing re-plans mid-execution if a step reveals
the plan's premise was wrong. A full implementation plan was produced
(retry-wrapped step execution mirroring `ralph.py::_run_attempt`, a
3-outcome LLM-judged escalation classifier, a circuit breaker reusing the
existing plan-approval gate for hand-back) — but a direct check mid-plan
found **zero example agents in this project actually use
`loop: plan_execute`**. Building adaptation logic for a code path with no
real users would repeat the exact mistake this roadmap already caught and
reversed once (the prompt-override-file retraction for the thrashing
breaker) — "no code-level tweaks without hard evidence," just at a much
larger scale (six new functions, a full `plan_execute.py` execution-loop
restructure, cross-step circuit-breaker state). Caught by the user's own
instinct mid-session, verified rather than just accepted.

**Next step before this returns to Priority Order:** build and actually
run a real `plan_execute`-based agent for a task genuinely suited to
upfront step planning, and watch what happens. If the static-plan
limitation never bites, this was never needed — a correct outcome, not a
failure to revisit. If it does bite, there'll be real evidence to design
against instead of a prior-project anecdote.

**First real data point (2026-08-19), and it argues against building
this, not for it.** Built `agents/competitor-research` (`loop:
plan_execute`, same local LM Studio model as `agents/researcher`) and ran
it live: "compare Slack, Microsoft Teams, and Discord." Plan generation
produced exactly one step per competitor; critique approved immediately;
all 3 steps executed cleanly — no thrashing, no tool errors, no
escalation-worthy event of any kind — and the final summary was accurate
and properly sourced for all three. One genuinely interesting wrinkle:
mid-way through step 1, the model prematurely declared "I've completed
the research on all three" despite having only searched Slack — a
hallucinated early completion, not thrashing. It didn't derail anything,
because `plan_execute.py`'s Phase 2 loop doesn't read or trust that
self-report at all — it just executes the fixed step list regardless of
what any step's text claims. The rigidity this feature would relax turned
out to be a *strength* in this run, not a limitation — the same "don't
trust self-report, use structure instead" principle already behind
`completion_check` and the thrash guard, arrived at organically rather
than designed in. One real run isn't proof this is never needed, but it's
a genuine first data point, and it points toward "not yet," not "here's
the evidence to build against."

**Design, preserved for if/when real evidence justifies building it:**
- **Trigger**: not "any tool error" (that's normal react-loop
  self-correction) — only when a step shows *persistent* thrashing, i.e.
  the step-level thrashing breaker's `on_thrash_detected` fires more than
  once during one step's `react_run` call. Concretely wireable without
  any new signal from `react.py`/`common.py`: `plan_execute.py` can count
  firings by building a per-step `LoopCallbacks` wrapper
  (`dataclasses.replace(cb, on_thrash_detected=counting_wrapper)`) that
  delegates to the original callback so display/tracing still happens.
- **The escalation call needs three possible outputs, not one**: (a) no
  change, retry the step with a nudge (the common case); (b) swap this
  one step's approach, rest of the plan untouched (local fix); (c) a real
  structural revision affecting later steps too (rarer). Forcing a plan
  revision every time this fires would make the cure worse than the
  disease.
- **Revise minimally, not by full regeneration** — smaller diffs are
  lower-risk, and there's no way to *guarantee* a revision is better
  before it executes.
- **Circuit breaker**: escalating twice in a row *without an intervening
  step that converged cleanly* (not just "N total escalations") hands
  back to the human via the *existing* `cb.on_plan_approval` gate, not a
  new stop pathway — fails safe (stop with a clear message, don't loop
  forever) if no approval callback is wired, matching the initial
  plan-approval gate's own inert-by-default convention.
- **Structural fix required first**: today `plan_execute.py` has no
  retry/success concept at all — once `react_run` returns for a step, the
  loop just moves on regardless of outcome. Needs a `ralph.py`-style
  bounded per-step retry wrapper before any escalation logic can sit on
  top of it.
- **Config-field precedent to follow when built**: `replan_escalation_threshold`
  (firings within one step before escalating, not the same as
  `thrash_threshold` which governs when the nudge itself fires) and
  `replan_circuit_breaker_threshold` (consecutive escalations before
  hand-back) — both `int` fields with sensible defaults, same low-friction
  pattern as `completion_check`/`thrash_threshold`, no hardcoded magic
  numbers.
- **Explicitly out of scope even if this gets built**: the idea of plan
  generation stating each step's *expected* result shape (so a
  successful-but-wrong tool result can be caught structurally, not just
  errors) is a separate, larger follow-on — it touches plan *generation*
  itself, not just execution, and deserves its own build cycle. Detecting
  a tool result that's factually wrong (vs. merely mismatched from what
  the plan expected) has no general solution without ground truth or a
  domain-specific check — be honest that's a fundamental limit, not a gap
  to promise away.

### Provider-tier strategy: cloud direct / OpenRouter / HF-hosted / local (added 2026-08-16)

**What:** Not yet a feature — a real, unresolved question the user flagged
explicitly needs thinking through before any of it gets designed: how the
harness should reason about (and possibly help choose between) four
genuinely different provider tiers — cloud-direct (Anthropic/OpenAI as
already built), OpenRouter, Hugging-Face-hosted inference, and local
(LM Studio/Ollama/llama.cpp). "Becoming a complex map of managing
providers per message levels" — the user's own framing, kept verbatim
since it names the actual concern precisely.

**Why now, not resolved now:** driven by real, current experience —
tuning a local model (LM Studio + qwen3) well enough that it doesn't
"waffle on" (burn hundreds of tokens reasoning in circles before ever
acting, observed for real this session) turns out to depend heavily on
which local runtime and settings are used, and that variability doesn't
exist the same way for cloud-direct providers at all. Explicit goal
named: get this right *before* pointing a Reachy Mini agent at a local
model, where a "waffling" failure mode is a much worse user experience
than in a CLI session.

**Real, verified research from this session, worth keeping rather than
re-deriving:**
- **Ollama** supports per-request `num_ctx` (context size) *and* a
  working per-request `think` level (boolean or low/medium/high/max,
  model-dependent) — confirmed via Ollama's own docs
  (`docs.ollama.com/capabilities/thinking`), genuinely more tunable
  per-request than LM Studio for exactly this use case.
- **llama.cpp server**'s `--ctx-size`/`-c` is a server-*launch* flag only
  (shared unified KV cache across parallel slots) — no per-request
  context control, and no confirmed per-request thinking-level toggle
  either (not confirmed absent, just not found).
- **LM Studio**: context is load-time only (`POST /api/v1/models/load`);
  `reasoning_effort` per chat-completions request is confirmed **broken**
  upstream (open bug, lmstudio-ai/lmstudio-bug-tracker#988 — the
  UI-configured value always wins regardless of what the API request
  sends). Its native `/api/v1/models` endpoint *is* good for read-only
  visibility (real `max_context_length`/loaded `context_length`/reasoning
  capability options), just not for setting anything per-request.
- **Apple Silicon MLX vs GGUF speed** is genuinely nuanced, not a flat
  "MLX always wins": meaningfully faster for models under ~14B, but the
  gap mostly closes for ~27-32B-class models (the user's actual
  `qwen3.8-27b`), and at 30K+ context tokens MLX can become *slower* than
  llama.cpp with FlashAttention — i.e. shrinking context favors MLX,
  giving it more context favors GGUF/llama.cpp. Treat exact percentages
  from web benchmarks loosely (sources disagreed on magnitude); the
  *direction* and the long-context crossover are the load-bearing facts.
- **Format portability, concrete constraint on the user's own two
  models:** `qwen3.8-27b` (GGUF) runs on LM Studio/Ollama/llama.cpp;
  `qwen3-4b-thinking` (MLX format) only runs on MLX-capable runtimes
  (LM Studio's MLX engine, or Apple's own `mlx-lm`) — Ollama's brand-new
  MLX support is a narrow preview tied to one specific NVFP4-quantized
  model, unrelated to either of the user's actual models.
- **Cloud providers checked directly against this harness's own code, not
  assumed:** Anthropic's `thinking: {budget_tokens}` and OpenAI's
  `reasoning_effort` are both already fully implemented and functional
  (`anthropic.py`/`openai_provider.py`) — nothing missing there. Context
  isn't a per-request lever for cloud models at all (fixed per model), so
  there's no equivalent gap to close on that side.

**Scope in roadmap terms:** not designed, not scoped — needs a real
thinking-through session before it becomes a buildable item, per the
user's own explicit framing. Possible shape, not decided: some kind of
per-agent or per-provider-tier settings profile, informed by which
capabilities (context control, working reasoning-level control) are
actually real for the tier in use, rather than assuming uniform
capability across all of them the way `provider_kwargs` currently does.

### Split openai_provider.py (added 2026-08-16)

`providers/openai_provider.py` is ~600 lines, well past the 500-line
guideline, driven by hosting two full endpoint implementations
(Responses + Chat Completions, both streaming and non-streaming) in one
module. Deferred deliberately when Chat Completions streaming was added
(2026-08-16) — user asked to get streaming working now, not split the
file mid-feature. Natural seam if/when this gets done: `openai_responses.py`
/ `openai_chat_completions.py` behind the existing single `chat()` entry
point in `openai_provider.py`, so nothing outside this module needs to
change. Not urgent — file is still readable, just long.

### Refining the reflection loop (added 2026-08-05)

`loops/reflection.py`'s stopping condition is `"DONE" in critique_text.upper()`
— the model self-reporting that its own critique passed, not anything
verified. Same self-report weakness already flagged for `ralph.py`'s
`_DONE_MARKER` in "What a decent coding agent would need" (below/above).

Possible directions, none decided:
- Structured critique output (a real pass/fail + reasons) instead of
  keyword-matching free text.
- A way for the critique phase to reference programmatic verification
  (e.g. actually run tests) rather than only the model's own judgement —
  `eval_optimize.py`'s numeric `SCORE: N/10` is a small step in this
  direction already, but it's still self-reported, not verified.
- Conceptual overlap with the eval framework's grader split
  (`docs/eval_framework.md`) — the critique step is essentially an ad hoc
  model grader with no gate/signal distinction and no code-grader option.
  Worth asking whether reflection's critique phase could borrow that
  concept rather than reinventing verification twice.

**Promoted (2026-08-15), shipped (2026-08-15):** see "Verified task
completion" in Done — broadened beyond just `reflection.py` to cover
`ralph.py`/`eval_optimize.py`'s same self-report weakness.

### Framework comparison

Build agents to research/compare other agent frameworks. Look at Andrew
Ng's `aisuite` on GitHub for any design tips. Not a harness feature —
a research task, kept here rather than forced into a build-shaped entry.

### Use file-based databases? — ties to "Per-task cost attribution" below

TinyDB, DuckDB, or SQLite for some storage. Motivating case: cost/task
attribution data (below) is currently JSONL — would be trivial SQL to
query if it lived in one of these instead. Needs that concrete driver
before it's roadmap-ready on its own.

### High level tools — needs discussion before this is actionable (added 2026-08-06)

code generation / sql / storing the outputs?

Real question underneath the fragments: how do we make more generic,
multi-purpose tools rather than one narrow tool per task — e.g. when is
`execute_code` with guidance the right call versus a purpose-built tool?
"sql" only makes sense once/if the file-based-DB idea above happens.
Needs a real discussion, not resolvable as a one-line idea — revisit
together before drafting a proper entry.

### Security — needs scoping, stays here until we get to it (added 2026-08-06)

Prompt injection is the obvious one. Checked the current OWASP LLM Top 10
(2026 edition, published 2026-08-04) against this codebase directly so the
research is here when this gets scoped properly, rather than re-derived
from scratch:

**Correction (2026-08-06):** the first pass of this list undersold what
`hooks.py` already does — written without actually reading it first. Redone
against the real code:

- **Sensitive Information Disclosure** — partially mitigated for secrets,
  not at all for PII. `secrets_leakage_scanner` (`hooks.py`, an
  `after_tool` hook, on by default) redacts known secret *shapes* (API keys
  matching `sk-`/`ghp_`/`AKIA` prefixes, private key headers) from tool
  output before it reaches the LLM. Real gap: narrow pattern list — a
  generic password or a company-specific secret format sails straight
  through. Separately, and worth not conflating with the above: **there is
  no PII detection/redaction at all** — checked directly, confirmed via
  repo-wide search 2026-08-06. Not hypothetical — `column-matcher` handles
  real pension data (DOB, gender, participant status) via
  `profile_data`/`value_overlap` with zero PII-specific protection today.
- **Prompt Injection** — also partially mitigated. `injection_scanner`
  (another default `after_tool` hook) scans tool output for patterns like
  "ignore previous" and wraps matches in an `[EXTERNAL CONTENT WARNING]`
  marker — but it *flags*, it doesn't block, and it's three narrow regex
  patterns, easily evaded by anything more sophisticated. `save_memory`
  separately re-runs the same pattern scan before persisting.
- **Excessive Agency** — mixed picture. `permissions.py`'s three-tier
  approval system is genuinely inert by default (empty `always_allow`/
  `always_ask` means every tool call auto-approves) — that part of the
  original claim holds. But it's not the whole story: `dangerous_command_
  blocker` (blocks `rm -rf`, `sudo`, `mkfs`, `dd if=`, redirects to
  `/dev/`) and `network_exfiltration_blocker` (domain-allowlist for
  `curl`/`wget`/`requests`/`urllib`, interactive approve-per-domain,
  persisted) are both default `before_tool` hooks — on unless an agent's
  config explicitly overrides them. Plus `routing.py`'s `max_agent_depth =
  3` caps runaway sub-agent delegation regardless of permission config.
- **System Prompt Leakage** — still a real, unmitigated gap. Nothing stops
  a user asking an agent to repeat its system prompt; `build_system_prompt`
  has no redaction.
- **Improper Output Handling** — still a real gap. Same territory as "Will
  ```JSON catch us out" below: `execute_code`/`write_file`/`routing.py`
  all trust model output with no validation before acting on it.
- **Vector and Embedding Weaknesses** — relevant to `docs/rag-plan.md`,
  worth designing in from Phase 1 rather than retrofitting (still N/A —
  RAG isn't built yet).
- Already well covered: **Unbounded Consumption** (`Budget`/`max_turns`/
  `max_cost`).
- Lower relevance here: Supply Chain (narrow — arbitrary `base_url`,
  future MCP servers), Data/Model Poisoning (not applicable — this harness
  doesn't train anything).

### What a decent coding agent would need (added 2026-08-03)

Curiosity-driven, not a commitment — came out of thinking about the ATF
work. Verified against the actual code, not guessed. Conclusion: closer
than expected — it's not "difficult," it comes down to four things: tools,
a todo list, planning, and completion detection.

**Already there, no work needed:** file I/O + execution (`read_file`,
`write_file`, `run_command`, `execute_code`), cost/turn budgeting (`Budget`),
permission gates + safety hooks, streaming + extended thinking (both shipped
this session), sub-agent delegation (`routing.py`, `orchestrator` example
agent) — directly relevant to "coding agent that builds workflows."

**Tools — two real gaps, both shipped 2026-08-06:**
- ~~No targeted edit tool.~~ **Resolved.** `agent_harness.tools.edit_file`
  — search-replace on a unique match, errors clearly on zero/multiple
  matches. See `docs/features.md`.
- ~~No content search.~~ **Resolved.** `tools/content_search.py` — regex
  search across file contents, recursive. See `docs/features.md`.
- Plus existing `MCP support` idea (above) — still open, now has a
  concrete reason: using the ATF's existing MCP tooling from a coding
  agent needs this.

**Todo list — doesn't exist, flagged as needed.** Nothing in the harness
gives an agent (or the human watching) an explicit, visible, checkable task
list during a long task — the closest thing today is `ralph.py`'s
fresh-context retry, which has no notion of sub-tasks at all.

**Planning — partially exists.** `loops/plan_execute.py` already does
plan-once-then-execute-each-step. What it doesn't do: adaptive re-planning
when a step reveals something the original plan didn't account for — it's a
static plan, not a living one. **Promoted (2026-08-15):** see "Adaptive
re-planning" in Plausible Future Capabilities.

**Completion detection — real weakness, checked directly.** `ralph.py`'s
"done" signal is the model saying the literal word `DONE` in its response
(`_DONE_MARKER`) — a self-report, not a verification. The loop never runs
the test suite itself and checks the result; it just believes the model.
Same category of problem as the JSON-fencing discussion — the loop has no
way to programmatically check its own work. **Promoted (2026-08-15), shipped
(2026-08-15):** see "Verified task completion" in Done.

**Connects to RAG work already planned:** semantic search over a codebase
(not just docs) is the same infrastructure as `docs/rag-plan.md`, different
corpus — worth keeping in mind if either gets built.

### prompt caching

### Structured extraction from free text — JSON and code (expanded 2026-08-06, was "Will ```JSON catch us out")

General utility, not eval-specific — for any caller that needs to pull
structured content out of a chat response, given a model might wrap it in
markdown fencing, an explicit tag, or nothing at all. Decision of *whether*
to extract stays with the caller (it always knows what it asked for) —
this is just the extraction mechanism.

One utility, `extract_delimited(text, tag=None)`, tried in priority order,
not as peer alternatives:
1. **Explicit tag** (`<json>...</json>`, `<code>...</code>`) — if the
   caller told the prompt to use one. Most reliable tier — Claude
   specifically handles explicit XML-style tags very consistently when
   instructed to use them, more reliably than "please don't use markdown."
2. **Fenced code block** (` ```json ... ``` `, or bare ` ``` ... ``` `).
3. **Balanced-bracket scan** (JSON only) — find the first balanced `{`/`[`
   in the text, string-literal-aware so a `}` inside a quoted string
   doesn't prematurely close it. Last resort for "no delimiter at all,
   JSON embedded in prose."

`extract_json` = this chain + a `json.loads()` attempt at each candidate.
`extract_code` = the same chain, tiers 1–2 only — **code has no equivalent
to tier 3**. JSON has one closed structure to balance-scan for; a
multi-statement code snippet doesn't, so code extraction depends on
actually getting a delimiter rather than scanning undelimited text.

Prompting implication worth remembering when this gets used: an
agent/case can ask for `<json>`/`<code>` tags explicitly in its prompt and
get tier-1 reliability, rather than hoping the model happens to fence
things helpfully.

### Browser automation (added 2026-08-06)

Playwright-style tool for agents that need to interact with a web UI, not
just read static content (distinct from the web-fetch tool idea, which
only reads). Real scope — a new subsystem, not a quick add. Came up
alongside the pricing-update demo agent idea.

### Messaging / notification tool (added 2026-08-06)

Slack/email-style "tell someone" capability — for workflows that should
end in a notification, not just produce an artifact. Relevant if ATF
workflows are meant to actually notify people, not just run and stop.

### Check multi turn vs one shot

### api
rest and mcp ?
plus buid chat app?

### RAG framework/tools (added 2026-08-03)

**Status:** Active roadmap design

**What:** Retrieval-augmented generation as a tool by default (agent decides
when to retrieve), with an opt-in config-driven pre-loop injection path for
dedicated knowledge agents. Chroma (embedded/local) as the default vector
provider, Weaviate as a production/hybrid-search option. Phased: plain text
first, PDF mining and multimodal deferred until there's a reason to take
them on.

**Why:** No RAG/embedding capability exists in the harness today — every
agent is limited to what fits directly in its prompt or what a tool reads
verbatim.

**Scope in roadmap terms:** start with the smallest useful slice (text +
tool + Chroma), not the full design at once.

**Deep-dive design:** `docs/rag-plan.md`

### Identity / procedure split (added 2026-04-16)

Optional `identity.md` before `instructions.md` to separate "who the agent is" from "what it should do".

### Model fallback chains (added 2026-04-16)

If the primary provider fails, try a fallback provider before giving up. Keep it config-driven and small if it is ever built.

### Self-improving skills (added 2026-04-16)

After a successful multi-step task, the agent can save the approach as a reusable skill in `{agent_dir}/skills/` and reload it later by convention.

### Immutable trace hash chain (added 2026-04-16)

Make traces tamper-evident by including the previous event hash in each trace entry.

### Per-task cost attribution (added 2026-04-16)

Add `task_id` to trace and budget events so cost can be summed by task later.

### Decision-level approval gates (added 2026-04-16)

Explore approvals by decision severity, not just by tool, if multi-agent orchestration becomes important enough to justify it.

### Shared workspace communication (added 2026-04-16)

Use a `workspace/` directory convention for multi-agent file-based coordination instead of only fire-and-forget delegation calls.

### Agentic patterns backlog (added 2026-04-16)

Compact index entry for unshipped coordination patterns. Script-level fan-out/fan-in and consensus remain possible without framework changes; more advanced branching patterns such as Tree-of-Thoughts and LATS stay explicitly future work until there is a strong reason to pay their complexity cost.

### Rejected

Not bad ideas — just resolved one way or another. Kept with reasons rather than deleted.

~~**How to define fixed and dynamic workflows** — linear pass, orchestration manager calls sub-agent, multi-level hierarchy, all-to-all, async/parallel/routing/voting, evaluator-optimizer, prompt chaining.~~
**Reason (2026-08-06):** already covered — the "Agentic patterns backlog" and "Parallel sub-agent fan-out" entries above, plus the loop patterns already built (`plan_execute`, `rewoo`, `debate`, `reflection`, `eval_optimize` *are* prompt-chaining/evaluator-optimizer/orchestrator patterns already). Confirmed by Simon: fixed-linear, routing, and parallelisation are each already either implemented or already on the roadmap. Good study notes, not a new roadmap item.

~~**What other tools do I need**~~
**Reason (2026-08-06):** a meta-question, not a specific idea — already answered by "What a decent coding agent would need"'s tools section (targeted edit tool, content search).

~~**evls add deterministic tests for the same prompt set** — example: date extraction from invoices over 20 invoices.~~
**Reason (2026-08-06):** already shipped, not a gap. `run_repeated(case, cell, n)` + `stdev` in `eval/report.py::summarize()` already does exactly this — run the same case N times, measure consistency — and the eval framework already supports both code-based deterministic grading (gate) and LLM-as-judge (signal) per case via `GraderSpec.kind`, so "code-based logic as well as LLM as judge" is already covered too. What's missing isn't capability, it's an actual test suite — the invoice-date-extraction example is a good candidate first one to build, same shape as the column-matcher capstone.

---

## Done

### Parallel tool-call execution within a turn (added 2026-04-16, resolved 2026-08-23)

A turn's tool calls now run concurrently via a `ThreadPoolExecutor`
(`loops/react.py::_run_tool_calls`, capped at 8 workers) instead of one at a
time — driven by the concrete case already on record (a research agent
firing multiple `web_fetch` calls per turn). Default **on**
(`AgentConfig.parallel_tool_calls: bool = True`, per-agent opt-out via
`config.yaml`), matching the existing `thrash_threshold`/`completion_check`
pattern rather than an easily-forgotten opt-in flag. A single-call turn (the
overwhelmingly common case) skips the executor entirely — no overhead for the
normal path. Results are collected in original call order regardless of
completion order, keeping the resulting message history deterministic even
though execution isn't; thrash detection (`check_tool_thrashing`) moved to
run sequentially over the finished batch rather than interleaved, since it
mutates shared dicts and there's no reason to make cheap bookkeeping
thread-safe when it can just run after. Propagates for free to
`reflection`/`eval_optimize`/`plan_execute`/`ralph`, all of which delegate
their step execution to a react sub-loop — same free propagation the thrash
guard got. `rewoo.py` has its own independent tool-execution loop and does
**not** get this, an acknowledged gap matching the one the thrash guard left.

**Two real correctness gaps found while grounding this in the actual code,
not speculative — both closed as part of this build, not left as documented
footguns, since parallel execution is what makes them possible in the first
place:** `Permissions.check()` and `network.py::make_network_blocker` both
call a synchronous, blocking `prompt_fn` (the CLI's is a literal
`Console.input()`) — safe only because tool calls previously never ran
concurrently. Two calls in the same turn both needing approval would have
raced on stdin/stdout, and the underlying "check membership, maybe prompt,
then record" sequence in both was a TOCTOU race that could double-prompt for
the same tool/domain. Both now hold a lock around the whole check (not just
the prompt call), which closes the double-prompt race as a side effect, not
just the interleaved-stdin one. Also found: `trace.py::Tracer.record` opens
its file in append mode per call with no lock — genuinely safe before
(never concurrent), not guaranteed safe after. Given a lock too.

Real, zero-mock verification, not just unit tests: `tests/integration/test_concurrency_safety.py::TestParallelToolCallWallClockSpeedup`
runs the real react loop with two real `run_command "sleep 1"` calls (real
subprocesses, no mocked provider — a plain hand-written `chat_fn`) in one
turn and confirms wall-clock time lands near 1s, not 2s (asserted `< 1.7s`;
measured exactly ~1.0s parallel vs. ~2.0s with `parallel_tool_calls=False`,
confirming the test is genuinely discriminating, not trivially passing).
Real-thread proofs (not just correctness assertions) for both lock fixes:
`test_permissions.py::TestConcurrentPrompting` and
`test_network.py::TestConcurrentDomainPrompting` each drive 10 real threads
through a slow fake prompt and assert max concurrent entries is exactly 1 —
confirmed genuinely red before the fix (10, not 1) and green after.
`test_trace.py::TestConcurrentRecording` drives 500 concurrent real writes
and confirms none are lost or corrupted — notably, this one did **not**
reproduce red pre-fix (small appends are apparently already atomic at the
OS level here), reported honestly rather than claimed as a red-first proof
that didn't actually happen; the lock was added anyway as correct defensive
engineering, not dependent on that OS behavior holding.

`pytest tests/unit -q` → 791 passed (up from 780); `pytest tests/integration/test_concurrency_safety.py` → 4 passed; ruff clean; `mypy --strict` clean (108 files); `radon cc --min D` → none. One existing test
(`test_react_loop.py::test_multi_tool_call_turn_nudge_positioned_after_both_results`)
needed fixing, not just passing unchanged: its two-tool-call turn now
executes in parallel by default, so its `MagicMock(side_effect=[...])` list
assumed a call order the executor no longer guarantees — switched to a
dict-keyed-by-`tool_call.id` side effect function, correct regardless of
which thread reaches the mock first.

### Harness: path-traversal hook false-positive (resolved 2026-04-16)

The `path_traversal_detector` now validates path-like argument names (`path`, `working_dir`, `directory`, `file_path`) against the workspace root instead of scanning every string argument for `".."`. This removes the known false-positive on free-form code/text while keeping path checks deterministic.

### OpenAI provider hardening for supported text models (resolved 2026-04-16)

The OpenAI provider now supports the selected hosted text model set (`gpt-4o`, `gpt-4o-mini`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.1`, `gpt-5-mini`, `gpt-5-nano`) through one harness-facing provider. Hosted OpenAI requests use Responses by default, OpenAI-compatible `base_url` backends keep Chat Completions for compatibility, GPT-5 cost/context metadata is present, and representative live integration tests passed on the host. `o4-mini` abort investigation remains separate.

### Harness: react loop turn/budget awareness (added 2026-04-09 approx, resolved 2026-08-10)

The react loop now injects a "You have N turn(s) remaining[, Estimated $X remaining]" note into the system prompt on every turn (`Budget.status_note()`, wired via `LoopCallbacks.get_budget_status`, applied in `loops/react.py::_with_budget_note`). Confirmed react.py is the only loop with a genuine per-turn budget concept — other loops either reuse `max_turns` for a different unit or delegate their turn budget to a nested `react_run` call, so this change propagates into those automatically. The note is built as a disposable per-call overlay and never written into the canonical, session-persisted system message — the literal "mutate the system prompt" reading would have baked a stale turn count into any resumed session forever, since `init_messages()` only rebuilds the system prompt when the message list is empty. Verified live: the note decrements correctly turn-by-turn in a real run, and a saved session's system message was confirmed to carry no injected note.

### CLI streaming (added 2026-04-16, resolved by the "Streaming" commit `61d32d3`)

Found stale while reviewing "Plausible Future Capabilities" (2026-08-10) — this had already fully shipped and was never moved out. `--stream`/`--no-stream` CLI flags, `display.py::show_delta`/`show_thinking_delta`, `on_delta`/`on_thinking_delta` callback wiring through `runtime.py`/`loops/react.py`, valid for `anthropic` and `openai` (Responses API models only, rejected for Chat Completions/`base_url` backends at the provider boundary and in `validate_config`). Deep-dive design remains at `docs/streaming-plan.md` for reference.

### Plan critique + human-in-the-loop refinement (added 2026-08-06, resolved 2026-08-10)

`plan_execute.py` now runs a bounded (max 2 rounds) critique/refine round between planning and execution — reuses `reflection.py`'s generate→critique→refine pattern and `_parse_plan()` as-is, stops on a `DONE` marker or an unparseable critique response (falls back to the last good plan rather than looping forever). A new optional `on_plan_approval` callback (`LoopCallbacks`, `types.py`) gates execution on human approval of the full plan — distinct from `permissions.py`'s per-tool-call prompts, since a plan is different text every run and there's nothing meaningful to "remember" across sessions. Inert by default (Phase 2 proceeds automatically) if no `plan_prompt_fn` is wired, matching `Permissions`' own "inert by default" convention; no example agent used `plan_execute` before this, so there was no existing behavior to preserve either way. CLI's `_plan_prompt` renders steps via `rich.text.Text` (not raw interpolated strings), the same markup-safety pattern from this session's earlier corruption fix, since step text routinely contains brackets/backticks. Verified live against the real Anthropic API (`agents/hello --loop plan_execute`): the critique round fired and approved the plan without revision, the approval prompt rendered step text with brackets/backticks correctly (no markup corruption), and rejecting with `n` blocked all step execution — confirmed via the trace log (`plan_approval` event, `approved: false`, no `react_run` steps followed).

### CLI REPL: bright single-letter prompt options (added 2026-08-10, resolved 2026-08-13)

New `_highlight_choices()` helper in `cli.py`: regex-finds each `[x]`-bracketed choice in a static prompt hint and styles the bracketed content `bold cyan`, leaving the brackets and surrounding text unstyled. Wired into all three prompts that use this pattern — `_permission_prompt` (`[o]nce / allow for [s]ession / allow [p]ersistently / [d]eny?`), `_domain_prompt`, and `_plan_prompt` (both `[y/n]`). Returns a `Text` object, so it's structurally immune to markup parsing regardless of the `markup` flag — same safety property as the earlier markup-corruption fix, though not itself a fix (these three hint strings are static, not dynamic content). Verified with a real ANSI-rendering check (`Console(force_terminal=True)`), confirming the `1;36` (bold cyan) escape codes land exactly on `o`/`s`/`p`/`d` and `y/n`, nothing else.

### MCP client support (added 2026-04-16, resolved 2026-08-13)

Agents can now consume external MCP servers as tools — client only, not server (see the new "Scoped out" backlog section above for that and other deliberately-cut pieces). New `agent_harness/mcp_client.py::McpManager`: since the chosen client package (FastMCP, via `fastmcp-slim[client]`) is asyncio-native with no sync API — confirmed true of the official `mcp` SDK too, checked directly rather than assumed — `McpManager` runs one persistent background thread and event loop for the whole run, holding each configured server's connection open (subprocess spawned once, reused for every call, not respawned per tool call) and exposing a plain synchronous `list_tools`/`call_tool`/`close` surface so the rest of the harness never touches asyncio.

New `AgentConfig.mcp_servers` (`config.yaml`'s `mcp_servers:` list, same pattern as `hooks`/`permissions`). `runtime.py::prepare_runtime` starts the manager, merges every discovered tool into the existing `tool_registry`/`tool_schemas` — auto-included, not gated by `config.tools`, since the point of "auto-discovered" is the agent author doesn't hand-enumerate them. Every MCP tool call still flows through the existing `on_tool_call` callback (hooks, permissions, tracer) for free, since it's just another entry in the same registry.

**Collision policy corrected same-day, from real usage, not a code review catch.** Shipped checking MCP tool names against the *entire* tool registry (everything built-in/custom that exists anywhere), matching `discover_tools`'s convention — but user caught via live use of `agents/hello` (which only exposes `read_file`/`run_command`/`execute_code` in `config.tools`) that this was wrong: `write_file`/`edit_file`/`list_directory` are real built-ins, so their MCP equivalents got silently skipped even though `hello` never opted into the built-in versions — leaving all three tool names completely inaccessible, neither built-in nor MCP. Fixed: the check is now against `config.tools` (what this agent actually exposes to the model) plus names already claimed by an earlier MCP server in the same merge (still guards against two MCP servers offering the same tool name) — not the full registry. This means a locally-unclaimed name always resolves to MCP automatically, and an agent author can "claim" any given name for the harness's own (safer/vetted) implementation at any time just by adding it to `config.tools` — no MCP config change needed. TDD: two new tests lock this in (`test_mcp_tool_not_exposed_by_agent_is_not_skipped`, `test_two_mcp_servers_offering_same_tool_name_second_is_skipped`), verified live against `hello` before and after.

**Fail-fast per dead server:** distinguishes a tool-call mistake the agent can self-correct (bad args — `fastmcp.exceptions.ToolError`, flows back to the model as a normal recoverable tool error, unchanged) from an unsurvivable transport failure (server subprocess crashed/pipe broken — any other exception type) — the latter marks that server dead so every subsequent call fails immediately with a clear message instead of repeating a doomed round-trip until the budget runs out.

**Package choice revised mid-planning, not the first instinct:** started with the official `mcp` SDK as the safe default. User's first reason for FastMCP ("we'll use FastAPI later, so synergy") didn't survive a direct check — FastMCP is built by Jeremiah Lowin/PrefectHQ, no relation to FastAPI's author — said so rather than going along with it. The real deciding factor, raised by the user: they intend to build an MCP *server* at some future point, and FastMCP's own docs confirm the slim client and full packages "use the same importable package... application code remains identical regardless of the chosen installation method" — so starting on `fastmcp-slim[client]` now makes that later transition an install-only change. Turned out heavier than hoped in practice (`[client]` transitively pulls in the full `mcp` SDK plus `starlette`/`uvicorn`/`authlib`/`keyring`/`cryptography` — auth/HTTP machinery for a remote-transport path this build doesn't use) — flagged transparently, didn't change the decision, since the deciding argument was migration cost, not dependency weight.

Verified live against the real reference `@modelcontextprotocol/server-filesystem` (via `npx`) at every level: unit tests mock the FastMCP boundary; `tests/integration/test_mcp_real.py` runs the actual stdio server with zero mocks (skips cleanly if `npx` is absent); a manual run of a throwaway agent against the live Anthropic API showed the model correctly discovering and calling the MCP-provided `read_text_file` tool, getting real file content back, and answering correctly — with the built-in-name-collision skip (`read_file`/`write_file`/`edit_file`/`list_directory`) firing exactly as designed in the same run. Confirmed no orphaned `npx`/node processes survive after the harness process exits.

### Multimodal file handling (added 2026-08-06 as "Image handling", broadened and resolved 2026-08-15)

Agents can now genuinely see images and PDFs, and tools can hand back freshly-generated binary content — full requirements/PRD in `docs/multimodal-plan.md`, this entry is the shipped summary. Two capabilities: (A) new built-in tools `view_image(path)`/`view_document(path)` attach a real vision/document content block to the *next* message, not just a text description; (B) any tool can embed base64+filename in its ordinary string output (`attachments.py::wrap_binary_output`) and the harness detects, decodes, guardrails, and saves it, replacing the envelope with a short text reference before it ever enters history or the CLI display.

**Architecture decision, validated by a Plan agent re-reading every touched file:** `ToolResult` gets one new field, `attachment: Attachment | None` — `tool_registry: dict[str, Callable[..., str]]` stays completely untouched, every tool (built-in/custom/MCP) still just returns `str`. Verified both OpenAI translation paths (Chat Completions and Responses) are string-only for tool output, so an attachment becomes a **separate synthetic message following the tool result** on all three translation functions (Anthropic + 2×OpenAI) — uniform, not relying on an unverified Anthropic-specific nested-content quirk. `view_image`/`view_document` are matched by **function identity, not name** in `execute_tool`, closing an edge case where an MCP server exposing its own same-named tool could otherwise get misattributed.

**Two real bugs the validation pass caught before they shipped, not discovered later:**
1. The obvious guardrail reuse (`hooks.py`'s path-traversal helper) would have been a security hole — it deliberately exempts absolute paths for its actual job (explicit tool arguments), but reused for a filename pulled from untrusted tool output, `Path("/agent/tmp") / "/etc/passwd"` silently evaluates to `/etc/passwd` in Python. Mechanism B does its own stricter basename-only check instead.
2. The policy of "let the API reject unsupported content, don't pre-validate against a stale compatibility table" (same lesson as the `COST_TABLE`/o4-mini drift bug) depended on that rejection being a normal visible error — traced the real path and found any `BadRequestError` today crashes the whole process with a raw traceback, no try/except anywhere on the chain. Fixed in `providers/retry.py` (wraps as `RuntimeError`) and `cli.py` (catches it at both the single-shot and REPL call sites) — a real, general fix, not multimodal-specific.

**Token/context handling, two separate mechanisms:** mechanism B's extraction is synchronous at tool-call time, so raw base64 never enters `Message` history at all. Mechanism A's viewed image *does* need to exist as a real content block for the model to see it, so `attachments.py::prune_attachments` keeps only the most-recently-viewed attachment "live" in what's sent to the model (mirrors `loops/react.py::_with_budget_note`'s disposable-overlay pattern exactly — canonical persisted history keeps every attachment, only the API-bound copy is pruned). Wired into both `react.py` and `rewoo.py` — the latter has its own independent tool-execution path that doesn't delegate to `react_run`, found by the validation pass, would otherwise have silently skipped pruning.

**Storage:** new `agent_dir/tmp/` (mirrors `eval/runner.py::_clear_memory`'s existing "fresh state" pattern) — deliberately not session-persisted (`session.py` untouched: a base64 blob surviving into `session.json` would already point at a deleted file on resume). **Updated 2026-08-19:** each run now gets its own `tmp/<run-id>/` subfolder instead of a shared, rmtree-cleared `tmp/` — see "Concurrency-safety for per-agent-dir state" below; the "resume points at a deleted file" reasoning still holds, just per-run-folder rather than per-clear now.

Verified live, zero mocks, real files, real API calls throughout: a real striped PNG (stdlib-only PNG encoder, no new dependency) viewed via `view_image` against live Anthropic — the model's exact color-and-order description proves genuine visual perception, not a guess (an earlier attempt with a too-small 40×30px test image got the colors wrong even with correctly-attached real image data, confirmed via an isolated raw-API call — a test-image-sizing issue, not a harness bug, fixed by using a larger image); two-image pruning confirmed against a live run (canonical history keeps both, the pruned overlay keeps one); mechanism B confirmed end-to-end via `execute_code` generating real PNG bytes in-process, saved correctly, zero base64 in captured output; graceful degradation confirmed against a real local OpenAI-compatible LM Studio server — both the deterministic Chat-Completions-has-no-PDF-type note and a genuine live provider rejection (`RuntimeError`, not a crash) verified for real.

### Verified task completion (added 2026-08-15, resolved 2026-08-15)

`reflection`/`ralph`/`eval_optimize` now support an optional `completion_check: <string>` config field (default unset — fully inert). When set, a DONE/SCORE-pass claim must also pass this check before the loop stops; on failure the check's own output feeds back to the model and the loop retries, bounded by the loop's existing `max_turns`/`Budget` machinery. Dispatch always goes through the normal tool-call path (`cb.on_tool_call`) — if the string names one of the agent's exposed tools, it's called with no arguments; otherwise it's treated as a shell command and routed through the built-in `run_command` tool. Pass/fail convention: a tool error or `FAIL`-prefixed output fails; a `PASS`-prefixed output or a `[exit code 0]` marker passes; anything else fails closed.

**Two real, pre-existing bugs found and fixed as part of this work, not left as tangential gaps:** (1) `run_command` never read `result.returncode` at all — a failing shell command was indistinguishable from a passing one; fixed by unconditionally appending `[exit code N]` to its output (both on success and failure, not just failure — a nonzero-only trailer would have left a genuinely-passing command with no signal at all under the pass/fail convention above). (2) `ralph.py`'s outer retry loop never checked whether the shared `Budget` was already exceeded before starting another attempt, so it kept burning wasted attempts and re-printing the budget-exceeded message once per attempt — fixed with a new `Budget.is_exceeded()` read-only check, threaded through a new `LoopCallbacks.is_budget_exceeded` callback, checked after every ralph attempt. Independent of `completion_check` — applies to every ralph run.

**User-visible signal, closing a real gap:** `cli.py` previously discarded a loop's return value entirely — nothing distinguished "stopped because verified" from "stopped because budget ran out, unverified" in what the user actually saw. New `LoopCallbacks.on_completion_status(verified, detail)` fires once at the end of a run, only when `completion_check` is configured, wired to a new `display.py::show_completion_status` line (green "Verified complete" / red "NOT verified", mirroring `show_budget`'s shape).

`ralph.py`'s failure-feedback path is a deliberate, scoped softening of its "naive fresh context every attempt" identity: a failed check's output is fed into the *current* attempt (not discarded on a fresh restart) so the model can actually act on it — discarding real failure feedback every time would defeat the point of checking at all. This only applies when `completion_check` is configured; with it unset, behavior is byte-identical to before.

Verified: `pytest tests/unit -q` → 644 passed (up from 588); ruff clean; `mypy --strict` clean (91 files); `radon cc --min D` → none (no D-or-worse anywhere). Real, zero-mock integration test (`tests/integration/test_real_loops.py::TestCompletionCheck`) proves a genuine fail-then-retry-then-pass cycle against the live Anthropic API — a deterministic counter-based checker script fails its first invocation and passes every one after, independent of model behavior, confirming the retry mechanism works end-to-end rather than just in mocked unit tests.

`docs/roadmap.md` Priority Order renumbered (Adaptive re-planning is now #1); `docs/features.md`/`README.md` updated.

### Concurrency-safety for per-agent-dir state (added 2026-08-15, resolved 2026-08-19)

Fixed three real races confirmed against actual code, all triggered by two concurrent runs of the *same* agent (e.g. two rooms asking the same home-assistant agent something at once): (1) `runtime.py::prepare_runtime` unconditionally `rmtree`d and recreated `agent_dir/tmp/` on every call — two concurrent runs could wipe each other's in-progress binary tool output; (2) `memory.py::save_memory`'s naive `write_text` could leave a garbled file on a concurrent write to the same key; (3) `session.py::save_session` had the same naive-write problem, only relevant when two concurrent runs share the same `--session` name.

**tmp/ — isolated per-run, not locked.** `prepare_runtime` now generates a short id (`uuid.uuid4().hex[:8]`) and creates `agent_dir/tmp/<run-id>/` instead of clearing a shared `tmp/`. The `shutil.rmtree` call is gone entirely — nothing to clear that another run owns. `PreparedRuntime` gained a `tmp_dir: str` field so callers/tests learn the resolved per-run path (nothing downstream assumed a fixed `agent_dir/tmp` location — `execute_tool`/`extract_and_save_binary_output` already treated it as an opaque path, and the model always learns the real saved path from the tool's own returned text). **Accepted, documented tradeoff:** old run subfolders are never cleaned up — age-based cleanup would need a threshold that can't misfire against a genuinely slow still-running process, and there's no evidence unbounded `tmp/` growth is a real problem yet.

**memory.py / session.py — atomic write via same-directory temp file + `os.replace`, not locking.** New leaf module `agent_harness/atomic_write.py` (stdlib only, zero internal imports): `atomic_write_text(path, content)` writes to a uniquely-named temp file in the same directory (same filesystem, so the rename is atomic) then `os.replace`s it into place — a reader always sees the complete old content or the complete new content, never a partial/interleaved write. Deliberately does **not** resolve which of two truly concurrent writes to the identical key wins — documented last-write-wins for that narrow case, not building merge semantics without evidence it's needed. Both `memory.py`/`session.py` got a one-line write-call swap each, no public signature changes.

Verified: `pytest tests/unit -q` → 684 passed (up from 644); ruff clean; `mypy --strict` clean (95 files); `radon cc --min D` → none. Real, zero-mock concurrency stress tests in `tests/integration/test_concurrency_safety.py` (`threading.Thread` + `threading.Barrier` to force genuine overlap, not staggered starts; final-state-only assertions, not timing-dependent) prove 500 concurrent writes to the same memory key and 500 concurrent writes to the same session file never produce a garbled/corrupt result. A parallel unit test (`test_concurrent_prepare_runtime_calls_get_isolated_tmp_dirs`) confirms 10 concurrent `prepare_runtime` calls each get a distinct `tmp_dir` with nothing clobbered.

`docs/roadmap.md` Priority Order renumbered (Permission/approval UX for no-terminal contexts is now #1, API/async boundary #2, parallel tool-call execution #3, parallel sub-agent fan-out #4).

### HTTP API server (added 2026-08-15 as two items — "Permission/approval UX for no-terminal contexts" and "API / async boundary" — merged and resolved 2026-08-22)

Full requirements/architecture discussion first (`docs/api-plan.md`), since the two parent roadmap items turned out tightly coupled — designing the approval mechanism without first picking the transport shape would have meant redesigning it once the transport was chosen. Real driving clients established through that discussion: a separately-built web chat UI (not part of this repo), eventually Reachy Mini (voice, own STT/TTS), possibly an Echo-via-AWS-Lambda proxy "one day."

**Transport:** one HTTP request per agent turn ("run"), held open, response streamed as Server-Sent Events. Client→server stays ordinary short requests: start a run, and a generic signal endpoint (`POST /runs/<run_id>/signal`, `{"approval_id", "decision"}`) for anything that needs to reach into an in-progress run — deliberately generic, not approval-specific, so real cancellation (deferred, see below) can reuse it later without a redesign. Thread-per-request, not asyncio — each held-open SSE connection is one thread blocked on I/O, genuinely idle not CPU-bound, and the real client count (a handful of devices) is nowhere near where that stops being fine. **Flask chosen over FastAPI**: FastAPI's real draw (Pydantic models, free interactive docs) means adopting Pydantic for a project that avoids it unless necessary, for a benefit (async-native performance) this design deliberately doesn't use; Flask's `stream_with_context` is the standard, singular SSE recipe, FastAPI's isn't.

**New `agent_harness/api/` subpackage** (mirrors the `loops/` convention): `events.py` (`SseEvent`, `format_sse` — pure, no I/O), `registry.py` (`RunRegistry` — one class handles both session-exclusivity and approval-blocking, since splitting them into two separately-locked objects would make "claim a session slot" and "register a run" non-atomic, a real race), `callbacks.py` (API-specific implementations of the permission/domain/plan prompts and a new `OutputSink`, all wired to the registry), `routes.py` (Flask app, `create_app`/`serve`, new `agent-harness serve` subcommand on the existing CLI — architecturally a sibling of `cli.py`, not a separate package, both are thin drivers supplying their own callbacks to `prepare_runtime`).

**Required, necessary scope expansion found during planning, not speculative:** `runtime.py`'s `on_delta`/tool-call/budget/thrash callbacks were hardwired to either print via `display.py` or no-op, with zero injection point for redirecting them elsewhere — confirmed by reading `_make_callbacks` directly. Closed with a new `OutputSink` dataclass (`types.py`) and an additive `output_sink` param on `prepare_runtime`, fully backward-compatible (CLI passes `None`, unaffected). `_make_callbacks` extracted into a new sibling module `runtime_callbacks.py` first, since `runtime.py` was already at 478/500 lines.

**Session identity redesigned GUID-first**, mirroring Claude Code's session model: every session gets a GUID regardless of whether a human names it; a name is optional/cosmetic, resolved via a directory scan (no second index file to keep in sync). Breaking file-format change to `session.py` (bare message array → `{"id", "name", "messages"}`), no migration — accepted, pre-1.0 personal project, existing local session files are throwaway. CLI's `--session foo` UX is unchanged externally; GUID resolution happens transparently underneath. **One active connection per session at a time, enforced not just documented** — `save_session` overwrites the whole file rather than appending, so two genuinely concurrent writers to the same session would otherwise silently drop one writer's entire turn; a second run request against a session already in flight gets rejected (409).

**Real bug caught by the end-to-end integration test, not found any other way:** the initial exclusivity check keyed on the *resolved* session's id — but resolving a session by name is itself a non-atomic find-or-create, so two concurrent first-time requests for the same never-before-used name each found nothing on disk and each created a distinct fresh id, never colliding in the registry at all. A real two-thread HTTP test against the live server proved both got `200` before the fix landed. Fixed: exclusivity is now claimed on the caller's *requested* identifier (the raw `session_id`/`session_name` from the request body) before any file lookup happens, not the identifier that lookup produces. A second real bug from the same test pass: the client had no way to learn a run's id to answer an approval — nothing in the SSE stream carried it. Fixed with an `X-Run-Id` response header set before the streaming body begins.

**Approval waits time out** (5 minutes, default-deny on expiry) — a run blocked on an approval that never arrives releases its session lock instead of holding it forever, the same fail-safe instinct as the `EOFError` fix folded into this build (`_permission_prompt`/`_domain_prompt`/`_plan_prompt` now catch `EOFError` from non-interactive stdin and default-deny instead of crashing raw). `permissions.py::Permissions.save()` also swapped to `atomic_write_text` — a real gap the concurrency-safety work above had missed, same class of per-agent-dir race, folded in here since it was found while grounding this build in the real code.

**Explicitly scoped out, not forgotten** (all captured in `docs/api-plan.md`): real cancellation execution (the signal endpoint's shape deliberately didn't preclude it — reused as-is, unchanged, when it was built; see "Real cancellation ('stop')" below, shipped 2026-08-23); true suspend/resume of a run; full auth (accounts/tokens/OAuth) beyond the existing shared-secret header; agent create/delete/edit via the API (list/run only); websockets; reconnect gap-recovery.

**Documented, not built:** any caller holding the shared secret can list/resume/run every agent and session — the same trust boundary the secret already grants for everything else, not a separate protection layer for sessions specifically. Must be stated plainly in `README.md`/`docs/features.md` — done as part of this same pass.

Verified: `pytest tests/unit -q` → 762 passed (up from 684); ruff clean; `mypy --strict` clean (107 files); `radon cc --min D` → none. Real, zero-mock, end-to-end integration tests (`tests/integration/test_api_server.py`) against a real Flask app on a real socket (`werkzeug.serving.make_server`, real `httpx` client): a genuine SSE run against the live Anthropic API streaming real `delta`/`done` events; the concrete concurrency proof (two real barrier-adjacent threads racing a `POST` against the same session name — exactly one `200` and one `409`, on-disk session file has exactly one new turn, not silently dropped); a real approval round trip (two separate live connections — one blocked mid-run on `registry.await_signal`, a second answers it, the first then reaches `done`, not the timeout-driven default-deny path); real auth rejection. `docs/roadmap.md` Priority Order collapsed (Track A shipped; Track B renumbered to #1/#2), `docs/api-plan.md` status updated, `docs/features.md`/`README.md` updated with the new `serve` subcommand and the shared-secret trust-boundary statement.

**Same-day fix from real usage, not a code review catch (2026-08-22):** hit live within minutes of shipping — a config.yaml typo (`stream:true`, no space) raised `yaml.YAMLError` inside `config_loader.load()`, which `_handle_start_run` only caught as `FileNotFoundError`, so it leaked a raw, message-free Werkzeug 500 HTML page. Worse, found while fixing that: `_run_worker` only wrapped `run_messages()` in `except RuntimeError` — any exception earlier in the function (`prepare_runtime` itself failing config validation, e.g.) went completely uncaught in the background thread, silently hanging the client on heartbeats forever with the session's exclusivity lock stuck busy permanently, since `_sse_stream` only calls `end_run()` after seeing a `done`/`error` event that would now never arrive. Fixed: `_handle_start_run` catches any config-load exception and returns a clean `400` with the real message; `_run_worker` split into a thin outer wrapper (catches anything, logs the full traceback via `logger.exception`, guarantees an `error` event always reaches the client) around the existing `_execute_run` logic. Also: `serve()` now calls `setup_logging()` (new `--verbose` flag) so the terminal running `agent-harness serve` shows properly formatted logs instead of relying on Python's bare fallback handler — a real "I can see no logs" gap raised directly by live use, not anticipated in the original design. Verified against the exact original failure (temporarily reintroduced the same YAML typo against the live running server, confirmed a clean JSON error and a visible traceback in the log, restored the fix) and with two new tests (`TestWorkerFailureSafety`, using `tests/data/invalid_agent_bad_provider` to trigger a real `prepare_runtime`-time failure) proving the session lock releases correctly. `pytest tests/unit -q` → 765 passed; ruff/mypy/radon unchanged, still clean.

**Second same-day fix, a genuinely different bug (2026-08-22):** the API/chat client appeared to hang indefinitely on a real local LM Studio thinking model (`qwen3-4b-thinking-2507`) for anything but the simplest prompts — diagnosed with real curl tests, timestamped and cross-checked against LM Studio's own server log (not guessed): the request genuinely reached LM Studio and was genuinely streaming the whole time, confirmed by pulling LM Studio's raw SSE response directly, which showed thinking-model reasoning arriving on a separate `reasoning_content` delta field, distinct from `content`. `openai_provider.py::_stream_chat_completions_deltas` (and `_chat_completions_to_response`, the non-streaming path) only ever read `delta.content` — every reasoning token was silently discarded, no `on_thinking_delta` fired, so the harness (and therefore the API and any client) sat in total silence for as long as the model thought, indistinguishable from a real hang. Compare `anthropic.py::_stream_deltas`, which already handles Claude's extended thinking correctly — this was a real, confirmed gap specific to the OpenAI-compatible Chat Completions path, not a design decision. Also confirmed live: a real response can exhaust `max_tokens` entirely on thinking before any real content (`finish_reason: "length"`, `content: ""`) — previously surfaced as a silent empty answer, not even an error.

Fixed: both functions now read `reasoning_content` via `getattr(..., None)` (safe for real hosted OpenAI responses, which simply don't have the field), accumulate it into `Message.thinking`, and the streaming path fires `on_thinking_delta` per chunk — mirroring the Anthropic implementation exactly. `content` now normalizes empty-string-only to `None` in both paths (previously only the streaming path did this), so an all-thinking response is distinguishable from a genuine empty answer. `chat()` threads a new `on_thinking_delta` kwarg through to the streaming path. Deliberately not touched: the Responses API streaming path (`_stream_responses_deltas`, hosted OpenAI reasoning models) — no confirmed evidence of its reasoning-delta event name, and guessing one risked either dead code or a silently-wrong implementation; left as a documented gap, not fixed on assumption.

Real end-to-end verification, not just unit tests: re-ran the exact prompt that originally looked hung against the live running server after the fix — `thinking_delta` events started arriving within ~2 seconds instead of nothing but heartbeats for 2+ minutes. `pytest tests/unit -q` → 769 passed; ruff/mypy/radon clean. New tests in `tests/unit/test_provider_openai.py::TestChatCompletionsStreaming` (reasoning deltas fire `on_thinking_delta` not `on_delta`, all-thinking response leaves `content=None`, missing callback doesn't raise) and `TestToResponse` (non-streaming reasoning populates `thinking`).

**Third same-day fix pass, three related run-lifecycle bugs found via live dogfooding against the local LM Studio model, not code review (2026-08-23):**

1. **Double-terminal-event crash.** `_execute_run` pushed an `error` event on a `RuntimeError` from `run_messages`, then fell through and pushed a `done` event too — but `_sse_stream` already calls `registry.end_run()` on the first terminal event it sees, so the second push hit an already-unregistered run and raised `UnknownRunError`, uncaught, crashing the worker thread. Found from a real captured server log: three chained tracebacks, all `UnknownRunError`, correlated against an `ExplicitModelUnloadError` in LM Studio's own log at the same timestamp. Fixed with an `errored` flag on `_execute_run`, returning immediately after the `error` push instead of falling through to `done`; `_run_worker`'s own crash-safety-net push also wrapped in `contextlib.suppress(UnknownRunError)` for the same reason — it can legitimately fire after the run's already ended.
2. **Missing immediate first SSE event.** `_sse_stream`'s first action blocked on `registry.pop_event(timeout=15.0)` — nothing was yielded, not even HTTP headers (Werkzeug doesn't flush a streaming response's headers until the generator produces its first chunk), until either a real event arrived or the full 15s heartbeat interval elapsed. Found by measuring a real captured trace (an exact 15.005s gap between request sent and `HTTP 200` received) plus a fresh live report of an 8s gap on a different prompt. Fixed by yielding an immediate `heartbeat` before entering the wait loop. Test measured the exact pre-fix 15.005s delay, confirming the mechanism precisely before fixing it.
3. **Session lock never released on client disconnect, and separately, never released if no reader ever connects.** Two related gaps in the same area, found from the user's own test plan (kill `chat/cli.py` mid-response with Ctrl-C, then immediately retry): (a) if a client disconnected mid-stream (closed terminal, dropped network, `SIGINT`), `_sse_stream`'s generator was torn down via `GeneratorExit` before it ever saw a terminal event, so `end_run()` never ran — the session stayed locked until the abandoned run happened to finish on its own, confirmed live to survive a laptop sleep/wake and an LM Studio model unload/reload; (b) structurally, if no reader ever connected to consume the stream at all, nothing called `end_run()` either, for the same underlying reason. Fixed both at once: `_run_worker` now calls `registry.end_run(run_id)` unconditionally in its own `finally` (independent of whether any reader exists), and `_sse_stream`'s entire body (not just its loop) is wrapped in `try:/finally: registry.end_run(run_id)` so a `GeneratorExit` at any point — including the very first yield — releases the lock immediately rather than relying on the worker's backstop to eventually catch up. `end_run` is already idempotent (pop-with-default), so both call sites firing is always safe.

Verified end-to-end against the real running server, not just unit tests: a real `chat/cli.py` subprocess sent a real `SIGINT` mid-stream, force-killed, then a fresh request against the exact same session name — confirmed `200` and immediate streaming, not `409`. `pytest tests/unit -q` → 780 passed; ruff/mypy --strict/radon cc --min D all clean. New tests: `TestDoubleTerminalEventBug`, `TestImmediateFirstEvent` (including the 15.005s pre-fix timing measurement), `TestSessionLockReleasedWithoutAReader`, `TestLockReleasedOnClientDisconnect` — all in `tests/unit/test_api_routes.py`.

**Deliberate sequencing decision, acted on later the same day:** real cancellation (aborting in-flight work, not just releasing the lock) stayed deferred at this point per the existing "Explicitly scoped out" note above — these three fixes only made an already-abandoned run's *lock* release promptly; they didn't make the abandoned run stop doing work. Discussed directly with the user: client crashes are realistically frequent this early in dogfooding, real interruption is real, non-trivial work (the loop layer has zero interrupt points today), and the two aren't the same problem — lock release was worth fixing first (cheap, testable via Ctrl-C), real stop was worth building once there's a working Streamlit app in daily use to want it against. See "Real cancellation ('stop')" below — built the same day, once the Streamlit fixes landed and the user asked to discuss it directly.

### Real cancellation ("stop") (deferred 2026-08-22 pending Streamlit dogfooding, resolved 2026-08-23)

Full PRD-then-plan cycle, written up in `docs/stop-plan.md` (now marked Shipped) before any code: real, grounded requirements discussion (not guessed) covering what's actually interruptible in the real code, three decisions confirmed directly with the user via `AskUserQuestion` — scope limited to turn-boundary + mid-stream interruption only, explicitly **not** mid-tool-call kill (`run_command`/`execute_code` use blocking `subprocess.run`, no live handle to kill early — separate, bigger scope, no evidence it's needed since the driving case is rambling *thinking*, not a stuck tool call); applies to the plain CLI too (graceful SIGINT, not a hard process kill), not just the API; `chat/cli.py`'s Ctrl-C now sends a real cancel signal before disconnecting, completing the disconnect-lock-release work from the day before. Streamlit's own Stop button UX stayed explicitly out of scope — `chat/app.py` blocks the whole script on `st.write_stream`, so a button can't even be clicked mid-stream with today's structure; that's its own follow-up once this mechanism is proven via `chat/cli.py`.

**Real empirical finding that changed the design, not assumed:** a live timing script against the real Anthropic streaming API proved `stream.get_final_message()` on an early-broken delta loop keeps consuming the rest of the stream internally — 30.77s elapsed, essentially identical to the 30.04s full-response baseline, versus 3.44s when the loop is broken early and `get_final_message()` is never called. This meant the originally-sketched design (rely on the SDK's own final-message accumulation even for the cancelled path) would have silently defeated cancellation entirely — no wall-clock benefit at all. Fixed by adding local delta accumulation to `anthropic.py::_stream_deltas` (mirroring the pattern `openai_provider.py::_stream_chat_completions_deltas` already used) and building the cancelled-path `Response` from that instead, never touching `get_final_message()` on that path. `react.py::run()`'s existing `if response.stop_reason != "tool_use": break` already handles a `stop_reason="cancelled"` response for free — no new branch needed there, only a new `LoopCallbacks.is_cancelled` checked once per turn (same shape/placement as `ralph.py`'s existing `is_budget_exceeded` check) and threaded into both providers' `chat_fn` calls for the mid-stream case.

**A second real, independent bug found during live verification, not part of the original plan — fixed the same day since it directly undermines cancellation's own reliability:** the API's `RunRegistry.push_event` raises `UnknownRunError` once a run's reader has disconnected and released it (the 2026-08-22 disconnect-lock-release fix's own `end_run()` call) — previously harmless in practice only because an abandoned run kept running for a long time before its worker got around to pushing anything else. Real cancellation makes an abandoned run finish in seconds instead, so a worker still mid-turn when its reader vanishes now reliably tries to push more events (deltas, thinking deltas, the terminal event) to an already-unregistered run — every one of those uncaught `UnknownRunError`s propagated through `_run_worker`'s generic exception handler and got logged as "crashed unexpectedly," a misleading label for what's actually an expected, benign race. Confirmed live against a real local LM Studio model, not guessed: a genuine Ctrl-C mid-thinking-stream produced exactly this crash trace on the first attempt. Fixed with a new `RunRegistry.try_push_event(run_id, event) -> bool`, tolerating an unregistered run instead of raising; every push site in `api/callbacks.py`'s `OutputSink` and `api/routes.py::_execute_run`'s terminal/error events now uses it. `push_event` itself keeps its raising behavior for callers that genuinely want to know about a bad run_id.

Verified end-to-end against the real running server and a real local model, not just unit tests: a real `chat/cli.py` subprocess, real thinking tokens observed streaming, a real `SIGINT` mid-stream — client returned to the `>` prompt immediately, server log showed `Turn 1: 0 in / 0 out tokens` (the cancelled-path zero `Usage`, exactly as designed) and no crash trace, a fresh request against the same session succeeded immediately. Separately verified the full `anthropic.py::chat()` path (not just the raw SDK experiment) against the live Anthropic API: cancelled after 2.69s with 802 characters of genuine partial content and `stop_reason="cancelled"`, versus 30+ seconds for the same prompt's full response. `pytest tests/unit -q` → 817 passed (up from 791); `pytest tests/integration/test_concurrency_safety.py tests/integration/test_api_server.py` → 9 passed; ruff clean; `mypy --strict` clean (108 files); `radon cc --min D` → none (`react.py::run` briefly regressed to D(21) after the turn-boundary check and `is_cancelled` kwarg landed — fixed by extracting the existing tool-call/thrash-detection block into a new `_handle_tool_calls` helper, back to C(16), checked explicitly rather than assumed safe). `docs/stop-plan.md` status updated to Shipped, `docs/features.md` updated (Agent loops section, HTTP API server section, Configuration & CLI section).

### Step-level tool-call thrashing breaker (added 2026-08-15, resolved 2026-08-15)

`react.py` now guards against a step thrashing — the same tool erroring `thrash_threshold` times in a row, or called with identical arguments that many times total in one run (default 3, on by default unlike `completion_check`, since a repeated failure is never something an agent legitimately wants unbounded; `<= 0` disables it). Detect-and-nudge-only MVP, as scoped: an explicit message ("this approach isn't working, try something fundamentally different") feeds back to the model once per turn, `LoopCallbacks.on_thrash_detected(tool_name, detail)` fires (traced as `thrash_detected`, shown via a new `display.py::show_thrash_warning`), and the loop otherwise continues exactly as before — no stop/escalate pathway; that's "Adaptive re-planning" (above), a separate, later item this is the trigger mechanism for.

Detection lives in a new pure helper, `loops/common.py::check_tool_thrashing` (mutates two per-run dicts — `call_counts`/`error_streaks` — passed in by `react.py`, error streak checked first when both signals fire on the same call). Because `reflection`/`eval_optimize`/`plan_execute`'s step execution and `ralph`'s per-attempt execution all delegate to a react sub-loop, every one of them gets this for free with zero changes to those files; `rewoo.py` has its own independent tool-execution path and doesn't — acknowledged, not built.

**One correctness fix made during implementation review, not caught by the initial design:** the first sketch injected the nudge message *inside* the per-tool-call loop, immediately after the triggering call's result. Reviewed against the provider message-translation layer's constraints before building: Anthropic's API expects every `tool_result` for one assistant turn's `tool_use` blocks to arrive together, correlated by ID — injecting a `user`-role message between two sibling `tool_result`s (a turn with 2+ tool calls, thrashing detected on an early one) risked breaking that pairing. Fixed by deferring the nudge append to *after* the whole turn's tool calls are resolved — the same slot `reflection.py`/`ralph.py`'s own follow-up messages already use safely — locked in with a dedicated multi-tool-call-in-one-turn positioning test.

Verified: `pytest tests/unit -q` → 668 passed (up from 644); ruff clean; `mypy --strict` clean (92 files); `radon cc --min D` → none (`react.py::run` moved from C(15) to C(18), still comfortably inside the C band). Real, zero-mock integration test (`tests/integration/test_real_loops.py::TestThrashGuardPlumbing`) seeds a conversation history with several pre-built repeated-failure tool-call turns plus an already-injected nudge message and confirms it survives a real Anthropic API round-trip — explicitly testing plumbing, not live-model misbehavior (a capable model won't reliably thrash on cue, so detection logic is covered by deterministic mocked unit tests instead). All 12 existing real-API loop-pattern integration tests re-run and passed unchanged, confirming the new on-by-default threshold doesn't interfere with any normal, non-thrashing run.

`docs/roadmap.md` Priority Order renumbered (Adaptive re-planning is now #1, no longer built-on-a-pending-prerequisite); `docs/features.md` updated.

---

## Roadmap Filter

Any new feature idea must provide a clear benefit before it belongs in this roadmap.

A feature should improve at least one of:

- user value for someone using the harness
- quality of agent outcomes
- execution time or feedback speed
- reliability, safety, or debuggability
- a concrete future capability without premature complexity

It should also pass this test:

- the benefit is greater than the added complexity
- it preserves the harness as simple, elegant, and easy to reason about

If an item cannot state a real benefit clearly, keep it in `Ideas` or do not add it.
