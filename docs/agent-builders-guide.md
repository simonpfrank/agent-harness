# Agent Builder's Guide

Practical reference for building agents, tools, and skills. Read `architecture.md` for design rationale — this doc is the recipe book.

---

## Quick Start: What Goes Where

| Thing to build | Where it lives | What changes |
|---|---|---|
| Built-in tool | `agent_harness/tools.py` | Add function + registry entry |
| Custom tool | `tools/<name>.py` | New file only (auto-discovered) |
| Shared skill | `skills/<name>/SKILL.md` | New directory + file only |
| Agent | `agents/<name>/` | New directory (config.yaml + instructions.md) |
| Agent-local skill | `agents/<name>/skills/<skill>/SKILL.md` | Overrides shared skill of same name |

---

## Built-in Tools

Defined in `agent_harness/tools.py`. Each is a typed function registered in the `registry` dict.

### Pattern

```python
def my_tool(arg1: str, arg2: int = 10) -> str:
    """One-line description shown to the LLM.

    Args:
        arg1: Description of arg1
        arg2: Description of arg2

    Returns:
        What the tool returns.
    """
    # implementation
    return "result string"
```

Then add to the registry:

```python
registry: dict[str, Callable[..., str]] = {
    # ... existing tools ...
    "my_tool": my_tool,
}
```

### Schema auto-generation

`generate_schema(fn)` inspects the function and produces JSON Schema from:
- **Function name** -> tool name
- **First line of docstring** -> description
- **Type hints** -> parameter types (str/int/float/bool mapped to JSON types)
- **`Args:` section of docstring** -> parameter descriptions
- **Parameters without defaults** -> required fields

### Existing built-ins

| Tool | Signature | Purpose |
|---|---|---|
| `run_command` | `(command: str, working_dir: str = ".")` | Shell command via `shlex.split()`, no `shell=True` |
| `read_file` | `(path: str)` | Read file contents |
| `execute_code` | `(code: str, language: str = "python")` | Run Python or bash with timeout |
| `save_memory` | `(key: str, content: str)` | Write to `{agent_dir}/memory/{key}.md` |
| `recall_memory` | `(key: str)` | Read from memory |
| `list_memories` | `()` | List saved memory keys |
| `run_agent` | `(agent_name: str, message: str)` | Invoke another agent (routing) |

### Safety

All tool calls pass through hooks before execution:
1. `path_traversal_detector` — blocks any tool arg containing `..`
2. `dangerous_command_blocker` — blocks `rm -rf`, `sudo`, etc. in `run_command`
3. `injection_scanner` — flags suspicious patterns in tool output
4. `secrets_leakage_scanner` — redacts API keys/tokens from output

New built-in tools get path traversal protection for free (checks all arg values).

---

## Custom Tools

One Python file per tool in `tools/`. Auto-discovered by `discover_tools()` at startup.

### Convention

- One public function per file (first non-underscore function with a return type hint wins)
- Must have a `-> str` return type hint
- Must have a Google-style docstring (for schema generation)
- File name = tool name by convention (but the function name is what matters)
- Cannot overwrite built-in tool names

### Example: `tools/file_search.py`

```python
"""Search for files matching a glob pattern."""

from pathlib import Path


def file_search(pattern: str, directory: str = ".") -> str:
    """Find files matching a glob pattern in a directory.

    Args:
        pattern: Glob pattern (e.g. "*.py", "**/*.md").
        directory: Directory to search in.

    Returns:
        Newline-separated list of matching file paths.
    """
    matches = sorted(str(p) for p in Path(directory).glob(pattern))
    return "\n".join(matches) if matches else "No files found."
```

### Discovery mechanism

`cli.py` calls `discover_tools("tools")` during setup. This:
1. Scans `tools/*.py` (skips `_`-prefixed files)
2. Imports each module
3. Finds the first public function with a return type hint
4. Registers it in `tool_registry`
5. Logs a warning if the name collides with a built-in

### Using custom tools in agents

Just reference the function name in `config.yaml`:

```yaml
tools: [read_file, execute_code, file_search]
```

---

## Skills

Markdown files injected into the system prompt. Two levels:

- **Shared**: `skills/<name>/SKILL.md` — available to all agents
- **Agent-local**: `agents/<name>/skills/<skill>/SKILL.md` — overrides shared skill of same directory name

### Format

Plain markdown. No frontmatter. Content is concatenated directly into the system prompt after instructions and tools guidance.

### Example: `skills/system-tools/SKILL.md`

```markdown
# System Tools

CLI tools available on this machine via `run_command`. Use these instead of guessing.

## File operations
- `fd <pattern>` -- find files by name
- `tree <dir> -L <depth>` -- show directory structure
...
```

### How skills are loaded

`skills.py` scans both directories. Agent-local skills override shared skills with the same directory name. The content is sorted by skill name and joined with `\n\n`.

### System prompt assembly order

Built in `cli.py:_build_system_prompt()`:

```
1. instructions.md          (required)
2. tools.md                 (optional, if present in agent dir)
3. skills/* SKILL.md files  (shared then agent-local overrides)
```

---

## Agent Folders

### Required files

```
agents/my-agent/
  config.yaml       # model, tools, loop, budget
  instructions.md   # what this agent does (becomes system prompt)
```

### Optional files/dirs

```
  tools.md           # tool usage guidance (appended to system prompt)
  skills/            # agent-local skills
  memory/            # long-term memory (auto-created by save_memory)
  logs/              # trace JSONL + debug logs (auto-created)
  sessions/          # saved conversation sessions (auto-created)
```

### config.yaml fields

```yaml
name: my-agent                       # display name (defaults to folder name)
provider: anthropic                   # anthropic | openai
model: claude-haiku-4-5-20251001     # model ID
tools: [read_file, execute_code]      # list of tool names (built-in or custom)
loop: react                           # react | reflection | plan_execute | rewoo | eval_optimize | ralph | debate
max_turns: 10                         # max loop iterations
max_cost: 0.30                        # cost ceiling in USD (optional)
executor: subprocess                  # code executor (default: subprocess)
tool_timeout: 30                      # seconds per tool call
max_output_chars: 10000               # truncate tool output beyond this
provider_kwargs: {}                   # extra kwargs passed to provider chat()
permissions: {}                       # tool permission config
hooks: {}                             # safety hook config
```

All fields except `name` have sensible defaults. A minimal config:

```yaml
name: my-agent
provider: anthropic
model: claude-haiku-4-5-20251001
tools: [read_file]
```

### instructions.md

This is the system prompt. Write it as if briefing the agent:

```markdown
You are a data analyst. You have access to CSV files in the working directory.

When given a question about data:
1. Use list_directory to find available files
2. Use read_file to examine the data
3. Use execute_code to run pandas analysis
4. Report findings clearly with numbers

Always show your working. If unsure, say so.
```

### tools.md (optional)

Appended to system prompt. Use for tool-specific guidance:

```markdown
# Tool usage

- Prefer `execute_code` over `run_command` for data processing
- Use `save_memory` to record patterns you discover for future sessions
```

---

## Loop Patterns

All loops share the same signature:

```python
def run(
    chat_fn: Callable[..., Response],
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    config: AgentConfig,
    callbacks: LoopCallbacks | None = None,
) -> str:
```

### Available loops

| Loop | Config value | How it works |
|---|---|---|
| **ReAct** | `react` | Reason -> act (tools) -> observe -> repeat. Stops on end_turn or max_turns. |
| **Reflection** | `reflection` | ReAct generate -> critique (no tools) -> refine. Stops when critique says "DONE". |
| **Plan-Execute** | `plan_execute` | Plan step (no tools) -> execute each step via ReAct sub-loop. |
| **ReWOO** | `rewoo` | Plan all steps at once -> execute all -> solve with all results. |
| **Eval-Optimize** | `eval_optimize` | Generate -> score (0-10) -> improve. Stops at score >= 8 or max iterations. |
| **RALPH** | `ralph` | Fresh context retries. Each attempt starts clean. |
| **Debate** | `debate` | Two perspectives argue, then synthesise. |

### Choosing a loop

- **Simple tasks**: `react` — one-shot, tools as needed
- **Quality-sensitive**: `reflection` — catches errors via self-critique
- **Multi-step plans**: `plan_execute` — structured approach
- **Optimisation**: `eval_optimize` — iterative improvement with scoring

---

## Memory System

Per-agent, file-based. Three tools exposed to the LLM:

- `save_memory(key, content)` — writes `{agent_dir}/memory/{key}.md`
- `recall_memory(key)` — reads it back
- `list_memories()` — lists all keys

Memory persists across sessions. Guide the agent on what/when to save via `instructions.md`.

Content is scanned for injection patterns before saving.

---

## Running Agents

### CLI

```bash
# Single prompt
python -m agent_harness run agents/my-agent "analyse sales.csv"

# Interactive REPL
python -m agent_harness run agents/my-agent

# With session persistence
python -m agent_harness run agents/my-agent --session my-session

# With overrides
python -m agent_harness run agents/my-agent "hello" --model claude-sonnet-4-6 --max-cost 1.0

# Scaffold a new agent
python -m agent_harness init my-new-agent
```

### Override flags

`--provider`, `--model`, `--loop`, `--max-turns`, `--max-cost`, `--executor`, `--tool-timeout`, `--max-output-chars`

---

## Wiring: How It All Connects

The composition root is `cli.py`. On `run`:

```
1. Load config.yaml + instructions.md -> AgentConfig
2. Apply CLI overrides
3. Validate against registries (provider, tools, loop exist)
4. Set tool module globals (timeout, executor, memory dir)
5. Discover custom tools from tools/
6. Build system prompt (instructions + tools.md + skills)
7. Create tool schemas from registered functions
8. Create Budget, Hooks, Permissions, Tracer
9. Compose callbacks (on_response, on_tool_call, on_budget)
10. Get loop function from registry
11. Run: loop_fn(chat_fn, messages, tool_schemas, config, callbacks)
```

The loop calls `chat_fn` (provider), gets tool calls, calls `on_tool_call` (which runs hooks -> permissions -> execute -> post-hooks), and repeats.

---

## Checklist: Building a New Agent

1. Create `agents/<name>/` directory
2. Write `config.yaml` — pick model, tools, loop, budget
3. Write `instructions.md` — brief the agent on its task
4. Optionally write `tools.md` for tool guidance
5. Optionally create agent-local skills in `agents/<name>/skills/`
6. If the agent needs a new tool:
   - Generic/reusable? Put in `tools/` as a custom tool
   - Core to the framework? Add to `agent_harness/tools.py` as built-in
7. Test: `python -m agent_harness run agents/<name> "test prompt"`
8. Check `agents/<name>/logs/` for trace output
