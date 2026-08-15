# Features — what's actually built

Ground truth for what exists today, verified against the code (not
recalled from memory or conversation history). Companion to `docs/
roadmap.md`, which tracks what's planned but not yet built — if it's not
in this file, treat it as not shipped, even if it was discussed at length.

Regenerate/re-verify sections rather than trust this file blindly once
enough time has passed — it's a snapshot, not a live view.

---

## Providers & model access

- **Anthropic provider** (`providers/anthropic.py`) — Claude via the
  Messages API. Converts internal message format to Anthropic's content
  blocks (text, tool_use, tool_result, thinking), merges consecutive
  same-role messages (API requires strict alternation).
- **OpenAI provider** (`providers/openai_provider.py`) — one harness-facing
  provider hiding two real endpoints. Hosted models (`gpt-4o`, `gpt-4o-mini`,
  the `gpt-5.x` family) route through the Responses API by default;
  OpenAI-compatible `base_url` backends (LM Studio, etc.) use Chat
  Completions for compatibility. `o1`/`o3`/`o4` models explicitly excluded
  (unreliable per `docs/roadmap.md`'s open investigation).
- **Streaming** — both providers support `stream: true` (token-by-token via
  `on_delta`/`on_thinking_delta` callbacks). Anthropic: full support. OpenAI:
  Responses-API models only (`client.responses.stream()`); rejected with a
  clear error for Chat Completions/`base_url` backends, which aren't wired
  for it.
- **Extended thinking** (Anthropic only) — `provider_kwargs.thinking:
  {budget_tokens: N}` enables Claude's extended thinking. Validated
  (budget ≥1024, < max_tokens, incompatible with `temperature`/`top_p`).
  Thinking content captured in `Message.thinking`/`thinking_blocks`, hidden
  from the CLI by default (`show_thinking: false`), round-tripped correctly
  through multi-turn tool-use continuations.
- **Retry logic** (`providers/retry.py`) — shared across both providers.
  Exponential backoff (1s/2s/4s) on transient API errors, immediate failure
  with a clear message on auth errors, no retry on bad-request errors.
- **Cost tracking** (`budget.py` + `models.py`) — `models.py::MODEL_REGISTRY`
  is the single source of truth per `(provider, model)`: cost (input/output
  rates) and context-window limit together in one `ModelSpec`, replacing
  three previously-separate, independently-drifting tables (`COST_TABLE`,
  `_CONTEXT_LIMITS`, `_SUPPORTED_RESPONSE_MODELS`) — consolidated after a
  real bug where `o4-mini` had a priced `COST_TABLE` entry while the
  provider hard-rejected the model. `o1`/`o3`/`o4` (o-series) models are
  deliberately absent from the registry, not an oversight. `Budget` tracks
  cumulative turns and cost against `max_turns`/`max_cost`, exposes raw
  `.turns`/`.total_cost` properties and a `status_note()` ("You have N
  turn(s) remaining...") injected into the system prompt each turn via a
  disposable overlay — the persisted system message itself is never
  mutated.
- **Context trimming** (`context.py`) — per-model context-window limits;
  `trim_messages` drops oldest non-system messages once usage crosses 80%
  of the limit, always preserving the system message and most recent turns.

## Agent loops (orchestration patterns)

Seven interchangeable loop patterns, selected via `config.yaml: loop:`.

- **`react`** — standard reason/act/observe loop. Default for most agents.
  Includes a **thrash guard**, on by default (`config.yaml:
  thrash_threshold`, default 3; `<= 0` disables it): if the same tool
  errors that many times in a row, or is called with the exact same
  arguments that many times total in one run, an explicit nudge message
  ("this approach isn't working, try something different") is fed back to
  the model after the turn completes, and `LoopCallbacks.on_thrash_detected`
  fires (traced as `thrash_detected`). Detect-and-nudge only — no
  stop/escalate behavior; the loop continues exactly as before otherwise.
  Because `reflection`/`eval_optimize`/`plan_execute`'s step execution and
  `ralph`'s per-attempt execution all delegate to a react sub-loop, every
  loop gets this for free; `rewoo` has its own independent tool-execution
  path and doesn't (acknowledged gap, not yet built).
- **`plan_execute`** — plan once (numbered list, no tools), then a bounded
  (max 2 rounds) critique/refine round against the plan text itself (reuses
  `reflection`'s generate→critique→refine pattern; stops on a `DONE` marker
  or an unparseable critique, falling back to the last good plan rather
  than looping forever), then an optional human-approval gate
  (`LoopCallbacks.on_plan_approval`, inert unless a `plan_prompt_fn` is
  wired — CLI wires one by default) before executing each step via a react
  sub-loop, then summarize. Falls back to plain react if no plan steps
  parse.
- **`rewoo`** — plan once *with* tool calls, execute all of them, solve once
  with all results. Only 2 LLM calls total (vs. react's per-step calls).
- **`reflection`** — generate (react sub-loop) → critique (no tools) →
  refine → repeat until the critique contains `DONE` or `max_turns` hits.
  Completion detection is a self-report (model saying "DONE") unless
  `completion_check` is configured (see below), in which case a DONE claim
  must also pass the check before the loop stops.
- **`eval_optimize`** — same shape as reflection, but the critique produces
  a numeric `SCORE: N/10` against a pass threshold (7/10) instead of a
  DONE marker. Also honors `completion_check`.
- **`ralph`** — "Ralph Wiggum" loop: fresh context on every retry (only
  original system+user messages carried forward), retries until the
  response contains `DONE` or `max_turns` is hit. No sub-task tracking.
  Also honors `completion_check` — a failed check feeds back into the
  *same* attempt rather than starting fresh (discarding real failure
  feedback every time would defeat the point of checking at all); with no
  `completion_check` configured, behavior is unchanged from before. The
  outer retry loop also now stops promptly once the shared `Budget` is
  exceeded, rather than burning through remaining attempts.
- **`debate`** — two personas argue for/against a position across
  `max_turns` rounds, then a synthesis call reconciles them into one answer.

### Verified completion (`completion_check`)

Optional `config.yaml: completion_check: <string>` field (default unset —
fully inert, zero behavior change for any agent that doesn't set it).
Honored by `reflection`/`ralph`/`eval_optimize` only (a `logger.warning`
fires at load time if set on a loop that ignores it).

Resolution, always dispatched as a tool call through the normal
`on_tool_call` path (permissions/hooks/tracing apply exactly like any
other tool call — deliberate, e.g. `dangerous_command_blocker` still
protects a badly-configured check): if the string names one of the
agent's exposed tools, that tool is called with no arguments (a
completion-check tool must work with zero required arguments — "build a
tool, tell the agent to call it last" was already possible via
`instructions.md`; this is what makes it *enforced* rather than optional).
Otherwise the string is treated as a shell command and dispatched through
the built-in `run_command` tool.

Pass/fail convention, checked in order: a tool error → FAIL; output
starting with `PASS`/`FAIL` (case-insensitive) → that; a trailing
`[exit code N]` marker (`run_command` now always appends one, pass or
fail — previously it never read `result.returncode` at all, so a failing
shell command was indistinguishable from a passing one) → `N == 0`;
anything else → FAIL, not a silent pass.

On failure, the check's own output is fed back to the model as a user
message and the loop retries — bounded by the loop's existing
`max_turns`/`Budget` machinery, no separate unbounded retry path. A new
`LoopCallbacks.on_completion_status(verified, detail)` callback fires
once at the end of a run **only when `completion_check` is set**, wired
to a new `display.py::show_completion_status` line (green "Verified
complete" / red "NOT verified", mirroring `show_budget`'s shape) — this
closes a real gap: `cli.py` previously discarded a loop's return value
entirely, so nothing distinguished "stopped because verified" from
"stopped because budget ran out, unverified" in what the user actually
saw.

## Tools

**Built-in** (`tools.py`, always available):
- `read_file` / `write_file` — text only; `write_file` is whole-file
  overwrite.
- `edit_file(path, old_string, new_string)` — targeted, diff-style edit.
  Requires `old_string` to appear exactly once; errors clearly (no silent
  guessing) on zero or multiple matches. Added 2026-08-06, closing the
  "no targeted edit tool" gap.
- `view_image(path)` / `view_document(path)` — attach a real image/PDF as a
  vision/document content block on the *next* message, not just a text
  description. Matched by function *identity*, not name, in
  `execute_tool()` — an MCP server exposing its own same-named tool can't
  get misattributed. Only the most recently viewed attachment stays "live"
  in what's actually sent to the model (`attachments.py::prune_attachments`,
  same disposable-overlay pattern as the budget status note); canonical,
  session-persisted history keeps every attachment it saw, session
  round-tripping deliberately drops them (the file itself won't survive a
  resume anyway, since `tmp/` clears every run). See "Multimodal / file
  handling" below for the full picture, including agent-produced binary
  output.
- `web_fetch(url)` — fetches a URL and extracts main readable content via
  `trafilatura` (discards nav/ads/boilerplate, not just raw HTML→text).
  Falls back to raw page text if extraction finds nothing substantial.
  Wired into `network_exfiltration_blocker` — domain approval required
  same as `run_command`/`execute_code`.
- `web_search(query)` — Tavily-based search, returns title/url/snippet per
  result. Requires `TAVILY_API_KEY`. Also gated by
  `network_exfiltration_blocker` (fixed domain, `api.tavily.com`).
- `list_provider_models(provider)` — queries the vendor's live
  `models.list()` API directly (Anthropic/OpenAI SDKs), not any of the
  harness's internal lists. Added 2026-08-10 for `agent_budgets`: an
  internal "supported models" list can't discover a model missing from
  itself, so pricing-verification scope needs a source outside the
  artifact being checked. Does not affect `_SUPPORTED_RESPONSE_MODELS`
  (`openai_provider.py`), which remains the real runtime compatibility
  gate — a different question ("can this harness correctly call this
  model") from "does this model currently exist at the vendor." Gated by
  `network_exfiltration_blocker` (`api.anthropic.com`/`api.openai.com`).
- `list_directory`, `run_command` (shell, with timeout), `execute_code`
  (python/bash execution).
- `save_memory` / `recall_memory` / `list_memories` — see Memory below.
- `run_agent` — delegate a task to a named sub-agent (see Multi-agent below).

**Custom tools** (project-level `tools/`, auto-discovered):
- `profile_data` — column profiling for CSV/Excel (pandas-based): types,
  sample values, date-pattern detection, multi-encoding CSV fallback.
- `value_overlap` — pairwise sample-value overlap between two data files,
  surfaces high-confidence column-match candidates deterministically.
- `file_search` — glob-pattern file finder (filename/path only).
- `content_search(pattern, directory)` — grep-equivalent: regex search
  across file *contents*, recursive, `path:line: text` results. Pure
  Python (`re`+`Path.rglob`), no external binary dependency. Added
  2026-08-06, closing the "no content search" gap.
- `word_count` — trivial reference example for the custom-tool convention.

**Discovery mechanism** (`tools.py::discover_tools`) — drop a `.py` file
with one public, type-annotated function into `tools/`; auto-registered by
function name. Built-ins can't be overwritten by custom tools with the
same name.

## MCP client support (`mcp_client.py`)

Agents can consume external MCP (Model Context Protocol) servers as tools —
client only, the harness doesn't expose itself as an MCP server. Config:
`config.yaml`'s `mcp_servers:` list (name/command/args/env per server),
same pattern as `hooks`/`permissions`.

- **`McpManager`** — the sync/async bridge. FastMCP's client (the chosen
  package, via `fastmcp-slim[client]`) is asyncio-native with no sync API,
  same as the official `mcp` SDK, so `McpManager` runs one persistent
  background thread and event loop per run, holding each configured
  server's stdio subprocess connection open for the whole run (spawned
  once, reused for every call, not respawned per tool call) behind a plain
  synchronous `list_tools`/`call_tool`/`close` surface.
- **Tool merging** (`runtime.py::_start_mcp_manager`) — every discovered
  MCP tool is auto-included in `tool_schemas`, not gated by `config.tools`
  (the point of "auto-discovered" is the agent author doesn't hand-
  enumerate them). **Collision policy**: a name already exposed via this
  agent's own `config.tools` wins — MCP's version of that name is skipped.
  A name *not* exposed by this agent (even if it exists as an unexposed
  built-in elsewhere in the registry) is not blocked — MCP fills the gap.
  Two MCP servers offering the same tool name: first one registered wins,
  the rest are skipped. This means an agent author can "claim" any given
  tool name for the harness's own implementation at any time just by
  adding it to `config.tools` — no MCP config change needed.
- **Fail-fast per dead server** — a normal tool-level error (bad args,
  `fastmcp.exceptions.ToolError`) flows back to the model exactly like any
  other tool error, unchanged. A transport-level failure (server
  subprocess crashed, pipe broken — any other exception type) marks that
  server dead; every subsequent call to it fails immediately with a clear
  message instead of repeating a doomed round-trip until the budget runs
  out.
- Every MCP tool call still flows through the existing `on_tool_call`
  callback (hooks, permissions, tracer) for free — it's just another entry
  in the same `tool_registry`.
- Scope: stdio (local subprocess) transport only, tools capability only.
  No HTTP/SSE remote servers, no MCP server mode, no resources/prompts/
  sampling — see `docs/roadmap.md`'s "Scoped out of MCP client support"
  backlog for what was deliberately cut and why.

## Multimodal / file handling (`attachments.py`)

Full PRD + as-built spec in `docs/multimodal-plan.md`. Two capabilities:

- **Vision/document input** — `view_image(path)` / `view_document(path)`
  (see Tools above) read a file, detect its media type from magic bytes
  (PNG/JPEG/GIF/PDF signatures, stdlib-only, no new dependency), and the
  harness attaches it as a real provider-native content block on the
  *next* message — Anthropic `image`/`document` blocks, OpenAI Responses
  API `input_image`/`input_file`. Attachments are a **separate synthetic
  message following the tool result**, never fused into the tool_result
  block itself — necessary because both OpenAI translation paths (Chat
  Completions and Responses) are string-only for tool output, so the same
  uniform treatment applies to Anthropic too rather than relying on an
  unverified provider-specific quirk.
- **Agent-produced binary output** — any tool (built-in, custom, or MCP)
  that creates fresh binary content it hasn't already written to disk can
  hand it back via `attachments.py::wrap_binary_output` — embeds
  base64+filename in its ordinary string output. `execute_tool()` detects
  this convention on every call, decodes it, guardrails it (filename must
  be a bare basename — not the same check as `hooks.py`'s path-traversal
  detector, which deliberately exempts absolute paths for a different,
  narrower purpose and would be unsafe reused here; size cap; decoded
  bytes' magic-byte signature must match the claimed media type), and
  saves it to `{agent_dir}/tmp/`, replacing the envelope with a short text
  reference (`"[saved: chart.png (image/png, 42KB) -> tmp/chart.png]"`)
  before it ever enters persisted history or the CLI display. Extraction
  runs strictly *before* `execute_tool`'s output truncation, so a large
  base64 payload can't get corrupted first.
- **`{agent_dir}/tmp/`** — cleared once at the start of each run
  (`runtime.py::prepare_runtime`, mirrors `eval/runner.py::_clear_memory`'s
  "fresh state per run" precedent), gitignored (`**/tmp/`). Not session-
  persisted (`session.py` deliberately unchanged) — a saved file wouldn't
  survive a session resume in a new process anyway, since `tmp/` clears
  every run; on resume, prior attachments round-trip as `None`, which is
  correct, not a gap.
- **Provider/model capability** — deliberately not pre-validated against a
  harness-maintained "which models support vision" table (same lesson as
  the `COST_TABLE`/o4-mini drift bug — a second stale table would be the
  same failure shape). The provider API is the source of truth; an
  unsupported combination surfaces as a normal `RuntimeError` (via
  `providers/retry.py`, which now wraps `BadRequestError` instead of
  letting it propagate raw — a real, general fix this feature's policy
  depended on, since before it any bad request crashed the whole process
  with an unhandled traceback). One deliberate exception: OpenAI Chat
  Completions (`base_url`/OpenAI-compatible backends) has no PDF/file
  content type at all, which is known ahead of time, not genuine per-model
  variance — a `view_document` attachment there becomes an in-band text
  note instead of a raw API rejection.
- Verified live against the real Anthropic API (correct color/order
  description of a real generated image — proof of genuine visual
  perception, not a guess) and a real local OpenAI-compatible LM Studio
  server (both the deterministic Chat-Completions note and a genuine live
  provider rejection surfacing cleanly, not crashing).

## Safety, permissions & hooks

- **Tool permissions** (`permissions.py`) — three-tier: `always_allow`,
  `always_ask`, and a prompt-and-remember tier (once / for the session /
  persistently, saved to `.permissions.yaml`). **Inert by default** — an
  agent with no `permissions:` config block allows every tool with no
  prompting.
- **Default safety hooks** (`hooks.py`) — on regardless of permission
  config, unless an agent explicitly overrides `before_tool`/`after_tool`:
  - `dangerous_command_blocker` — blocks `rm -rf`, `sudo`, `mkfs`, `dd if=`,
    redirects to `/dev/`, in `run_command`.
  - `path_traversal_detector` — blocks path-like tool arguments that
    resolve outside the workspace root.
  - `network_exfiltration_blocker` (`network.py`) — domain-allowlist for
    network-capable commands/code (`curl`, `wget`, `requests`, `urllib`);
    interactive per-domain approval, persisted to
    `{agent_dir}/.allowed_domains.yaml`.
  - `injection_scanner` — scans tool *output* for prompt-injection patterns
    ("ignore previous", etc.), wraps matches in an `[EXTERNAL CONTENT
    WARNING]` marker. Flags, doesn't block. Three narrow regex patterns.
  - `secrets_leakage_scanner` — redacts known secret shapes (API-key
    prefixes, private-key headers) from tool output before it reaches the
    LLM. Narrow pattern list, not a general secret detector.
- **Cascading depth limit** (`routing.py`) — `max_agent_depth = 3` caps
  runaway recursive sub-agent delegation regardless of permission config.
- **Memory injection scan** — `save_memory` independently re-runs the
  injection pattern scan before persisting content to a memory file.

## Memory & sessions

- **Agent memory** (`memory.py`) — flat markdown files under
  `{agent_dir}/memory/{key}.md` via `save_memory`/`recall_memory`/
  `list_memories`. No automatic memory — the LLM decides what to save, and
  content is scanned for injection patterns first. No semantic search —
  purely list/read by exact key.
- **Session persistence** (`session.py`) — full conversation history
  (including tool calls/results, thinking blocks) serialized to JSON via
  `--session <name>`, resumable across CLI invocations. Corrupted/malformed
  session files fail safe (start fresh, don't crash).

## Observability

- **Structured tracing** (`trace.py`) — one JSONL file per run under
  `{agent_dir}/logs/`, timestamped events (`user_prompt`, `turn`,
  `tool_call`, `tool_result`, `tool_blocked`, `tool_denied`, `budget`,
  `context_loaded`). Inert (no-op) when tracing is disabled — used for
  delegated sub-agent runs (`run_agent`/`handoff_agent`) to avoid noise.
- **Logging** (`log.py`) — console + optional per-day file logging under
  `{agent_dir}/logs/`, structured format (timestamp, level, module,
  function, line, message). `--verbose` flips console level to DEBUG.

## Multi-agent delegation

- **`run_agent(agent_name, message)`** (`routing.py`) — fresh conversation
  with a named sub-agent, returns its final text. Depth-limited, traced-off
  by default (non-interactive: `deny_permission`, `show_output=False`).
- **`handoff_agent(agent_name, messages)`** — hands off the *existing*
  conversation history to another agent rather than starting fresh.
- No parallel fan-out yet (sequential only) — see `docs/roadmap.md`.

## Skills

- **`skills.py`** — markdown files (`SKILL.md` inside a named directory)
  auto-loaded into an agent's system prompt. Two tiers: shared (`skills/`
  at project root) and agent-local (`{agent_dir}/skills/`), with agent-local
  overriding shared skills of the same directory name.

## Configuration & CLI

- **Agent = folder** (`config.py`) — `config.yaml` + `instructions.md` +
  optional `tools.md`, loaded via `agent_harness.config.load()`.
- **`config.yaml` fields**: `provider`, `model`, `tools` (list), `loop`,
  `max_turns`, `max_cost`, `executor`, `tool_timeout`, `max_output_chars`,
  `provider_kwargs` (temperature, top_p, max_tokens, thinking, base_url,
  reasoning_effort), `permissions`, `hooks`, `stream`, `show_thinking`,
  `mcp_servers` (list of `{name, command, args, env}` — see "MCP client
  support" above), `completion_check` (see "Verified completion" above),
  `thrash_threshold` (see "Agent loops" above — on by default, 3).
- **CLI** (`cli.py`) — `agent-harness run <dir> [prompt]` (single-shot or
  REPL if no prompt), `agent-harness init <name>` (scaffold a new agent).
  Per-run overrides for every major config field via flags (`--provider`,
  `--model`, `--temperature`, `--stream`, `--show-thinking`, etc.).
- **Scaffolding** (`scaffold.py`) — `init` generates a minimal
  `config.yaml`/`instructions.md`/`tools.md` template, ready to run.
- **Validation** (`runtime.py::validate_config`) — rejects unknown
  provider/tool/loop names, `max_turns < 1`, `stream`/`thinking` on
  providers that don't support them (only `anthropic` + `openai` for
  stream, `anthropic` only for thinking) at load time, before any API call.

## Evaluation framework (`eval/`)

Sibling package, not part of `agent_harness` itself — a consumer of the
framework, same relationship as `scripts/` has to it.

- **Test cases** (`eval/cases.py`) — one YAML file per case: id, target
  agent, prompt (supports `{cell_id}`/`{run_index}` templating), one or
  more graders, optional `output_file` (for agents whose real output is a
  file, not their chat reply).
- **Cells** (`eval/cases.py::load_cells`) — named configuration variants:
  override `instructions` (swap in alternate `instructions.md` content),
  `provider`, `model`, `temperature` per cell, run the same case suite
  against each.
- **Graders** (`eval/graders/`) — two kinds, tagged `gate` or `signal`:
  - **Code graders**, auto-discovered from `eval/graders/code/` (same
    one-file-one-function convention as tools). Built in: `contains`
    (substring match), `column_match` (reuses `scripts/score_run.py`'s
    comparison logic — correct/false-positive/missed-match counting).
  - **Model grader** (`eval/graders/model.py`) — LLM-as-judge. Rubric in,
    PASS/FAIL verdict out, independently configurable judge
    provider/model.
  - **Gate/signal split**: gate (code) graders are disqualifying — a cell
    failing any gate never outranks one that passes, regardless of signal
    score. Signal (model) grader only ranks among cells that already
    cleared every gate.
- **Runner** (`eval/runner.py`) — drives real `agent_harness` execution
  (`prepare_runtime`, non-interactive), applies cell overrides, clears
  agent memory between repeats (independent trials), reads the configured
  output file if set, grades, returns a structured `RunResult`.
- **Storage** (`eval/storage.py`) — JSONL as source of truth (one line per
  run, full structured detail), CSV as a derived/regenerable projection
  for spreadsheet use.
- **Report** (`eval/report.py`) — aggregates JSONL into a per-cell
  leaderboard (gate pass rate, stdev, mean signal score, mean cost/turns),
  lexicographic ranking (not a blended score), disqualified cells always
  sort last regardless of ranking order. Rendered via `rich.table` or
  markdown.
- **CLI** (`eval/cli.py`) — `python -m eval run <cases-dir> --cells
  <file.yaml> --repeats N --out results.jsonl`, `python -m eval report
  results.jsonl --rank gate,stdev,signal,cost`.
- **What it replaced**: `scripts/run_experiment.py` (still present,
  column-matcher-specific, subprocess+regex-based) — not deleted, but the
  eval framework is the general-purpose successor.

## Example agents (`agents/`)

Eleven example agents demonstrating different loop patterns: `hello`
(react, general assistant — also configured with an `mcp_servers:` entry
pointing at the reference `@modelcontextprotocol/server-filesystem` via
`npx`, so it's the live MCP-support demo alongside being the general
assistant), `hello-local` (react via LM Studio), `csv-analyser` (react +
pandas tools), `analyst` (reflection), `reviewer` (eval_optimize),
`persistent-coder` (ralph), `orchestrator` (react + `run_agent`
delegation), `column-matcher` / `column-matcher-reflective` (the
pension-data column-matching task, react vs. reflection variants),
`local-coder`.

- **`agent_budgets`** (react + `read_file`/`content_search`/
  `list_provider_models`/`web_fetch`/`web_search`/`edit_file`) —
  dogfooding demo: verifies `budget.py::COST_TABLE` against real published
  vendor pricing. Provider scope derives from `providers/__init__.py`'s
  registry; model scope derives from `list_provider_models` (the vendor's
  live API), not from any of the harness's own internal lists —
  `content_search` across `COST_TABLE`/`_CONTEXT_LIMITS`/
  `_SUPPORTED_RESPONSE_MODELS` is now used only for cross-table
  consistency checking, not scoping. `permissions: always_ask: [edit_file]`
  — proposes fixes, never applies them without human approval. Verified in
  two real runs: 2026-08-06 (content_search-scoped version) correctly
  found the known `o4-mini`/`_CONTEXT_LIMITS` cross-table gap, fetched
  real pricing, proposed two edits that correctly paused for approval, and
  declined to guess on an ambiguous model-version case; 2026-08-10
  (`list_provider_models`-scoped version) surfaced substantially more —
  current vendor models like `gpt-4.1`/`gpt-5` and several current Claude
  models that don't appear anywhere in this codebase, which the earlier
  content-search-only scoping could never have found.

## What's explicitly NOT built (see `docs/roadmap.md` for detail)

No RAG/embeddings/vector store. No audio/video content (image and PDF
vision/document support exists — see "Multimodal / file handling" above).
No MCP *server* mode (client support exists — see "MCP client support"
above); no HTTP/SSE remote MCP servers, stdio only. No parallel sub-agent
fan-out — deliberately deferred to a future "async phase" rather than
scheduled as a one-off, alongside the API/async-boundary item, since
there's still no concrete driving use case in this repo (`orchestrator`
calls `run_agent` serially). No structured HTTP/API request tool (distinct
from `web_fetch`, which reads pages, not JSON APIs). No browser
automation. No messaging/notification tool. No prompt caching (deliberately
delayed until agents exist with a big enough tool/instruction footprint and
enough turns to clear the provider's cache-block minimum and recoup the
write-cache premium). No adaptive/dynamic re-planning — `plan_execute`'s
critique/refine round revises the plan text once or twice before
execution starts, but nothing re-plans mid-execution. No CLI-level
type-ahead tool invocation or no-Enter-keypress prompts (both need the
same raw-terminal-input infrastructure, flagged as one future "REPL input
upgrade" rather than two separate builds) — plain `!`-prefixed inline
shell commands are a smaller, separable, still-unbuilt item. No todo-list
mechanism for long tasks. No async/API layer
(FastAPI/SSE) — CLI
only. **No PII detection/redaction of any kind** — `secrets_leakage_scanner`
only matches API-key-shaped strings (`sk-`/`ghp_`/`AKIA`/private-key
headers); names, addresses, DOBs, SSNs pass through completely unfiltered.
Concretely real, not hypothetical: `column-matcher` handles actual pension
data (DOB, gender, participant status) via `profile_data`/`value_overlap`
only.
