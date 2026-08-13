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

---

## Plausible Future Capabilities

**Build order (decided 2026-08-13, updated 2026-08-13 after MCP shipped):**
1. ~~Step-level evidence for evals~~ — **delayed** before being designed;
   see its entry below for why (same "no real driving case yet" call as
   prompt caching).
2. ~~MCP client support~~ — **shipped 2026-08-13**, see Done below.
3. **Next up:** Parallel sub-agent fan-out — real value but pushes
   concurrency into a deliberately synchronous core; wait until there's a
   concrete driving use case (none in this repo today — `orchestrator`
   calls `run_agent` serially) and until evals/MCP give something worth
   measuring and fanning out.
4. Image handling / multimodal — biggest lift on the list; build when
   something concrete needs vision, not speculatively.

Not part of the sequence: **API/async boundary** is a standing design constraint ("if an API is ever added, keep async at the boundary"), not a buildable task — it activates only if something else creates a reason for an external API. **Lazy tool schema loading** doesn't clear this file's own benefit-vs-complexity bar (see its entry below) and isn't scheduled.

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

### Parallel tool-call execution within a turn

Today (with or without MCP) a turn's tool calls execute one at a time,
sequentially. **Cut from the MCP work specifically:** it's a loop-level
change (`loops/react.py`/`loops/common.py`), not an MCP-client concern —
built-in tools would benefit exactly as much as MCP ones, so it belongs in
its own item, not bolted onto this one.

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

### CLI REPL: bright single-letter prompt options (added 2026-08-10, resolved 2026-08-13)

New `_highlight_choices()` helper in `cli.py`: regex-finds each `[x]`-bracketed choice in a static prompt hint and styles the bracketed content `bold cyan`, leaving the brackets and surrounding text unstyled. Wired into all three prompts that use this pattern — `_permission_prompt` (`[o]nce / allow for [s]ession / allow [p]ersistently / [d]eny?`), `_domain_prompt`, and `_plan_prompt` (both `[y/n]`). Returns a `Text` object, so it's structurally immune to markup parsing regardless of the `markup` flag — same safety property as the earlier markup-corruption fix, though not itself a fix (these three hint strings are static, not dynamic content). Verified with a real ANSI-rendering check (`Console(force_terminal=True)`), confirming the `1;36` (bold cyan) escape codes land exactly on `o`/`s`/`p`/`d` and `y/n`, nothing else.

### MCP client support (added 2026-04-16, resolved 2026-08-13)

Agents can now consume external MCP servers as tools — client only, not server (see the new "Scoped out" backlog section above for that and other deliberately-cut pieces). New `agent_harness/mcp_client.py::McpManager`: since the chosen client package (FastMCP, via `fastmcp-slim[client]`) is asyncio-native with no sync API — confirmed true of the official `mcp` SDK too, checked directly rather than assumed — `McpManager` runs one persistent background thread and event loop for the whole run, holding each configured server's connection open (subprocess spawned once, reused for every call, not respawned per tool call) and exposing a plain synchronous `list_tools`/`call_tool`/`close` surface so the rest of the harness never touches asyncio.

New `AgentConfig.mcp_servers` (`config.yaml`'s `mcp_servers:` list, same pattern as `hooks`/`permissions`). `runtime.py::prepare_runtime` starts the manager, merges every discovered tool into the existing `tool_registry`/`tool_schemas` — auto-included, not gated by `config.tools`, since the point of "auto-discovered" is the agent author doesn't hand-enumerate them. Every MCP tool call still flows through the existing `on_tool_call` callback (hooks, permissions, tracer) for free, since it's just another entry in the same registry.

**Collision policy corrected same-day, from real usage, not a code review catch.** Shipped checking MCP tool names against the *entire* tool registry (everything built-in/custom that exists anywhere), matching `discover_tools`'s convention — but user caught via live use of `agents/hello` (which only exposes `read_file`/`run_command`/`execute_code` in `config.tools`) that this was wrong: `write_file`/`edit_file`/`list_directory` are real built-ins, so their MCP equivalents got silently skipped even though `hello` never opted into the built-in versions — leaving all three tool names completely inaccessible, neither built-in nor MCP. Fixed: the check is now against `config.tools` (what this agent actually exposes to the model) plus names already claimed by an earlier MCP server in the same merge (still guards against two MCP servers offering the same tool name) — not the full registry. This means a locally-unclaimed name always resolves to MCP automatically, and an agent author can "claim" any given name for the harness's own (safer/vetted) implementation at any time just by adding it to `config.tools` — no MCP config change needed. TDD: two new tests lock this in (`test_mcp_tool_not_exposed_by_agent_is_not_skipped`, `test_two_mcp_servers_offering_same_tool_name_second_is_skipped`), verified live against `hello` before and after.

**Fail-fast per dead server:** distinguishes a tool-call mistake the agent can self-correct (bad args — `fastmcp.exceptions.ToolError`, flows back to the model as a normal recoverable tool error, unchanged) from an unsurvivable transport failure (server subprocess crashed/pipe broken — any other exception type) — the latter marks that server dead so every subsequent call fails immediately with a clear message instead of repeating a doomed round-trip until the budget runs out.

**Package choice revised mid-planning, not the first instinct:** started with the official `mcp` SDK as the safe default. User's first reason for FastMCP ("we'll use FastAPI later, so synergy") didn't survive a direct check — FastMCP is built by Jeremiah Lowin/PrefectHQ, no relation to FastAPI's author — said so rather than going along with it. The real deciding factor, raised by the user: they intend to build an MCP *server* at some future point, and FastMCP's own docs confirm the slim client and full packages "use the same importable package... application code remains identical regardless of the chosen installation method" — so starting on `fastmcp-slim[client]` now makes that later transition an install-only change. Turned out heavier than hoped in practice (`[client]` transitively pulls in the full `mcp` SDK plus `starlette`/`uvicorn`/`authlib`/`keyring`/`cryptography` — auth/HTTP machinery for a remote-transport path this build doesn't use) — flagged transparently, didn't change the decision, since the deciding argument was migration cost, not dependency weight.

Verified live against the real reference `@modelcontextprotocol/server-filesystem` (via `npx`) at every level: unit tests mock the FastMCP boundary; `tests/integration/test_mcp_real.py` runs the actual stdio server with zero mocks (skips cleanly if `npx` is absent); a manual run of a throwaway agent against the live Anthropic API showed the model correctly discovering and calling the MCP-provided `read_text_file` tool, getting real file content back, and answering correctly — with the built-in-name-collision skip (`read_file`/`write_file`/`edit_file`/`list_directory`) firing exactly as designed in the same run. Confirmed no orphaned `npx`/node processes survive after the harness process exits.

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
