"""Load agent configuration from a folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_harness.types import AgentConfig


def _read_required_file(base: Path, filename: str, agent_dir: str) -> str:
    """Read a required file from the agent directory.

    Args:
        base: Agent directory path.
        filename: File to read.
        agent_dir: Original agent_dir string for error messages.

    Returns:
        File contents as string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = base / filename
    if not path.exists():
        raise FileNotFoundError(f"{filename} not found in {agent_dir}")
    return path.read_text()


def load(agent_dir: str) -> AgentConfig:
    """Load an AgentConfig from an agent directory.

    Reads config.yaml, instructions.md, and optional tools.md.
    Does not validate against registries — that is the caller's job.

    Args:
        agent_dir: Path to agent folder containing config.yaml and instructions.md.

    Returns:
        Populated AgentConfig.

    Raises:
        FileNotFoundError: If agent_dir, config.yaml, or instructions.md missing.
    """
    base = Path(agent_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    raw_loaded = yaml.safe_load(_read_required_file(base, "config.yaml", agent_dir))
    if not isinstance(raw_loaded, dict):
        raise ValueError(f"config.yaml must contain a YAML mapping, got {type(raw_loaded).__name__}")
    raw: dict[str, Any] = raw_loaded
    instructions = _read_required_file(base, "instructions.md", agent_dir)

    tools_path = base / "tools.md"
    tools_guidance = tools_path.read_text() if tools_path.exists() else None

    return AgentConfig(
        name=raw.get("name", base.name),
        provider=raw.get("provider", "anthropic"),
        model=raw.get("model", "claude-haiku-4-5-20251001"),
        agent_dir=agent_dir,
        instructions=instructions,
        tools_guidance=tools_guidance,
        tools=raw.get("tools", []),
        loop=raw.get("loop", "react"),
        max_turns=raw.get("max_turns", 10),
        max_cost=raw.get("max_cost"),
        executor=raw.get("executor", "subprocess"),
        tool_timeout=raw.get("tool_timeout", 30),
        max_output_chars=raw.get("max_output_chars", 10_000),
        provider_kwargs=raw.get("provider_kwargs", {}),
        permissions=raw.get("permissions", {}),
        hooks=raw.get("hooks", {}),
    )
