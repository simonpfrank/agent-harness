"""Load and validate agent configuration from a folder."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_harness.loops import registry as loop_registry
from agent_harness.providers import registry as provider_registry
from agent_harness.tools import registry as tool_registry
from agent_harness.types import AgentConfig


def load(agent_dir: str) -> AgentConfig:
    """Load an AgentConfig from an agent directory.

    Args:
        agent_dir: Path to agent folder containing config.yaml and instructions.md.

    Returns:
        Populated AgentConfig.

    Raises:
        FileNotFoundError: If agent_dir, config.yaml, or instructions.md missing.
        ValueError: If provider, tools, or loop are not in their registries.
    """
    base = Path(agent_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    config_path = base / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found in {agent_dir}")

    instructions_path = base / "instructions.md"
    if not instructions_path.exists():
        raise FileNotFoundError(f"instructions.md not found in {agent_dir}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    instructions = instructions_path.read_text()

    tools_guidance: str | None = None
    tools_path = base / "tools.md"
    if tools_path.exists():
        tools_guidance = tools_path.read_text()

    provider = raw.get("provider", "anthropic")
    if provider not in provider_registry:
        raise ValueError(f"Unknown provider: {provider}")

    tools: list[str] = raw.get("tools", [])
    for tool_name in tools:
        if tool_name not in tool_registry:
            raise ValueError(f"Unknown tool: {tool_name}")

    loop = raw.get("loop", "react")
    if loop not in loop_registry:
        raise ValueError(f"Unknown loop: {loop}")

    max_turns = raw.get("max_turns", 10)
    if max_turns < 1:
        raise ValueError(f"max_turns must be > 0, got {max_turns}")

    return AgentConfig(
        name=raw.get("name", base.name),
        provider=provider,
        model=raw.get("model", "claude-haiku-4-5-20251001"),
        agent_dir=agent_dir,
        instructions=instructions,
        tools_guidance=tools_guidance,
        tools=tools,
        loop=loop,
        max_turns=max_turns,
        max_cost=raw.get("max_cost"),
        permissions=raw.get("permissions", {}),
        hooks=raw.get("hooks", {}),
    )
