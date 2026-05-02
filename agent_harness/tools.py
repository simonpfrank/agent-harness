"""Tool registry, schema generation, and built-in tools."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_type_hints

from agent_harness.memory import list_memories as list_memories_for_dir
from agent_harness.memory import recall_memory as recall_memory_for_dir
from agent_harness.memory import save_memory as save_memory_for_dir
from agent_harness.types import ToolCall, ToolResult

_logger = logging.getLogger(__name__)

_TYPE_MAP: dict[type[Any], str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

_DEFAULT_TIMEOUT = 30
_DEFAULT_EXECUTOR = "subprocess"
_DEFAULT_MAX_OUTPUT = 10_000


@dataclass(frozen=True)
class ToolRuntimeContext:
    """Execution settings for a single run's tool registry."""

    memory_dir: str = "memory"
    tool_timeout: int = _DEFAULT_TIMEOUT
    executor: str = _DEFAULT_EXECUTOR


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
    return _run_command_impl(command, working_dir, _DEFAULT_TIMEOUT)


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


def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        path: Path to the file to write
        content: Content to write

    Returns:
        Confirmation with character count.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Written {len(content)} chars to {path}"


def list_directory(path: str = ".") -> str:
    """List files and directories at the given path.

    Args:
        path: Directory to list

    Returns:
        Newline-separated listing. Directories have a trailing slash.

    Raises:
        FileNotFoundError: If the path does not exist.
    """
    target = Path(path)
    if not target.is_dir():
        raise FileNotFoundError(f"Directory not found: {path}")
    entries = sorted(target.iterdir())
    if not entries:
        return "Directory is empty."
    lines = [f"{e.name}/" if e.is_dir() else e.name for e in entries]
    return "\n".join(lines)


def execute_code(code: str, language: str = "python") -> str:
    """Execute a code snippet and return stdout and stderr.

    Args:
        code: The code to execute
        language: python or bash

    Returns:
        Combined stdout and stderr output.
    """
    return _execute_code_impl(code, language, _DEFAULT_TIMEOUT, _DEFAULT_EXECUTOR)


def _run_command_impl(command: str, working_dir: str, timeout: int) -> str:
    args = shlex.split(command)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=working_dir,
    )
    output = result.stdout
    if result.stderr:
        output += result.stderr
    return output


def _subprocess_executor(code: str, language: str, timeout: int) -> str:
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


def _execute_code_impl(code: str, language: str, timeout: int, executor_name: str) -> str:
    executor = executor_registry[executor_name]
    return executor(code, language, timeout)


def _run_agent_tool(agent_name: str, message: str) -> str:
    """Run another agent and return its response.

    Args:
        agent_name: Name of the agent folder to run.
        message: Message to send to the sub-agent.
    """
    from agent_harness.routing import run_agent

    return run_agent(agent_name, message)


def build_tool_registry(context: ToolRuntimeContext | None = None) -> dict[str, Callable[..., str]]:
    """Build a tool registry for a specific runtime context.

    Args:
        context: Per-run execution settings. Defaults to static defaults.

    Returns:
        Mapping of tool name to callable.
    """
    ctx = context or ToolRuntimeContext()

    def run_command_tool(command: str, working_dir: str = ".") -> str:
        return _run_command_impl(command, working_dir, ctx.tool_timeout)

    def execute_code_tool(code: str, language: str = "python") -> str:
        return _execute_code_impl(code, language, ctx.tool_timeout, ctx.executor)

    def save_memory_tool(key: str, content: str) -> str:
        return save_memory_for_dir(key, content, ctx.memory_dir)

    def recall_memory_tool(key: str) -> str:
        return recall_memory_for_dir(key, ctx.memory_dir)

    def list_memories_tool() -> str:
        return list_memories_for_dir(ctx.memory_dir)

    run_command_tool.__name__ = "run_command"
    run_command_tool.__doc__ = run_command.__doc__
    execute_code_tool.__name__ = "execute_code"
    execute_code_tool.__doc__ = execute_code.__doc__
    save_memory_tool.__name__ = "save_memory"
    save_memory_tool.__doc__ = (
        "Save information to long-term memory.\n\n"
        "Args:\n"
        "    key: Memory key (used as filename).\n"
        "    content: Content to save.\n"
    )
    recall_memory_tool.__name__ = "recall_memory"
    recall_memory_tool.__doc__ = (
        "Recall information from long-term memory.\n\n"
        "Args:\n"
        "    key: Memory key to recall.\n"
    )
    list_memories_tool.__name__ = "list_memories"
    list_memories_tool.__doc__ = "List all saved memory keys."

    return {
        "run_command": run_command_tool,
        "read_file": read_file,
        "write_file": write_file,
        "list_directory": list_directory,
        "execute_code": execute_code_tool,
        "save_memory": save_memory_tool,
        "recall_memory": recall_memory_tool,
        "list_memories": list_memories_tool,
        "run_agent": _run_agent_tool,
    }


registry: dict[str, Callable[..., str]] = build_tool_registry()
_BUILTIN_NAMES = set(registry.keys())


def discover_tools(
    tools_dir: str,
    base_registry: dict[str, Callable[..., str]] | None = None,
) -> dict[str, Callable[..., str]]:
    """Discover and register custom tools from a directory.

    Each .py file should contain one public function with type annotations.
    Built-in tools are never overwritten.

    Args:
        tools_dir: Path to directory containing tool .py files.
        base_registry: Registry to extend. Defaults to the module-level registry.

    Returns:
        The registry that received discovered tools.
    """
    target_registry = base_registry if base_registry is not None else registry
    path = Path(tools_dir)
    if not path.is_dir():
        return target_registry
    for py_file in sorted(path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if name.startswith("_"):
                    continue
                hints = get_type_hints(obj)
                if "return" not in hints:
                    continue
                if name in _BUILTIN_NAMES:
                    _logger.warning("Custom tool '%s' skipped — would overwrite built-in", name)
                    continue
                target_registry[name] = obj
                _logger.info("Registered custom tool: %s from %s", name, py_file.name)
                break
        except Exception as exc:
            _logger.warning("Failed to load tool from %s: %s", py_file.name, exc)
    return target_registry


def _truncate(output: str, max_chars: int) -> str:
    """Truncate output if it exceeds max_chars."""
    if len(output) <= max_chars:
        return output
    return output[:max_chars] + f"\n[truncated — {len(output)} chars total]"


def execute_tool(
    tool_call: ToolCall,
    max_output_chars: int = _DEFAULT_MAX_OUTPUT,
    tool_registry: dict[str, Callable[..., str]] | None = None,
) -> ToolResult:
    """Execute a tool call and return the result.

    Args:
        tool_call: The tool invocation to execute.
        max_output_chars: Max output characters before truncation.
        tool_registry: Registry to use. Defaults to the module-level registry.

    Returns:
        ToolResult with output or error.
    """
    active_registry = tool_registry or registry
    fn = active_registry.get(tool_call.name)
    if fn is None:
        return ToolResult(tool_call_id=tool_call.id, error=f"Unknown tool: {tool_call.name}")
    try:
        output = fn(**tool_call.arguments)
        output = _truncate(output, max_output_chars)
        return ToolResult(tool_call_id=tool_call.id, output=output)
    except Exception as exc:
        return ToolResult(tool_call_id=tool_call.id, error=str(exc))
