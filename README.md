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
# Edit .env with your ANTHROPIC_API_KEY
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
- `config.yaml` — provider, model, tools, budget limits
- `instructions.md` — system prompt (what the agent does)
- `tools.md` (optional) — guidance on tool usage

The runtime (~525 lines) loads the config, builds tool schemas from the registry, and runs a ReAct loop: call LLM → execute tool calls → repeat until done or budget exceeded.

```
types.py (root — dataclasses only)
  ↓
tools.py, budget.py, display.py, providers/*, config.py
  ↓
loops/react.py
  ↓
cli.py (composition root)
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

## Built-in Tools

- `run_command` — run a shell command
- `read_file` — read file contents
- `execute_code` — run Python or bash snippets

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
