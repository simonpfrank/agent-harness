# Agent Harness

Minimal agent framework — agents as markdown folders and possible scripts. Inspired by Skills and things like OpenClaw. Intended to make it easy to create and run agents quickly. This is probably alpha quality at this stage, but all tests pass and many agent types are run in integration tests. Most docs are AI written and iterated all code is AI written and not yet reviewed.

As a summary, be able to run an agent in a cli, and if it needs more inputs just using a simple input() ui. Define it in markdown, add skills, add tools, add a different provider if not there etc. The approach is deliberately simple with as flat an architecture as possible to make it easy to modify and keep code as low as practical.

### Features

- **Agent = folder** — `instructions.md` + `config.yaml` + optional `tools.md`. Copy it, share it, version it.
- **7 loop patterns** — ReAct, Plan-and-Execute (with a plan critique/refine round and an optional human-approval gate), ReWOO, Reflection, Evaluator-Optimizer, Ralph Wiggum, Debate
- **2 providers** — Anthropic (Claude) and OpenAI/LM Studio, with shared retry logic. Add your own in one file.
- **MCP client support** — consume external MCP servers (stdio) as tools, auto-discovered, alongside your own built-in/custom tools; a server can optionally declare a `tools:` allow-list to expose only some of what it offers
- **Browser automation** — accessibility-tree-based (not screenshots) via Microsoft's `@playwright/mcp`, with domain-approval gating that catches off-domain link clicks and redirects, not just explicit navigation; ephemeral browser profile by default, real profile as an explicit opt-in. See `agents/browser-assistant/`.
- **Vision and document support** — `view_image`/`view_document` tools let an agent genuinely see an image or PDF it has a path to; tools can hand back freshly-generated binary content too
- **Core built-in tools** — file read/write/edit, shell commands, code execution, web fetch/search, live vendor model listing, vision/document viewing, plus memory/routing tools (see [Built-in Tools](#built-in-tools) below for the full list)
- **5 safety hooks on by default** — dangerous command blocking, path traversal, network exfiltration, injection scanning, secrets redaction
- **Custom tools** — drop a Python file in `tools/`, list it in config, done
- **Skills** — markdown knowledge files loaded into agent context automatically (shared and agent-local)
- **Sessions** — save/resume conversations across restarts
- **Memory** — agents decide what to remember via `save_memory`/`recall_memory` tools
- **Agent routing** — agents delegate to other agents via `run_agent` tool with independent budgets
- **Shared runtime path** — CLI runs and `run_agent` sub-agents use the same prompt assembly, hooks, permissions, tracing, and tool wiring
- **CLI config overrides** — `--provider`, `--model`, `--loop`, `--max-turns` etc. without editing files
- **Structured traces** — JSONL files with full conversation replay (prompts, responses, tool I/O)
- **Budget enforcement** — turn limits and cost ceilings, deterministic (never exceeded), with a live "turns/cost remaining" note injected each turn
- **Real cancellation** — Ctrl-C (CLI) or a Stop button (API/Streamlit) actually stops a run mid-turn, not just at the end (turn-boundary + mid-stream checkpoints); mid-tool-call kill isn't built yet
- **Pluggable executor** — swap subprocess for Docker or any other sandbox
- **Context window management** — automatic trimming when approaching model limits
- **Scaffold command** — `agent-harness init my-agent` creates a ready-to-run agent
- **Evaluation framework** (`eval/`) — run agents against test-case suites, gate/signal graders, ranked leaderboards

See `docs/prd.md`, `docs/architecture.md`, `docs/spec.md`, and `docs/features.md` (verified-against-code feature inventory) for full details.

## Quick Start
Clone the repo.
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and add your API key:

```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and/or OPENAI_API_KEY
```

Run an agent:

```bash
python -m agent_harness run ./agents/hello "What files are in this directory?"

# Or with pip install:
agent-harness run ./agents/hello "What files are in this directory?"
```

Interactive REPL (no prompt argument):

```bash
python -m agent_harness run ./agents/hello
```

Override any config setting without editing the file:

```bash
python -m agent_harness run ./agents/hello "hi" --provider openai --model gpt-4o-mini
python -m agent_harness run ./agents/analyst "count files" --loop react --max-turns 3
```

## How It Works

An agent is a folder containing:
- `config.yaml` — provider, model, tools, budget limits, safety config
- `instructions.md` — system prompt (what the agent does)
- `tools.md` (optional) — guidance on tool usage

The runtime loads the config, builds a per-run tool registry, assembles the full system prompt, applies safety hooks and permissions, and runs an agent loop. CLI execution and `run_agent` delegation go through the same runtime path, so sub-agents see the same `instructions.md`, `tools.md`, and skills as standalone runs. Seven loop patterns are available:

| Loop | Config value | Pattern |
|------|-------------|---------|
| ReAct | `react` (default) | Think → Act → Observe → repeat |
| Plan-and-Execute | `plan_execute` | Plan all steps → execute each → summarise |
| ReWOO | `rewoo` | Plan once → execute all tools → solve (2 LLM calls) |
| Reflection | `reflection` | Generate → critique → refine until satisfied |
| Evaluator-Optimizer | `eval_optimize` | Generate → score → improve until threshold |
| Ralph Wiggum | `ralph` | Run → check done → discard and retry fresh |
| Debate | `debate` | Two perspectives argue → synthesise |

See `docs/agentic-design-patterns.md` for full descriptions and flow diagrams.

```
types.py (root — dataclasses only)
  ↓
attachments.py, tools.py, budget.py, models.py, hooks.py, permissions.py, providers/*, config.py
  ↓
mcp_client.py, runtime.py (shared execution setup)
  ↓
cli.py / routing.py
```

## Safety and Security

**This section is important. Read it before running agents unsupervised.**

Agent Harness includes five built-in safety hooks that filter tool calls and scan output. Three are on by default. Understanding what they do and don't do and adding more is your responsibility.

### Default-on hooks (active with zero config)

| Hook | Type | What it does | What it does NOT do |
|------|------|-------------|-------------------|
| `dangerous_command_blocker` | before tool | Blocks `rm -rf`, `sudo`, `mkfs`, `dd if=`, writes to `/dev/` | Does not catch every destructive command. A determined or creative LLM can find other ways to cause damage (e.g. `find / -delete`, overwriting files with `>`, Python `os.remove`). |
| `path_traversal_detector` | before tool | Checks path-like args such as `path`, `working_dir`, and `directory`, and blocks relative paths that escape the workspace | It does not inspect arbitrary command/code text, and it is not a full filesystem sandbox. Absolute paths and symlink tricks are still outside its protection scope. |
| `network_exfiltration_blocker` | before tool | Blocks `curl`, `wget`, `nc`, `ncat` in commands and `requests`/`urllib`/`http.client` in code | Only matches known command names and Python modules. Does not block network access via `socket`, compiled binaries, or less common tools. Does not inspect actual network traffic. |

### Default-on hooks (output scanning)

| Hook | Type | What it does | What it does NOT do |
|------|------|-------------|-------------------|
| `injection_scanner` | after tool | Wraps output containing `ignore previous`, `system:`, or `<\|im_start\|>` with `[EXTERNAL CONTENT WARNING]` | Only matches a small set of known injection patterns. Novel injection techniques will bypass it. The warning goes to the LLM, which may still follow injected instructions. |
| `secrets_leakage_scanner` | after tool | Redacts patterns matching API keys (`sk-*`, `ghp_*`, `AKIA*`) and private keys before output reaches the LLM | Only matches known key formats. Custom tokens, passwords, database connection strings, and other secrets with non-standard formats will pass through unredacted. |

### What the hooks are NOT

- **Not a sandbox.** The agent runs tools with your user's full permissions. Hooks are pattern-matching filters, not a security boundary.
- **Not comprehensive.** They catch common mistakes and known-bad patterns. They do not make an agent "safe" in any absolute sense.
- **Not a substitute for review.** If your agent does anything consequential (writes files, runs commands, accesses APIs), you should review its actions.

### Additional protections

- **Memory poisoning defence**: Content saved via `save_memory` is scanned for injection patterns. Suspicious content is prefixed with a warning before being stored.
- **Cascading failure protection**: `run_agent` has a depth limit (default 3). Agent A calling Agent B calling Agent C is fine; deeper nesting raises an error.
- **Credential scoping**: Sub-agents load their own `config.yaml`. Give sub-agents a restricted tool list — don't give an orchestrator's sub-agents tools they don't need.

### Domain whitelist (network blocker)

When the network blocker detects a URL, it extracts the domain and checks a whitelist. If the domain isn't listed, you'll be prompted:

```
Allow network access to api.weather.com? [y/n]
```

Approved domains are saved to `{agent_dir}/.allowed_domains.yaml` and not asked again. Three ways to whitelist domains:

1. **Config** — pre-approve in `config.yaml`:
   ```yaml
   hooks:
     allowed_domains: [api.weather.com, httpbin.org]
   ```
2. **Interactive** — prompted at runtime, automatically persisted
3. **Manual** — edit `.allowed_domains.yaml` directly

### Opting out of hooks

All hooks can be overridden in `config.yaml`. To disable specific hooks, set the list explicitly:

```yaml
hooks:
  # Only keep the dangerous command blocker, disable all others
  before_tool: [dangerous_command_blocker]
  after_tool: []
```

To disable all hooks entirely:

```yaml
hooks:
  before_tool: []
  after_tool: []
```

### Permissions

Tool permissions are **off by default** (all tools allowed). To enable, add a permissions section to `config.yaml`:

```yaml
permissions:
  always_allow: [read_file]           # never prompted
  always_ask: [run_command]           # prompted every time
  # tools not in either list: prompt decides once/session/persistent
```

Prompt choices now map directly to behavior:
- `once` — allow this call only
- `session` — remember until the current process exits
- `persistent` — save approval to `{agent_dir}/.permissions.yaml`
- `deny` — reject the call

Sub-agent runs are non-interactive. If a delegated agent reaches a tool call that needs prompting and has no saved approval, the call is denied instead of hanging for terminal input.

## Creating an Agent

Scaffold a new agent:

```bash
python -m agent_harness init my-agent
```

This creates `agents/my-agent/` with `config.yaml`, `instructions.md`, and `tools.md` — ready to run immediately. Edit the instructions to change what your agent does.

Or create one manually:

```bash
mkdir agents/my-agent
```

`agents/my-agent/config.yaml`:
```yaml
name: my-agent
provider: anthropic
model: claude-haiku-4-5-20251001
tools: [run_command, read_file, execute_code]
max_turns: 10
max_cost: 0.10
```

`agents/my-agent/instructions.md`:
```markdown
You are a helpful assistant. Be concise.
```

## Custom Tools

Add your own tools in the project-level `tools/` directory. One Python file per tool, one public function with type hints:

```python
# tools/word_count.py
def word_count(text: str) -> str:
    """Count the number of words in the given text.

    Args:
        text: The text to count words in.
    """
    return str(len(text.split()))
```

List the tool in your agent's config to make it available:

```yaml
tools: [run_command, read_file, word_count]
```

Custom tools are discovered at startup. Built-in tools cannot be overwritten.

## Skills

Skills are markdown files describing how to approach tasks. They're automatically loaded into the agent's system prompt.

```
skills/                          # Shared across all agents
  csv-analysis/
    SKILL.md                     # Loaded into prompt
    scripts/
      validate.py                # Agent invokes via tools
agents/my-agent/
  skills/                        # Agent-specific (overrides shared by name)
    specialised-task/
      SKILL.md
```

**Shared skills** in `skills/` are available to all agents. **Agent-local skills** in `{agent_dir}/skills/` override shared skills with the same directory name. No config needed — presence in the folder = active.

## Example Agents

| Agent | Loop | What it does |
|-------|------|-------------|
| `hello` | react | General assistant — tools, code execution, the strawberry test. Also configured with a real MCP server (`mcp_servers:`), so it doubles as the live MCP demo. |
| `csv-analyser` | react | Analyses the included sales.csv dataset with pandas |
| `analyst` | reflection | Data analysis with self-critique and refinement |
| `reviewer` | eval_optimize | Code review scored against a quality rubric |
| `persistent-coder` | ralph | Writes code, retries with fresh context until tests pass |
| `orchestrator` | react | Routes tasks to specialist agents |
| `hello-local` | react | Same as hello but uses LM Studio |
| `agent_budgets` | react | Dogfooding demo — verifies the harness's own model cost table against real vendor pricing, proposes fixes for human review (never applies them itself) |
| `browser-assistant` | react | Navigates and reads real web pages via `@playwright/mcp` — accessibility-tree based, ephemeral browser by default, domain-approval gated. Read/navigate only in v1, no form-filling. |

```bash
# Count letters with code (the strawberry test)
.venv/bin/python -m agent_harness run ./agents/hello "How many r's in strawberry?"

# Analyse real data
.venv/bin/python -m agent_harness run ./agents/csv-analyser "What's the total revenue?"

# Self-critiquing analysis
.venv/bin/python -m agent_harness run ./agents/analyst "How many Python files in agent_harness?"

# Code review with scoring
.venv/bin/python -m agent_harness run ./agents/reviewer "Review the last commit"

# Persistent coding
.venv/bin/python -m agent_harness run ./agents/persistent-coder "Write is_palindrome(s). Test it. Say DONE."
```

See `example_runs.md` for the full set of example commands.

## Sessions and Memory

Resume a conversation across restarts:

```bash
python -m agent_harness run ./agents/hello --session research
# ... conversation happens ...
# ctrl-c or "exit" to stop

# Resume later:
python -m agent_harness run ./agents/hello --session research
```

Agents with `save_memory` and `recall_memory` tools can persist information in `{agent_dir}/memory/`. The LLM decides what to remember — no automatic memory.

Under the hood, a session's real identity is a GUID, not the `--session` name — the name is just a label resolved on lookup (`{agent_dir}/sessions/{guid}.json`, not `{name}.json`). This doesn't change the `--session` flag's behavior at all; it's what lets the HTTP API server (below) address sessions safely without two different callers ever colliding on the same unqualified name.

## Providers

| Provider | Config value | Models | Notes |
|----------|-------------|--------|-------|
| Anthropic | `anthropic` | claude-haiku-4-5-20251001, claude-sonnet-5, claude-opus-5, and others — see `agent_harness/models.py::MODEL_REGISTRY` for the current list | Set `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | gpt-4o/gpt-4o-mini plus the gpt-5.x family — see `MODEL_REGISTRY` | Set `OPENAI_API_KEY`. `o1`/`o3`/`o4` (o-series) models are deliberately unsupported. |
| LM Studio / local | `openai` | any | Add `provider_kwargs.base_url` |

Model cost/context-window data lives in one place, `agent_harness/models.py::MODEL_REGISTRY` — check there rather than this README for the exact current model list, since it's the single source of truth the harness itself uses (not a separate doc that can drift from it).

LM Studio example:
```yaml
provider: openai
model: qwen3-4b-thinking-2507
provider_kwargs:
  base_url: "http://localhost:1234/v1"
```

Both providers retry transient errors (rate limits, server errors) with exponential backoff (1s, 2s, 4s). Auth errors fail immediately with a clear message.

## Streaming and Extended Thinking

Enable streaming per agent in `config.yaml` — text prints token-by-token instead of waiting for the full response:

```yaml
provider: anthropic  # or openai
stream: true
```

Or per-run: `--stream` / `--no-stream`.

Supported for both `anthropic` and `openai` (Responses API models only — `gpt-4o`, `gpt-4o-mini`, the `gpt-5.x` family). Streaming is rejected at config-validation time for OpenAI-compatible backends reached via `provider_kwargs.base_url` (e.g. LM Studio) — that path uses Chat Completions, which isn't wired for streaming here.

Extended thinking is Anthropic-only, independent of streaming — add a `thinking` block under `provider_kwargs`:

```yaml
provider_kwargs:
  thinking:
    budget_tokens: 2000  # must be >= 1024 and < max_tokens; incompatible with temperature/top_p
```

Thinking is captured either way but hidden from the CLI by default. Show it with:

```yaml
show_thinking: true
```

or `--show-thinking` / `--no-show-thinking` per run.

## Built-in Tools

- `run_command` — run a shell command (uses `shlex.split`, no `shell=True`)
- `read_file` / `write_file` — read/write file contents (whole-file, text only)
- `edit_file(path, old_string, new_string)` — targeted, diff-style edit; errors clearly if `old_string` isn't found exactly once
- `execute_code` — run Python or bash snippets (configurable timeout, default 30s)
- `web_fetch(url)` — fetch a URL, extract main readable content (via `trafilatura`, discards nav/ads/boilerplate)
- `web_search(query)` — Tavily-based web search (`TAVILY_API_KEY` required)
- `list_provider_models(provider)` — query the vendor's live model list directly, not any of the harness's internal tables
- `view_image(path)` / `view_document(path)` — let the agent genuinely see an image or PDF (real vision/document content block), not just read its path. See [Vision and Documents](#vision-and-documents) below.
- `read_live_page_content` — read the currently open browser page's main content, extracted the same way `web_fetch` does but from a live, JS-rendered page. Requires an `mcp_servers` entry named `playwright` (see `agents/browser-assistant/`).

`edit_file`/`web_fetch`/`web_search`/`list_provider_models`/`read_live_page_content`'s `browser_navigate` counterpart are gated by the network-exfiltration/permission hooks the same way `run_command` is.

## MCP Client Support

Agents can consume external [MCP](https://modelcontextprotocol.io/) servers as tools — client only, the harness doesn't expose itself as an MCP server. Point an agent at one or more servers in `config.yaml`:

```yaml
mcp_servers:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
```

Every tool the server exposes gets merged into the agent's tool list automatically — no need to hand-enumerate them in `tools:`. If a tool name collides with one this agent already exposes (built-in or custom), the harness's own version wins; anything not already claimed comes from MCP. Add a name to `tools:` at any time to "claim" it for the harness's own implementation instead — no MCP config change needed.

To expose only some of a server's tools rather than everything it offers, add an optional `tools:` list to that server's entry:

```yaml
mcp_servers:
  - name: playwright
    command: npx
    args: ["@playwright/mcp@latest", "--isolated"]
    tools: [browser_navigate, browser_click, browser_snapshot]
```

Without this list, a server's tools are still all merged in unchanged (the original, still-default behavior). See `agents/browser-assistant/config.yaml` for a real example — it deliberately keeps riskier tools like `browser_type`/`browser_evaluate` off this list rather than exposing everything `@playwright/mcp` offers.

stdio (local subprocess) transport only for now — see `docs/roadmap.md` for what's deliberately not built yet (remote HTTP/SSE servers, MCP server mode).

## HTTP API Server

`agent-harness serve` runs a second driver alongside the CLI — HTTP/SSE instead of terminal I/O, wired to the same runtime underneath. Lets a remote client (a separately-built chat UI, Reachy Mini, a voice device) run any agent, watch a turn stream in real time, and answer tool/domain/plan approval prompts without a terminal.

```bash
export AGENT_HARNESS_API_KEY=some-shared-secret   # optional but strongly recommended — see below
agent-harness serve --host 127.0.0.1 --port 8420 --agents-dir agents
```

```bash
curl -N -X POST http://127.0.0.1:8420/agents/hello/runs \
  -H "X-API-Key: some-shared-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "hi", "session_name": "my-chat"}'
```

Response is a held-open `text/event-stream`: `delta`/`thinking_delta` chunks as the model talks, `tool_call`/`tool_result`/`budget`/`thrash_warning` events (the same visibility a CLI user already gets — not just answer text), `heartbeat` every 15s when there's nothing else to send, `approval_needed` if a tool/domain/plan approval is required (answer it via `POST /runs/<run_id>/signal` — the run's id comes back on the initial response's `X-Run-Id` header), and a final `done` event — or `cancelled` instead, same shape, if the run was stopped mid-flight via `POST /runs/<run_id>/signal` with `{"type": "cancel"}` (turn-boundary and mid-stream checkpoints; a tool call already in flight finishes on its own first). `GET /agents` lists what's available to run.

**Security — read this before exposing beyond `localhost`.** Auth is a single shared-secret header (`X-API-Key`, from `AGENT_HARNESS_API_KEY`), checked in constant time. **Anyone holding a valid key can list, resume, and run every agent and every session on this server** — there is no per-user or per-session isolation on top of that secret; it grants everything the harness can do, the same way a working `--session` name in the CLI does. That's a deliberate, right-sized tradeoff for the current deployment model (home LAN or a single work machine, not internet-facing), not an oversight — full multi-user auth (accounts, tokens, rotation) is intentionally not built. The server binds to `127.0.0.1` by default; opening it up to a LAN is an explicit `--host` choice, not the default.

Sessions get a GUID identity under the hood (mirrors Claude Code's session model) — a `session_name` you pass is just a label resolved on lookup, never the file's real key, so two different callers can never collide on an unqualified name. Only one run at a time is allowed per session; a second concurrent request against the same session gets `409` rather than silently racing.

Full design background and what's still deliberately deferred (full auth, agent management via the API, websockets, killing a tool call already in flight): `docs/roadmap.md`'s "HTTP API server" Done entry (the original PRD, `docs/api-plan.md`, was deleted 2026-08-30 once fully superseded). Real mid-run cancellation itself has since shipped — see that same entry and the "Real cancellation" Done entry beside it.

## Verified Completion

`reflection`, `ralph`, and `eval_optimize` normally trust the model's own "DONE"/`SCORE: N/10` self-report. Give them something real to check instead:

```yaml
loop: ralph
completion_check: "pytest -q"
```

A shell command's real exit code decides pass/fail (nothing forced — plain self-report is still the default with `completion_check` unset). Or point it at one of your own tools instead of a shell command — the same "build a tool, tell the agent to call it last" pattern you could always write in `instructions.md`, except now the harness actually enforces it rather than trusting the model to remember:

```yaml
tools: [run_command, verify_output]
completion_check: verify_output
```

A completion-check tool must work with no arguments, and its output should start with `PASS` or `FAIL` (case-insensitive) so the harness doesn't have to guess. On failure, the check's own output is fed back to the model and the loop retries — bounded by the same `max_turns`/budget cap as everything else, never an unbounded extra loop. Whichever way you point it, the check runs through the normal tool-call path, so permissions/hooks/tracing apply exactly like any other tool call.

## Vision and Documents

Agents can genuinely look at images and PDFs, not just read their paths:

```yaml
tools: [read_file, execute_code, view_image, view_document]
```

```bash
python -m agent_harness run ./agents/hello "Run execute_code to make a chart, then view_image it and tell me if it looks right"
```

`view_image(path)` / `view_document(path)` attach the file as a real vision/document API content block on the agent's next message. A tool that generates binary content in-process (not already written to disk) can hand it back the same way other tools return values — see `docs/features.md`'s "Multimodal / file handling" section for the full mechanism. Only the most recently viewed attachment stays in what's actually sent to the model on later turns (keeps token cost and context usage down); nothing is lost from the persisted conversation history.

Provider/model support isn't pre-validated — if a model or backend can't handle what you're sending, the provider rejects it with a clear error rather than the harness guessing ahead of time.

## Code Execution

`execute_code` delegates to a pluggable executor. The default is `subprocess` (runs code directly on your machine). A docker version or a.n. other method of sandboxing can easily be added to tools and hooks can be enhanced/added to prevent malicious code.

```yaml
# config.yaml — default, runs locally
executor: subprocess
tool_timeout: 30
max_output_chars: 10000
```

### Custom executors

Register your own executor to sandbox code execution. An executor is a function with this signature:

```python
def my_executor(code: str, language: str, timeout: int) -> str:
    """Execute code and return combined stdout/stderr."""
    ...
```

Register it before running the agent:

```python
from agent_harness.tools import executor_registry
executor_registry["docker"] = my_docker_executor
```

Then in your agent's `config.yaml`:

```yaml
executor: docker
```

### Example: Docker executor

A Docker executor provides real sandboxing — no filesystem access, no network (unless you choose), resource limits. Here's a minimal implementation:

```python
import subprocess

def docker_executor(code: str, language: str, timeout: int) -> str:
    image = "python:3.12-slim" if language == "python" else "bash:latest"
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network=none",           # no network access
            "--memory=128m",            # memory limit
            "--cpus=0.5",               # CPU limit
            image,
            "python" if language == "python" else "bash",
            "-c", code,
        ],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    output = result.stdout
    if result.stderr:
        output += result.stderr
    return output
```

This is an example, not production code. For production use, consider:
- Pre-pulling images to avoid timeout on first run
- Using `--read-only` filesystem
- Dropping all Linux capabilities (`--cap-drop=ALL`)
- Setting `--pids-limit` to prevent fork bombs
- Mapping a temp volume for file I/O

## Logging and Tracing

**Human-readable logs** are written to `{agent_dir}/logs/YYYY-MM-DD.log` at DEBUG level. Console output is INFO by default, DEBUG with `--verbose`:

```bash
python -m agent_harness run ./agents/hello "hello" --verbose
```

**Structured traces** are written alongside logs as newline-delimited JSON (`*.trace.jsonl`). Each line is a timestamped event — easy to grep, parse, or pipe into scripts:

```json
{"ts": "2026-04-06T18:25:38", "event": "turn", "input_tokens": 830, "output_tokens": 75}
{"ts": "2026-04-06T18:25:38", "event": "tool_call", "tool": "run_command", "args": ["command"]}
{"ts": "2026-04-06T18:25:38", "event": "tool_result", "tool": "run_command", "chars": 245, "error": null}
{"ts": "2026-04-06T18:25:39", "event": "budget", "summary": "Turn 2/10 | $0.0017/$0.10"}
```

## Testing

```bash
pytest tests/unit/ -v          # unit tests
pytest tests/integration/ -v   # integration tests (needs API key)
```

## Quality Checks

```bash
ruff check agent_harness/
mypy --strict agent_harness/
radon cc agent_harness/ --min C
pytest --cov=agent_harness --cov-branch
```
