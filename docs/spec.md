# Specification — Agent Harness

This document turns the [architecture](architecture.md) into a concrete build plan. Each phase is designed to be completable in a single session and produces something that runs end-to-end.

See [prd.md](prd.md) for requirements and [architecture.md](architecture.md) for structural decisions.

---

## Phase 1 — A Working Agent

**Goal**: `python -m agent_harness run ./agents/hello "What files are in this directory?"` produces a real answer using tool calls.

### 1.1 Shared types (`agent_harness/types.py`)

Dataclasses only. No logic. Under 60 lines.

```python
ToolCall(id, name, arguments)
ToolResult(tool_call_id, output, error)
Message(role, content, tool_calls, tool_result)
Response(message, usage, stop_reason)
Usage(input_tokens, output_tokens)
AgentConfig(name, provider, model, agent_dir, instructions, tools_guidance,
            tools, loop, max_turns, max_cost, permissions, hooks)

# Callback type aliases
OnResponse = Callable[[Response], None]
OnToolCall = Callable[[ToolCall], ToolResult | None]
OnBudget = Callable[[Usage], bool]
```

### 1.2 Tool registry and built-in tools (`agent_harness/tools.py`)

- `generate_schema(fn) -> dict`: Inspect function signature + docstring, produce JSON Schema following the OpenAI/Anthropic convention. Use `inspect.signature`, `typing.get_type_hints`, and `docstring_parser` or manual first-line extraction.
- `registry: dict[str, Callable]`: Tool name to function mapping. Populated at import time for built-ins.
- `execute_tool(tool_call: ToolCall) -> ToolResult`: Look up and run. Catch exceptions, return as `ToolResult(error=...)`.

Built-in tools for phase 1:

```python
def run_command(command: str, working_dir: str = ".") -> str:
    """Run a shell command and return its output.

    Args:
        command: The command to run (e.g. "ls -la")
        working_dir: Directory to run the command in
    """
    # shlex.split(command), subprocess.run(..., shell=False, timeout=30)

def read_file(path: str) -> str:
    """Read a file and return its contents.

    Args:
        path: Path to the file to read
    """

def execute_code(code: str, language: str = "python") -> str:
    """Execute a code snippet and return stdout and stderr.

    Args:
        code: The code to execute
        language: python or bash
    """
    # subprocess.run with timeout=30, capture_output=True
```

### 1.3 Anthropic provider (`agent_harness/providers/anthropic.py`)

```python
def chat(messages: list[Message], tools: list[dict],
         model: str = "claude-haiku-4-5-20251001", **kwargs) -> Response:
```

Responsibilities:
- Translate `Message` list to Anthropic's message format (separate system message, map roles)
- Translate tool schemas from our JSON Schema format to Anthropic's `input_schema` format
- Call `client.messages.create()`
- Translate response back to `Response` with `Usage` populated
- Map `stop_reason`: Anthropic's `"end_turn"` → `"end_turn"`, `"tool_use"` → `"tool_use"`

Provider registry (`providers/__init__.py`):
```python
from agent_harness.providers import anthropic
registry = {"anthropic": anthropic.chat}
```

### 1.4 Config loader (`agent_harness/config.py`)

```python
def load(agent_dir: str) -> AgentConfig:
```

- Read `config.yaml` with `yaml.safe_load`
- Read `instructions.md` — becomes the system prompt
- Read `tools.md` if present — appended to system prompt after instructions
- Validate: provider in registry, tools in registry, loop in registry, max_turns > 0
- Return populated `AgentConfig`

### 1.5 ReAct loop (`agent_harness/loops/react.py`)

```python
def run(chat_fn, messages, tool_schemas, config,
        on_response=None, on_tool_call=None, on_budget=None) -> str:
```

The loop:
```
turn = 0
while turn < config.max_turns:
    response = chat_fn(messages, tool_schemas, model=config.model)
    messages.append(response.message)
    if on_response: on_response(response)
    if on_budget and on_budget(response.usage): break

    if response.stop_reason != "tool_use":
        break

    for tool_call in response.message.tool_calls:
        if on_tool_call:
            result = on_tool_call(tool_call)
        else:
            result = execute_tool(tool_call)
        messages.append(Message(role="tool", tool_result=result))

    turn += 1

return messages[-1].content if messages else ""
```

Loop registry (`loops/__init__.py`):
```python
from agent_harness.loops import react
registry = {"react": react.run}
```

### 1.6 Display (`agent_harness/display.py`)

Rich console output:
- `show_response(response)` — render assistant text as markdown
- `show_tool_call(tool_call)` — panel showing tool name + arguments
- `show_tool_result(result)` — panel showing output or error
- `show_budget(summary)` — dim status line with turn count and cost
- `prompt_user() -> str` — styled input prompt

### 1.7 Budget (`agent_harness/budget.py`)

Inert by default. Always created, does nothing unless config sets limits.

```python
class Budget:
    def __init__(self, config: AgentConfig): ...
    def record(self, usage: Usage) -> bool:
        """Returns True if budget exceeded."""
    def summary(self) -> str:
        """Human-readable status."""
```

Cost table: dict mapping `(provider, model)` to `(input_per_million, output_per_million)`. Start with Anthropic Haiku pricing. Add others as providers are added.

### 1.8 CLI and REPL (`agent_harness/cli.py`, `agent_harness/__main__.py`)

`__main__.py`: two lines — import and call `main()`.

`cli.py`:
- Parse args with `argparse`: `agent_dir` (required), `prompt` (optional), `--verbose`, `--session` (future)
- Load config, get provider, get loop, create budget
- Compose `on_tool_call` callback (phase 1: just `execute_tool`, no hooks/permissions yet)
- If prompt given: single command mode
- If no prompt: REPL with `input()` loop, exit on `exit`/`quit`/ctrl-c

### 1.9 Example agent (`agents/hello/`)

`config.yaml`:
```yaml
name: hello
provider: anthropic
model: claude-haiku-4-5-20251001
tools: [run_command, read_file, execute_code]
max_turns: 10
max_cost: 0.10
```

`instructions.md`:
```markdown
You are a helpful assistant that can run commands, read files, and execute code.

When asked about files or directories, use the run_command or read_file tools.
When asked to calculate or analyse data, prefer execute_code to get a
deterministic answer rather than guessing.

Be concise. Show your working when using tools.
```

### Phase 1 acceptance criteria

1. `python -m agent_harness run ./agents/hello "list the files in the current directory"` → uses run_command, returns file listing
2. `python -m agent_harness run ./agents/hello "how many lines in agents/hello/instructions.md"` → uses execute_code or read_file, returns correct count
3. Interactive REPL works with multi-turn conversation
4. Budget status displays after each turn
5. Agent stops at max_turns
6. Invalid config (bad provider name, missing instructions.md) gives clear error on startup
7. Tool errors (file not found, command fails) are returned to the LLM, not crashed
8. All tests pass, ruff clean, mypy clean

---

## Phase 2 — Security and Reliability

**Goal**: The agent can be trusted to run without supervision for short tasks.

### 2.1 Hooks (`agent_harness/hooks.py`)

Inert by default. Three hook points:

```python
class Hooks:
    def __init__(self, hook_config: dict): ...
    def run_before_tool(self, tool_call: ToolCall) -> ToolCall | None:
        """None = blocked."""
    def run_after_tool(self, tool_call: ToolCall, result: ToolResult) -> ToolResult:
        """Can sanitise output."""
    def on_external_content(self, content: str, source: str) -> str:
        """Scan for injection before content enters conversation."""
```

Built-in hooks (activated by name in config):
- `dangerous_command_blocker`: Rejects run_command calls containing `rm -rf`, `sudo`, `mkfs`, `dd if=`, `> /dev/`
- `path_traversal_detector`: Rejects file operations with `../` that escape the working directory
- `injection_scanner`: Flags common prompt injection patterns in tool output (`ignore previous`, `system:`, `<|im_start|>`) and wraps suspicious content with `[EXTERNAL CONTENT WARNING]`

Config:
```yaml
hooks:
  before_tool: [dangerous_command_blocker, path_traversal_detector]
  after_tool: [injection_scanner]
```

Custom hooks: user writes a Python file in the agent folder, references the function path in config.

### 2.2 Permissions (`agent_harness/permissions.py`)

Inert by default (allows everything). Activated when config includes permission settings.

```python
class Permissions:
    def __init__(self, agent_dir: str, perm_config: dict): ...
    def check(self, tool_call: ToolCall) -> bool:
        """Returns True if approved."""
```

Three tiers:
- `always_allow: [read_file, list_memories]` — never prompt for these
- `always_ask: [run_command, execute_code]` — always prompt
- Session memory: user approves once, remembered until exit

Persistent permissions saved to `{agent_dir}/.permissions.yaml`.

User prompt on tool call:
```
Tool: run_command
Args: {"command": "ls -la"}
[a]llow once / allow for [s]ession / [d]eny?
```

### 2.3 Wire hooks and permissions into cli.py

Update `make_tool_handler` in cli.py to compose hooks and permissions:

```python
def make_tool_handler(hooks, permissions):
    def handle(tool_call):
        tool_call = hooks.run_before_tool(tool_call)
        if tool_call is None:
            return ToolResult(id, "", error="Blocked by safety hook")
        if not permissions.check(tool_call):
            return ToolResult(id, "", error="Denied by user")
        result = execute_tool(tool_call)
        return hooks.run_after_tool(tool_call, result)
    return handle
```

### 2.4 Provider retry logic

Add to the anthropic provider (and later to others):
- Retry on transient errors (network, 429 rate limit, 500/503) with exponential backoff
- Max 3 attempts, delays: 1s, 2s, 4s
- Permanent errors (401 auth, 400 bad request) fail immediately
- Clear error messages: "API key not set — export ANTHROPIC_API_KEY" not a raw stack trace

### 2.5 Logging

- `logging.getLogger(__name__)` in each file
- Format: `%(asctime)s %(levelname)s %(module)s %(funcName)s:%(lineno)d %(message)s`
- Console: INFO by default, DEBUG with `--verbose`
- File: `{agent_dir}/logs/YYYY-MM-DD.log` at DEBUG level, created on first write
- Log: every API call (model, token count), every tool execution (name, args summary), every hook decision (allowed/blocked)

### Phase 2 acceptance criteria

1. `rm -rf /` in a run_command call is blocked by the dangerous_command_blocker hook
2. File read with `../../etc/passwd` is blocked by path_traversal_detector
3. Tool approval prompt appears for tools in the `always_ask` list
4. Session approval works — approve once, not asked again that session
5. Persistent permissions saved and loaded across sessions
6. API rate limit error → retries and succeeds
7. Invalid API key → clear error message on first call, not after 3 retries
8. Log file created with readable entries for an agent run
9. All hooks and permissions are inert with default config (no behaviour change from phase 1)

---

## Phase 3 — Multi-Provider and Loop Patterns

**Goal**: Same agent folder works across providers. New loop patterns available.

### 3.1 OpenAI provider (`agent_harness/providers/openai_provider.py`)

**Already implemented in Phase 1** as `providers/openai_provider.py` using Chat Completions API.

Remaining Phase 3 work:
- LM Studio support: accept `base_url` from config kwargs, pass to OpenAI client
- Test with local models (qwen3-4b-thinking-2507 available in LM Studio)

Config for LM Studio:
```yaml
provider: openai
model: qwen3-4b-thinking-2507
provider_kwargs:
  base_url: "http://localhost:1234/v1"
```

#### ⚠️ GPT-5 Responses API (future work)

As of 2026, OpenAI is migrating from Chat Completions (`/v1/chat/completions`) to the
Responses API (`/v1/responses`). Key impacts:

1. **GPT-4o-mini is on the deprecation path** — retired from ChatGPT Feb 2026, API
   retirement expected later in 2026.
2. **GPT-5.4+ has dropped tool calling in Chat Completions** with `reasoning: none`.
   Full tool calling for GPT-5 models requires the Responses API.
3. **Responses API has a different shape**: typed response objects instead of messages,
   different function calling format, `instructions` parameter instead of system message.
4. **Performance**: Responses API gives ~3% better results on benchmarks and 40-80%
   better cache utilisation for GPT-5 models.

**Action**: When GPT-5 support is needed, add a new `providers/openai_responses.py`
using the Responses API. The current Chat Completions provider remains correct for
GPT-4 series models and OpenAI-compatible endpoints (LM Studio, Ollama, etc.).

References:
- https://developers.openai.com/api/docs/guides/migrate-to-responses
- https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_new_params_and_tools

### 3.2 Plan-execute loop (`agent_harness/loops/plan_execute.py`)

Two phases:
1. **Plan**: Send the task with "Create a numbered plan" appended. No tools available. LLM produces a text plan.
2. **Execute**: For each step, run a mini react loop with tools available.
3. **Summarise**: Final call to summarise what was accomplished.

Reuses `react.run()` internally for step execution.

Config:
```yaml
loop: plan_execute
```

### 3.3 Code execution improvements

- Timeout configurable in config (default 30s)
- Working directory set to agent folder by default
- Output truncated to 10,000 characters (configurable) to avoid blowing context
- stderr captured alongside stdout

### 3.4 Context window awareness

Provider reports its context limit. If messages exceed ~80% of the limit, oldest non-system messages are summarised or truncated. This is simple and lossy — not a sophisticated memory system. Just prevents crashes on long conversations.

### Phase 3 acceptance criteria

1. Same agent folder runs with `provider: openai` and `model: gpt-4o-mini` by changing two lines in config
2. LM Studio works via base_url override
3. Plan-execute loop produces a visible plan, then executes steps
4. Long conversation (>50 turns) doesn't crash from context overflow
5. Budget cost tracking correct for both Anthropic and OpenAI pricing
6. execute_code respects timeout — long-running code is killed after limit

---

## Phase 4 — Memory, Routing, and Agent Building

**Goal**: Agents can remember across sessions, delegate to each other, and new agents can be scaffolded.

### 4.1 Session persistence (`agent_harness/memory.py`)

```python
def save_session(messages: list[Message], path: str) -> None:
def load_session(path: str) -> list[Message]:
```

Sessions saved as JSON in `{agent_dir}/sessions/`. CLI flag: `--session <name>` to resume.

### 4.2 Long-term memory tools

Added to `tools.py` built-ins:

```python
def save_memory(key: str, content: str) -> str:
    """Save information to long-term memory."""
    # writes {agent_dir}/memory/{key}.md

def recall_memory(key: str) -> str:
    """Recall information from long-term memory."""
    # reads {agent_dir}/memory/{key}.md

def list_memories() -> str:
    """List all saved memory keys."""
    # lists files in {agent_dir}/memory/
```

The agent's `instructions.md` guides when to use these. No automatic memory — the LLM decides when something is worth remembering.

### 4.3 Agent-as-tool (routing)

Added to `tools.py` built-ins:

```python
def run_agent(agent_name: str, message: str) -> str:
    """Run another agent and return its response.

    Args:
        agent_name: Name of the agent folder (relative to agents directory)
        message: The message to send to the agent
    """
    # Loads agent folder, creates a fresh loop, runs to completion
    # Inner agent gets its own budget (from its own config)
    # Returns final text response
```

Routing is defined in the orchestrator's `instructions.md`:
```markdown
You are a triage agent. Based on the user's request:
- For research questions, delegate to the researcher agent
- For data analysis, delegate to the csv-analyser agent
- For simple questions, answer directly
```

### 4.4 Agent scaffolding

A built-in command: `python -m agent_harness init <name>`

Creates:
```
agents/<name>/
  instructions.md    # template with guidance comments
  config.yaml        # defaults filled in
  tools.md           # template listing available tools
```

This is the simplest version. The richer version — where Claude Code builds a full agent from a description — works because the format is just markdown + yaml. No special tooling needed; any coding assistant can create and edit these files.

### Phase 4 acceptance criteria

1. `--session myresearch` saves conversation; rerunning with same flag resumes
2. Agent uses save_memory/recall_memory across sessions — information persists
3. Orchestrator agent delegates to sub-agent via run_agent tool
4. Sub-agent's budget is independent — doesn't drain orchestrator's budget
5. `python -m agent_harness init my-new-agent` creates a valid agent folder
6. The scaffolded agent runs without edits (with default config)

---

## Phase 5 — Polish and Examples

**Goal**: The project is ready for others to use. Examples solve real problems.

### 5.1 Example agents

Each is a folder with `instructions.md`, `config.yaml`, and optionally `tools.md`. These are the showcase — they matter more than the runtime code.

| Agent | What it does | Key tools |
|-------|-------------|-----------|
| `hello` | Simple assistant for trying things out | run_command, read_file, execute_code |
| `researcher` | Multi-step web research with source tracking | run_command (curl), read_file, execute_code, save_memory |
| `csv-analyser` | Answers questions about data files deterministically | read_file, execute_code |
| `code-reviewer` | Reviews a diff and gives structured feedback | run_command (git diff), read_file |
| `file-organiser` | Sorts files in a folder by content/type | run_command, read_file, execute_code |
| `orchestrator` | Routes tasks to specialist agents | run_agent |

### 5.2 README

- One-paragraph description
- 30-second quickstart (install, create agent, run)
- "How it works" — the agent folder concept
- Example agent walkthroughs
- Contributing guide (link to architecture.md)
- No marketing language

### 5.3 Packaging

- `pyproject.toml` with minimal dependencies: `anthropic`, `openai`, `pyyaml`, `rich`
- `pip install agent-harness` (or similar available name)
- Entry point: `agent-harness run ./my-agent`

### Phase 5 acceptance criteria

1. Every example agent runs successfully and does something useful
2. README quickstart works from a fresh clone
3. `pip install .` works
4. A stranger can create and run a custom agent in under 5 minutes following the README
5. Code review passes: ruff, mypy --strict, radon cc --min C, pytest --cov >90%

---

## File summary (actual, post-implementation)

| File | Phase | Lines | Purpose |
|------|-------|-------|---------|
| `types.py` | 1 | 92 | Shared dataclasses and type aliases |
| `tools.py` | 1 | 269 | Registry, schema generation, core tools, executor |
| `providers/anthropic.py` | 1 | 194 | Claude provider with retry |
| `providers/openai_provider.py` | 1+ | 199 | OpenAI/LM Studio provider with retry |
| `loops/react.py` | 1 | 68 | ReAct loop with context trimming |
| `loops/plan_execute.py` | 3 | 89 | Plan-then-execute loop |
| `loops/rewoo.py` | — | 75 | ReWOO loop |
| `loops/reflection.py` | — | 70 | Reflection/self-refine loop |
| `loops/eval_optimize.py` | — | 83 | Evaluator-optimizer loop |
| `loops/ralph.py` | — | 55 | Ralph Wiggum retry loop |
| `loops/debate.py` | — | 72 | Debate/adversarial loop |
| `loops/common.py` | — | 65 | Shared loop utilities |
| `config.py` | 1 | 78 | Load agent folder |
| `budget.py` | 1 | 61 | Turn/cost tracking |
| `hooks.py` | 2 | 201 | Safety hook chain + 4 pattern matchers |
| `network.py` | 2 | 138 | Network blocker with domain whitelist |
| `permissions.py` | 2 | 95 | Tool approval system |
| `memory.py` | 4 | 60 | Long-term memory tools |
| `routing.py` | 4 | 124 | Agent routing + handoff with depth limiting |
| `session.py` | 4 | 109 | Session save/load |
| `context.py` | 3 | 99 | Context window trimming |
| `scaffold.py` | 4 | 50 | Agent folder scaffolding |
| `skills.py` | — | 57 | Skill loading from directories |
| `display.py` | 1 | 66 | Rich console output |
| `log.py` | 2 | 40 | Logging setup |
| `trace.py` | 6 | 46 | Structured JSONL traces |
| `cli.py` | 1 | 318 | Arg parsing, REPL, composition root |
| `__main__.py` | 1 | 5 | Entry point |
| `__init__.py` | 1 | 3 | Package exports |
| **Total runtime** | | **~2,910** | 31 source files |
| **Total tests** | | **273** | |

---

## Dependencies

Minimal. Each justified:

| Package | Why | Phase |
|---------|-----|-------|
| `anthropic` | Claude API | 1 |
| `python-dotenv` | Load .env files | 1 |
| `pyyaml` | Config loading | 1 |
| `rich` | Console output | 1 |
| `openai` | OpenAI + LM Studio | 1+ |

No other runtime dependencies. Test dependencies: `pytest`, `pytest-cov`, `ruff`, `mypy`, `types-PyYAML`.

---

## Custom Tools and Skills System

### Custom Tools (`tools/`)

Project-level custom tools in `tools/` directory. One Python file per tool, one public function with type hints and docstring.

**Discovery:** At startup, `discover_tools("tools")` scans `tools/*.py`, imports each module, registers the first public function with a return type annotation. Built-in tools cannot be overwritten.

**Access control:** Custom tools only available to an agent if listed in its `config.yaml` tools list. No auto-discovery into agent context.

### Skills (`skills/` + `{agent_dir}/skills/`)

Skills are markdown files describing how to approach tasks, loaded into the system prompt.

**Structure:** Each skill is a directory containing `SKILL.md` and optional `scripts/`:
```
skills/csv-analysis/
  SKILL.md              # loaded into system prompt
  scripts/
    validate.py         # agent invokes via run_command/execute_code
```

**Resolution:** Project-level `skills/` scanned first, then `{agent_dir}/skills/`. Agent-local overrides shared on name collision (same directory name).

**Loading:** Auto-loaded from both locations. All SKILL.md contents appended to system prompt after instructions.md and tools.md.

---

## Backlog — Future Phases

### Phase 7 — MCP Support

Connect agents to external tools via [Model Context Protocol](https://modelcontextprotocol.io/). MCP is the emerging standard for tool integration — standardised connectors for Slack, GitHub, databases, file systems without writing custom tool functions.

Scope: MCP client in the harness, config to point at MCP servers, tools auto-discovered from server capabilities.

### Phase 8 — Async Execution

Parallel tool calls and streaming responses. Requires asyncio refactor of the react loop and provider chat functions. Would enable running multiple tools concurrently when the LLM requests them in one response.

### Phase 9 — Streaming Responses

Stream LLM output token-by-token for better UX on long responses. Requires provider-level streaming support and display updates.

### Phase 10 — Evaluation Framework

Run agents against test cases and score quality. Can be approximated today by scripting CLI runs and comparing output. A formal framework would add: test case definitions (input/expected), scoring functions, regression detection.

### Phase 11 — Model Fallback Chains

If primary provider fails (rate limit, outage), try a fallback provider before giving up. Config-driven, ~20 lines in the loop. Inspired by OpenClaw's model failover with circuit breaker.

```yaml
provider: anthropic
model: claude-haiku-4-5-20251001
fallback:
  provider: openai
  model: gpt-4o-mini
```

### Phase 12 — Self-Improving Skills

After a successful multi-step task, the agent can save the approach as a reusable skill in `{agent_dir}/skills/`. Next time a similar task comes up, the skill is loaded into context. Just save_memory with a convention — the LLM decides when to save. Inspired by Hermes Agent's skills system.

### Phase 13 — Lazy Tool Schema Loading

Instead of injecting all tool schemas into every prompt, send a compact list (name + description). The LLM picks which tools it needs, full schemas loaded on demand. Reduces token waste when agents have many tools. Only relevant when tool count exceeds ~15.

### Phase 14 — Identity/Procedure Split

Optional `identity.md` file in agent folder — prepended before `instructions.md`. Separates "who you are" from "what you do". Useful for agents that share an identity but have different procedures. ~5 lines in config.py. Inspired by OpenClaw's SOUL.md/AGENTS.md split.

### Phase 15 — Immutable Trace with Hash Chain

Add hash chaining to trace events — each entry includes the hash of the previous entry. Makes traces tamper-evident without requiring a database. ~10 lines in trace.py. Inspired by Paperclip's append-only audit log.

### Phase 16 — Per-Task Cost Attribution

Add `task_id` to trace events and budget.record(). Enables summing cost by task for reporting. ~10 lines. Inspired by Paperclip's granular cost tracking.

### Considering — Decision-Level Approval Gates

Beyond per-tool permissions, approve by decision severity. Could work as a `before_decision` hook that checks decision type (e.g. "this agent wants to delegate to another agent" vs "this agent wants to read a file"). Worth exploring if multi-agent orchestration becomes a primary use case. Inspired by Paperclip's governance model.

### Considering — Shared Workspace Communication

A `workspace/` directory convention for multi-agent file-based coordination. Agents read/write shared files instead of fire-and-forget `run_agent` calls. Enables richer collaboration without framework changes — just a directory and instructions.md guidance. Inspired by Paperclip's shared workspace.

### Implemented Loop Patterns

All implemented. See `docs/agentic-design-patterns.md` for diagrams.

- `loops/rewoo.py` — ReWOO: plan once, execute all tools, solve once (2 LLM calls)
- `loops/reflection.py` — Reflection: generate → critique → refine until DONE
- `loops/eval_optimize.py` — Evaluator-Optimizer: generate + score, loop until SCORE >= 7/10
- `loops/ralph.py` — Ralph Wiggum: fresh context retries until DONE marker
- `loops/debate.py` — Debate: two perspectives argue N rounds, synthesiser reconciles
- `routing.py:handoff_agent` — Handoff: pass existing messages to sub-agent

### Backlog — Remaining Patterns

**Script wrappers (no framework changes):**
- Parallelization (Fan-out/Fan-in) — shell `&` + `wait`, then synthesiser agent.
- Consensus/Voting — N agents in parallel on same task, judge agent compares.

**Needs async (Phase 8 prerequisite):**
- Tree-of-Thoughts (~100 lines) — multiple concurrent LLM calls with branching/pruning.
- LATS (~200 lines) — Monte Carlo Tree Search over agent reasoning. Research-grade.
