"""Tool registry, schema generation, and built-in tools."""

from __future__ import annotations

import inspect
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_type_hints

from agent_harness.types import Message, ToolCall, ToolResult

tool_timeout: int = 30

_TYPE_MAP: dict[type[Any], str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _parse_arg_descriptions(docstring: str) -> dict[str, str]:
    """Extract argument descriptions from Google-style docstring.

    Args:
        docstring: Full docstring text.

    Returns:
        Mapping of argument name to description.
    """
    descriptions: dict[str, str] = {}
    in_args = False
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            continue
        if in_args:
            if stripped == "" or (not stripped.startswith(" ") and ":" not in stripped and stripped.endswith(":")):
                break
            if ":" in stripped:
                name, desc = stripped.split(":", 1)
                descriptions[name.strip()] = desc.strip()
    return descriptions


def generate_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Generate JSON Schema from a typed function with docstring.

    Args:
        fn: Function to generate schema for

    Returns:
        Dict with name, description, and input_schema keys.
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    docstring = inspect.getdoc(fn) or ""
    first_line = docstring.split("\n")[0].strip()
    arg_descs = _parse_arg_descriptions(docstring)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "return":
            continue
        hint = hints.get(name, str)
        prop: dict[str, str] = {"type": _TYPE_MAP.get(hint, "string")}
        if name in arg_descs:
            prop["description"] = arg_descs[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "name": fn.__name__,
        "description": first_line,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def run_command(command: str, working_dir: str = ".") -> str:
    """Run a shell command and return its output.

    Args:
        command: The command to run (e.g. "ls -la")
        working_dir: Directory to run the command in

    Returns:
        Combined stdout and stderr output.
    """
    args = shlex.split(command)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=tool_timeout,
        cwd=working_dir,
    )
    output = result.stdout
    if result.stderr:
        output += result.stderr
    return output


def read_file(path: str) -> str:
    """Read a file and return its contents.

    Args:
        path: Path to the file to read

    Returns:
        File contents as string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    return Path(path).read_text()


def _subprocess_executor(code: str, language: str, timeout: int) -> str:
    """Execute code via subprocess.

    Args:
        code: The code to execute.
        language: python or bash.
        timeout: Execution timeout in seconds.

    Returns:
        Combined stdout and stderr output.
    """
    args = ["bash", "-c", code] if language == "bash" else [sys.executable, "-c", code]
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    output = result.stdout
    if result.stderr:
        output += result.stderr
    return output


Executor = Callable[[str, str, int], str]

executor_registry: dict[str, Executor] = {
    "subprocess": _subprocess_executor,
}

active_executor: str = "subprocess"


def execute_code(code: str, language: str = "python") -> str:
    """Execute a code snippet and return stdout and stderr.

    Delegates to the active executor (default: subprocess).

    Args:
        code: The code to execute
        language: python or bash

    Returns:
        Combined stdout and stderr output.
    """
    executor = executor_registry[active_executor]
    return executor(code, language, tool_timeout)


memory_dir: str = ""


_INJECTION_PATTERNS = [
    r"ignore\s+previous",
    r"^system:",
    r"<\|im_start\|>",
]


def save_memory(key: str, content: str) -> str:
    """Save information to long-term memory.

    Scans content for injection patterns before saving.

    Args:
        key: Memory key (used as filename).
        content: Content to save.

    Returns:
        Confirmation message.
    """
    import re

    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            content = f"[WARNING: content flagged by injection scanner]\n{content}"
            break
    mem_path = Path(memory_dir)
    mem_path.mkdir(parents=True, exist_ok=True)
    (mem_path / f"{key}.md").write_text(content)
    return f"Saved memory: {key}"


def recall_memory(key: str) -> str:
    """Recall information from long-term memory.

    Args:
        key: Memory key to recall.

    Returns:
        Stored content.

    Raises:
        FileNotFoundError: If the memory key doesn't exist.
    """
    return (Path(memory_dir) / f"{key}.md").read_text()


def list_memories() -> str:
    """List all saved memory keys.

    Returns:
        Newline-separated list of keys, or a message if empty.
    """
    mem_path = Path(memory_dir)
    if not mem_path.exists():
        return "No memories saved."
    keys = sorted(p.stem for p in mem_path.glob("*.md"))
    return "\n".join(keys) if keys else "No memories saved."


agents_dir: str = "agents"
max_agent_depth: int = 3
_call_depth: int = 0


def _run_sub_agent(agent_name: str, message: str) -> str:
    """Run a sub-agent to completion and return its response.

    Args:
        agent_name: Agent folder name (relative to agents_dir).
        message: Message to send to the sub-agent.

    Returns:
        Final text response from the sub-agent.
    """
    from agent_harness.budget import Budget
    from agent_harness.config import load
    from agent_harness.loops import registry as loop_registry
    from agent_harness.providers import registry as provider_registry

    agent_path = f"{agents_dir}/{agent_name}"
    config = load(agent_path)
    chat_fn = provider_registry[config.provider]
    loop_fn = loop_registry[config.loop]
    budget = Budget(config)

    from agent_harness.types import LoopCallbacks, Usage

    def on_budget(usage: Usage) -> bool:
        return budget.record(usage)

    schemas = [generate_schema(registry[t]) for t in config.tools]
    messages = [
        Message(role="system", content=config.instructions),
        Message(role="user", content=message),
    ]
    cb = LoopCallbacks(on_budget=on_budget)
    return loop_fn(chat_fn, messages, schemas, config, cb)


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
    global _call_depth  # noqa: PLW0603
    if _call_depth >= max_agent_depth:
        raise RuntimeError(f"Agent call depth limit exceeded ({max_agent_depth})")
    _call_depth += 1
    try:
        return _run_sub_agent(agent_name, message)
    finally:
        _call_depth -= 1


registry: dict[str, Callable[..., str]] = {
    "run_command": run_command,
    "read_file": read_file,
    "execute_code": execute_code,
    "save_memory": save_memory,
    "recall_memory": recall_memory,
    "list_memories": list_memories,
    "run_agent": run_agent,
}


_DEFAULT_MAX_OUTPUT = 10_000


def _truncate(output: str, max_chars: int) -> str:
    """Truncate output if it exceeds max_chars.

    Args:
        output: Raw output string.
        max_chars: Maximum allowed characters.

    Returns:
        Original or truncated output with message.
    """
    if len(output) <= max_chars:
        return output
    return output[:max_chars] + f"\n[truncated — {len(output)} chars total]"


def execute_tool(tool_call: ToolCall, max_output_chars: int = _DEFAULT_MAX_OUTPUT) -> ToolResult:
    """Execute a tool call and return the result.

    Args:
        tool_call: The tool invocation to execute.
        max_output_chars: Max output characters before truncation.

    Returns:
        ToolResult with output or error.
    """
    fn = registry.get(tool_call.name)
    if fn is None:
        return ToolResult(tool_call_id=tool_call.id, error=f"Unknown tool: {tool_call.name}")
    try:
        output = fn(**tool_call.arguments)
        output = _truncate(output, max_output_chars)
        return ToolResult(tool_call_id=tool_call.id, output=output)
    except Exception as exc:
        return ToolResult(tool_call_id=tool_call.id, error=str(exc))
