"""Agent-as-tool routing — delegate tasks to sub-agents."""

from __future__ import annotations

from typing import Any

from agent_harness.config import load
from agent_harness.runtime import deny_permission, prepare_runtime
from agent_harness.types import Message

agents_dir: str = "agents"
max_agent_depth: int = 3
_call_depth: int = 0


def _load_and_run(agent_name: str, messages: list[Message]) -> str:
    """Load a sub-agent config and run it with the given messages.

    Args:
        agent_name: Agent folder name relative to `agents_dir`.
        messages: Existing conversation to continue.

    Returns:
        Final assistant text from the delegated agent.
    """
    config = load(f"{agents_dir}/{agent_name}")
    runtime = prepare_runtime(
        config,
        permission_prompt_fn=deny_permission,
        show_output=False,
        trace_enabled=False,
    )
    active_messages = runtime.init_messages(existing_messages=messages)
    try:
        return runtime.run_messages(active_messages)
    finally:
        runtime.finalize()


def _with_depth_check(fn: Any, *args: Any) -> str:
    """Run a function with agent call depth tracking.

    Args:
        fn: Function to execute.
        *args: Positional arguments passed to `fn`.

    Returns:
        Result from `fn`.

    Raises:
        RuntimeError: If the configured delegation depth would be exceeded.
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
        agent_name: Agent folder name relative to `agents_dir`.
        message: User message to send to the delegated agent.

    Returns:
        Final assistant text from the delegated agent.
    """

    def _run() -> str:
        config = load(f"{agents_dir}/{agent_name}")
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=deny_permission,
            show_output=False,
            trace_enabled=False,
        )
        messages = runtime.init_messages()
        try:
            return runtime.run_messages(messages, prompt=message)
        finally:
            runtime.finalize()

    return _with_depth_check(_run)


def handoff_agent(agent_name: str, messages: list[Message]) -> str:
    """Hand off conversation to another agent, continuing the same context.

    Args:
        agent_name: Agent folder name relative to `agents_dir`.
        messages: Existing conversation history to continue.

    Returns:
        Final assistant text from the delegated agent.
    """
    return _with_depth_check(_load_and_run, agent_name, messages)
