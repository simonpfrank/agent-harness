"""Agent-as-tool routing — delegate tasks to sub-agents."""

from __future__ import annotations

from typing import Any

from agent_harness.types import Message

agents_dir: str = "agents"
max_agent_depth: int = 3
_call_depth: int = 0


def _load_and_run(agent_name: str, messages: list[Message]) -> str:
    """Load a sub-agent config and run it with the given messages.

    Args:
        agent_name: Agent folder name (relative to agents_dir).
        messages: Conversation messages to run.

    Returns:
        Final text response from the sub-agent.
    """
    from agent_harness.budget import Budget
    from agent_harness.config import load
    from agent_harness.loops import registry as loop_registry
    from agent_harness.providers import registry as provider_registry
    from agent_harness.tools import generate_schema, registry
    from agent_harness.types import LoopCallbacks, Usage

    config = load(f"{agents_dir}/{agent_name}")
    chat_fn = provider_registry[config.provider]
    loop_fn = loop_registry[config.loop]
    budget = Budget(config)

    def on_budget(usage: Usage) -> bool:
        return budget.record(usage)

    schemas = [generate_schema(registry[t]) for t in config.tools]
    cb = LoopCallbacks(on_budget=on_budget)
    return loop_fn(chat_fn, messages, schemas, config, cb)


def _with_depth_check(fn: Any, *args: Any) -> str:
    """Run a function with agent call depth tracking.

    Args:
        fn: Function to call.
        *args: Arguments to pass.

    Returns:
        Result from fn.

    Raises:
        RuntimeError: If depth exceeds max_agent_depth.
    """
    global _call_depth  # noqa: PLW0603
    if _call_depth >= max_agent_depth:
        raise RuntimeError(f"Agent call depth limit exceeded ({max_agent_depth})")
    _call_depth += 1
    try:
        return fn(*args)  # type: ignore[no-any-return]
    finally:
        _call_depth -= 1


def run_agent(agent_name: str, message: str) -> str:
    """Run another agent and return its response.

    Args:
        agent_name: Name of the agent folder (relative to agents directory).
        message: The message to send to the agent.

    Returns:
        Final text response from the sub-agent.

    Raises:
        RuntimeError: If agent call depth exceeds max_agent_depth.
    """
    def _run() -> str:
        from agent_harness.config import load
        config = load(f"{agents_dir}/{agent_name}")
        messages = [
            Message(role="system", content=config.instructions),
            Message(role="user", content=message),
        ]
        return _load_and_run(agent_name, messages)

    return _with_depth_check(_run)


def handoff_agent(agent_name: str, messages: list[Message]) -> str:
    """Hand off conversation to another agent, continuing the same context.

    Args:
        agent_name: Name of the agent folder (relative to agents directory).
        messages: Existing conversation messages to continue.

    Returns:
        Final text response from the sub-agent.

    Raises:
        RuntimeError: If agent call depth exceeds max_agent_depth.
    """
    return _with_depth_check(_load_and_run, agent_name, messages)
