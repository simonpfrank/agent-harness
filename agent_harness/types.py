"""Shared dataclasses and type aliases for agent_harness.

No internal imports. This is the dependency root.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of executing a tool call."""

    tool_call_id: str
    output: str | None = None
    error: str | None = None


@dataclass
class Message:
    """A single message in the conversation."""

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_result: ToolResult | None = None


@dataclass
class Usage:
    """Token usage for a single LLM call."""

    input_tokens: int
    output_tokens: int


@dataclass
class Response:
    """An LLM response with metadata."""

    message: Message
    usage: Usage
    stop_reason: str


@dataclass
class AgentConfig:
    """Configuration loaded from an agent folder."""

    name: str
    provider: str
    model: str
    agent_dir: str
    instructions: str
    tools_guidance: str | None = None
    tools: list[str] = field(default_factory=list)
    loop: str = "react"
    max_turns: int = 10
    max_cost: float | None = None
    permissions: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] = field(default_factory=dict)


# Callback type aliases
OnResponse = Callable[[Response], None]
OnToolCall = Callable[[ToolCall], ToolResult | None]
OnBudget = Callable[[Usage], bool]


@dataclass
class LoopCallbacks:
    """Optional callbacks for the agent loop."""

    on_response: OnResponse | None = None
    on_tool_call: OnToolCall | None = None
    on_budget: OnBudget | None = None
