# Roadmap / Todo

Durable list of things we've identified but haven't done yet. One section per item, dated when added. Add rather than edit — keep the history.

When an item ships, move it to the **Done** section at the bottom with a commit reference and the date.

---

## Near-term Improvements

### Investigate o4-mini run-1 abort (added 2026-04-15)

**What:** On the first of 5 H1p3 runs on `o4-mini` (commit `49e0799` era), the agent completed tool calls through turn 6/10 and then stopped with a `tool_result` as the last trace event — no terminal assistant message, no `write_file`, no output JSON. Subprocess exited 1 silently. Runs 2–5 on the same config succeeded (2× 11/11, 1× 10/11, 1× 9/11).

**Why:** If o4-mini is going to be a real option for this task it needs to be reliable. A ~20% silent-abort rate is not acceptable.

**Work:**
1. Capture the exact API response that led to the tool_result-as-terminal state. Might be a `length` finish reason, an empty content field, or the react loop not handling a specific stop_reason shape.
2. Check `agent_harness/loops/react.py` for how it terminates — does it require an assistant message with no tool_calls, or will it exit on other shapes?
3. Add a regression test.

**Note (2026-08-10):** o-series (o1/o3/o4) models, including o4-mini, are
now deliberately and completely unsupported by this framework (see
`docs/Progress_Tracker.md`, model-registry consolidation) — this item is
moot and can be dropped rather than investigated further.

---

### CLI REPL: bright single-letter prompt options (added 2026-08-10)

**What:** Permission/domain prompts show options like `[o]nce / allow for
[s]ession / ...` — the bracketed letter is the same style as the rest of
the line. Make just the letter bright/highlighted so the actual keystroke
needed stands out.

**Why:** Small readability win, user-reported. Confirmed easy —
`Console.input()` accepts a `Text` object for its prompt, so this is a
per-segment styling change using the same `Text`-composition pattern
already used for the markup-corruption fix earlier this session.

---

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

---

## Plausible Future Capabilities

### Parallel sub-agent fan-out (added 2026-04-16)

**Status:** Active roadmap design

**What:** Run multiple delegated agents in parallel, primarily for fan-out / adjudication workflows and execution-time improvements.

**Why:** This is the most plausible parallelism win for the harness. It may improve wall-clock time and unlock useful experimentation patterns without pushing concurrency into every part of the runtime.

**Scope in roadmap terms:** sub-agent fan-out first, not parallel tool calls inside a single turn.

**Deep-dive design:** `docs/streaming-plan.md`

### API / async boundary (added 2026-04-16)

**Status:** Active roadmap design

**What:** If an external API is ever added, keep async at the boundary and avoid pre-emptively converting the harness core.

**Why:** Async is a means to an end, not a feature. The main value would be serving external consumers cleanly, not making the core more complex.

**Scope in roadmap terms:** API later, boundary-first async only, sync core by default.

**Deep-dive design:** `docs/streaming-plan.md`

### MCP support (added 2026-04-16)

Connect agents to external tools via [Model Context Protocol](https://modelcontextprotocol.io/). Scope: MCP client in the harness, config to point at MCP servers, tools auto-discovered from server capabilities.

### Evaluation framework (added 2026-04-16, shipped 2026-08-03)

Run agents against test cases and score quality. Shipped as the `eval/` package — test case definitions, pluggable code + model graders with a gate/signal split, JSONL storage, and a ranked leaderboard. Replaces the ad hoc `scripts/run_experiment.py` pattern; `scripts/score_run.py`'s comparison logic was reused, not rewritten, as the `column_match` grader. Design doc: `docs/eval_framework.md`. Deferred: extending it to benchmark external coding assistants (Claude Code, Codex CLI, Copilot) via a `Subject` abstraction — captured in that doc, not built.

### Lazy tool schema loading (added 2026-04-16)

Send a compact list of tool names and descriptions first, then load full schemas on demand only when the model chooses a tool.

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

## Ideas

These are captured so they are not lost. They are not commitments.

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
static plan, not a living one.

**Completion detection — real weakness, checked directly.** `ralph.py`'s
"done" signal is the model saying the literal word `DONE` in its response
(`_DONE_MARKER`) — a self-report, not a verification. The loop never runs
the test suite itself and checks the result; it just believes the model.
Same category of problem as the JSON-fencing discussion — the loop has no
way to programmatically check its own work.

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
