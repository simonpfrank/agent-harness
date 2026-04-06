# Agent Harness

Minimal agent framework — agents as markdown folders.

## Quick Start

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
```

Interactive REPL (no prompt argument):

```bash
python -m agent_harness run ./agents/hello
```

## How It Works

An agent is a folder containing:
- `config.yaml` — provider, model, tools, budget limits, safety config
- `instructions.md` — system prompt (what the agent does)
- `tools.md` (optional) — guidance on tool usage

The runtime loads the config, builds tool schemas from the registry, applies safety hooks, and runs a ReAct loop: call LLM → check hooks → check permissions → execute tool → scan output → repeat until done or budget exceeded.

```
types.py (root — dataclasses only)
  ↓
tools.py, budget.py, display.py, hooks.py, permissions.py, providers/*, config.py
  ↓
loops/react.py
  ↓
cli.py (composition root)
```

## Safety and Security

**This section is important. Read it before running agents unsupervised.**

Agent Harness includes five built-in safety hooks that filter tool calls and scan output. Three are on by default. Understanding what they do and don't do is your responsibility.

### Default-on hooks (active with zero config)

| Hook | Type | What it does | What it does NOT do |
|------|------|-------------|-------------------|
| `dangerous_command_blocker` | before tool | Blocks `rm -rf`, `sudo`, `mkfs`, `dd if=`, writes to `/dev/` | Does not catch every destructive command. A determined or creative LLM can find other ways to cause damage (e.g. `find / -delete`, overwriting files with `>`, Python `os.remove`). |
| `path_traversal_detector` | before tool | Blocks `..` in any tool argument | Only checks for literal `..`. Does not resolve symlinks or normalise paths. A symlink pointing outside the working directory will bypass this. |
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
  # tools not in either list: prompted once per session
```

## Creating an Agent

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

## Providers

| Provider | Config value | Models | Notes |
|----------|-------------|--------|-------|
| Anthropic | `anthropic` | claude-haiku-4-5-20251001, claude-sonnet-4-6, claude-opus-4-6 | Set `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | gpt-4o-mini, gpt-4o | Set `OPENAI_API_KEY` |
| LM Studio / local | `openai` | any | Add `provider_kwargs.base_url` |

LM Studio example:
```yaml
provider: openai
model: qwen3-4b-thinking-2507
provider_kwargs:
  base_url: "http://localhost:1234/v1"
```

Both providers retry transient errors (rate limits, server errors) with exponential backoff (1s, 2s, 4s). Auth errors fail immediately with a clear message.

## Built-in Tools

- `run_command` — run a shell command (uses `shlex.split`, no `shell=True`)
- `read_file` — read file contents
- `execute_code` — run Python or bash snippets (30s timeout)

## Logging

Logs are written to `{agent_dir}/logs/YYYY-MM-DD.log` at DEBUG level. Console output is INFO by default, DEBUG with `--verbose`:

```bash
python -m agent_harness run ./agents/hello "hello" --verbose
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
