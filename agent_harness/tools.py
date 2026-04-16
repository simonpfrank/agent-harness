"""Tool registry, schema generation, and built-in tools."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_type_hints

from agent_harness.memory import list_memories, recall_memory, save_memory
from agent_harness.routing import run_agent
from agent_harness.types import ToolCall, ToolResult

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


registry: dict[str, Callable[..., str]] = {
    "run_command": run_command,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "execute_code": execute_code,
    "save_memory": save_memory,
    "recall_memory": recall_memory,
    "list_memories": list_memories,
    "run_agent": run_agent,
}
# Note: handoff_agent is available via agent_harness.routing but NOT
# registered as an LLM tool — its list[Message] parameter can't be
# serialised to JSON schema. Use it programmatically in custom loops.


_logger = logging.getLogger(__name__)

_BUILTIN_NAMES = set(registry.keys())


def discover_tools(tools_dir: str) -> None:
    """Discover and register custom tools from a directory.

    Each .py file should contain one public function with type annotations.
    Built-in tools are never overwritten.

    Args:
        tools_dir: Path to directory containing tool .py files.
    """
    path = Path(tools_dir)
    if not path.is_dir():
        return
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
                registry[name] = obj
                _logger.info("Registered custom tool: %s from %s", name, py_file.name)
                break  # one function per file
        except Exception as exc:
            _logger.warning("Failed to load tool from %s: %s", py_file.name, exc)


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
