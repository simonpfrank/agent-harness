"""Agent scaffolding — create new agent folders from templates."""

from __future__ import annotations

from pathlib import Path

_CONFIG_TEMPLATE = """\
name: {name}
provider: anthropic
model: claude-haiku-4-5-20251001
tools: [run_command, read_file, execute_code]
max_turns: 10
max_cost: 0.10
"""

_INSTRUCTIONS_TEMPLATE = """\
You are a helpful assistant that can run commands, read files, and execute code.

Be concise. Explain your reasoning when using tools.
"""

_TOOLS_TEMPLATE = """\
# Tool usage guidance

- Use `run_command` for shell operations (ls, grep, find, etc.)
- Use `read_file` to read file contents
- Use `execute_code` for calculations or data processing
- Use `save_memory` / `recall_memory` to persist information across sessions
"""


def create_agent(agent_dir: str) -> None:
    """Create a new agent folder with template files.

    Args:
        agent_dir: Path for the new agent directory.

    Raises:
        FileExistsError: If the directory already exists.
    """
    path = Path(agent_dir)
    if path.exists():
        raise FileExistsError(f"Agent directory already exists: {agent_dir}")

    path.mkdir(parents=True)
    name = path.name

    (path / "config.yaml").write_text(_CONFIG_TEMPLATE.format(name=name))
    (path / "instructions.md").write_text(_INSTRUCTIONS_TEMPLATE)
    (path / "tools.md").write_text(_TOOLS_TEMPLATE)
