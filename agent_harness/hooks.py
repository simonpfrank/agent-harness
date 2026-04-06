"""Safety hooks for tool call filtering and output scanning."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from agent_harness.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)

BeforeHook = Callable[[ToolCall], ToolCall | None]
AfterHook = Callable[[ToolCall, ToolResult], ToolResult]

_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/",
]

_INJECTION_PATTERNS = [
    r"ignore\s+previous",
    r"^system:",
    r"<\|im_start\|>",
]


def dangerous_command_blocker(tool_call: ToolCall) -> ToolCall | None:
    """Block dangerous shell commands.

    Args:
        tool_call: The tool call to check.

    Returns:
        The tool call if safe, None if blocked.
    """
    if tool_call.name != "run_command":
        return tool_call
    command = tool_call.arguments.get("command", "")
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            logger.warning("Blocked dangerous command: %s", command)
            return None
    return tool_call


def path_traversal_detector(tool_call: ToolCall) -> ToolCall | None:
    """Block file operations with path traversal.

    Args:
        tool_call: The tool call to check.

    Returns:
        The tool call if safe, None if blocked.
    """
    values = " ".join(str(v) for v in tool_call.arguments.values())
    if ".." in values:
        logger.warning("Blocked path traversal: %s", values)
        return None
    return tool_call


def injection_scanner(tool_call: ToolCall, result: ToolResult) -> ToolResult:
    """Scan tool output for prompt injection patterns.

    Args:
        tool_call: The tool call that produced the result.
        result: The tool result to scan.

    Returns:
        Original result if clean, wrapped result if suspicious.
    """
    if result.error or not result.output:
        return result
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, result.output, re.IGNORECASE | re.MULTILINE):
            logger.warning("Injection pattern detected in output of %s", tool_call.name)
            wrapped = f"[EXTERNAL CONTENT WARNING]\n{result.output}\n[/EXTERNAL CONTENT WARNING]"
            return ToolResult(tool_call_id=result.tool_call_id, output=wrapped)
    return result


_BEFORE_REGISTRY: dict[str, BeforeHook] = {
    "dangerous_command_blocker": dangerous_command_blocker,
    "path_traversal_detector": path_traversal_detector,
}

_DEFAULT_BEFORE: list[str] = ["dangerous_command_blocker", "path_traversal_detector"]

_AFTER_REGISTRY: dict[str, AfterHook] = {
    "injection_scanner": injection_scanner,
}


class Hooks:
    """Chainable safety hooks for tool calls and results.

    Args:
        hook_config: Dict with optional 'before_tool' and 'after_tool' lists.
    """

    def __init__(self, hook_config: dict[str, Any]) -> None:
        before_names = hook_config["before_tool"] if "before_tool" in hook_config else _DEFAULT_BEFORE
        self._before: list[BeforeHook] = [_BEFORE_REGISTRY[name] for name in before_names]
        self._after: list[AfterHook] = [
            _AFTER_REGISTRY[name] for name in hook_config.get("after_tool", [])
        ]

    def run_before_tool(self, tool_call: ToolCall) -> ToolCall | None:
        """Run before-tool hooks in order. None from any hook blocks the call.

        Args:
            tool_call: The tool call to check.

        Returns:
            The (possibly modified) tool call, or None if blocked.
        """
        current = tool_call
        for hook in self._before:
            result = hook(current)
            if result is None:
                return None
            current = result
        return current

    def run_after_tool(self, tool_call: ToolCall, result: ToolResult) -> ToolResult:
        """Run after-tool hooks in order.

        Args:
            tool_call: The tool call that produced the result.
            result: The tool result to process.

        Returns:
            The (possibly modified) tool result.
        """
        current = result
        for hook in self._after:
            current = hook(tool_call, current)
        return current
