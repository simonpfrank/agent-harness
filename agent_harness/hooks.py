"""Safety hooks for tool call filtering and output scanning."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_harness.network import (
    DomainPromptFn,
    load_allowed_domains,
    make_network_blocker,
    persist_path_for,
)
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

INJECTION_PATTERNS = [
    r"ignore\s+previous",
    r"^system:",
    r"<\|im_start\|>",
]

_SECRETS_PATTERNS = [
    (r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{6,}", "API key"),
    (r"ghp_[A-Za-z0-9]{6,}", "GitHub token"),
    (r"AKIA[A-Z0-9]{12,}", "AWS access key"),
    (r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", "private key"),
]

_PATH_ARGUMENT_NAMES = {"path", "file_path", "working_dir", "directory"}


def dangerous_command_blocker(tool_call: ToolCall) -> ToolCall | None:
    """Block dangerous shell commands.

    Args:
        tool_call: Tool call to inspect.

    Returns:
        The original tool call if it is safe, otherwise `None`.
    """
    if tool_call.name != "run_command":
        return tool_call
    command = tool_call.arguments.get("command", "")
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            logger.warning("Blocked dangerous command: %s", command)
            return None
    return tool_call


def _escapes_workspace(raw_path: str, workspace_root: Path) -> bool:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return False
    resolved = (workspace_root / candidate).resolve(strict=False)
    return not resolved.is_relative_to(workspace_root)


def path_traversal_detector(
    tool_call: ToolCall,
    workspace_root: Path | None = None,
) -> ToolCall | None:
    """Block relative path arguments that escape the workspace.

    Args:
        tool_call: Tool call to inspect.
        workspace_root: Base directory used to resolve relative paths. Defaults to cwd.

    Returns:
        The original tool call if path-like arguments stay within the workspace,
        otherwise `None`.
    """
    root = (workspace_root or Path.cwd()).resolve()
    for name, value in tool_call.arguments.items():
        if name not in _PATH_ARGUMENT_NAMES:
            continue
        if isinstance(value, str) and _escapes_workspace(value, root):
            logger.warning("Blocked path traversal in %s=%s", name, value)
            return None
    return tool_call


def injection_scanner(tool_call: ToolCall, result: ToolResult) -> ToolResult:
    """Scan tool output for prompt injection patterns.

    Args:
        tool_call: Tool call that produced the output.
        result: Raw tool result.

    Returns:
        Original result if clean, or a wrapped warning result if suspicious patterns
        were found.
    """
    if result.error or not result.output:
        return result
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, result.output, re.IGNORECASE | re.MULTILINE):
            logger.warning("Injection pattern detected in output of %s", tool_call.name)
            wrapped = f"[EXTERNAL CONTENT WARNING]\n{result.output}\n[/EXTERNAL CONTENT WARNING]"
            return ToolResult(tool_call_id=result.tool_call_id, output=wrapped)
    return result


def secrets_leakage_scanner(tool_call: ToolCall, result: ToolResult) -> ToolResult:
    """Redact secrets from tool output before they reach the LLM.

    Args:
        tool_call: Tool call that produced the output.
        result: Raw tool result.

    Returns:
        Original result if no secret-like values are found, otherwise a redacted copy.
    """
    if result.error or not result.output:
        return result
    output = result.output
    redacted = False
    for pattern, label in _SECRETS_PATTERNS:
        if re.search(pattern, output):
            output = re.sub(pattern, f"[REDACTED {label}]", output)
            redacted = True
    if redacted:
        logger.warning("Redacted secrets in output of %s", tool_call.name)
        return ToolResult(tool_call_id=result.tool_call_id, output=output)
    return result


_BEFORE_REGISTRY: dict[str, BeforeHook] = {
    "dangerous_command_blocker": dangerous_command_blocker,
}

_DEFAULT_BEFORE: list[str] = [
    "dangerous_command_blocker",
    "path_traversal_detector",
    "network_exfiltration_blocker",
]

_AFTER_REGISTRY: dict[str, AfterHook] = {
    "injection_scanner": injection_scanner,
    "secrets_leakage_scanner": secrets_leakage_scanner,
}

_DEFAULT_AFTER: list[str] = ["injection_scanner", "secrets_leakage_scanner"]


def _path_hook(tool_call: ToolCall, root_path: Path) -> ToolCall | None:
    """Run the path traversal detector with a bound root path."""
    return path_traversal_detector(tool_call, root_path)


class Hooks:
    """Chainable safety hooks for tool calls and results.

    Args:
        hook_config: Hook configuration from agent config.
        domain_prompt_fn: Optional callback used by the network blocker.
        agent_dir: Agent directory for persisted allowlists such as domains.
        workspace_root: Base directory used by path validation.
    """

    def __init__(
        self,
        hook_config: dict[str, Any],
        domain_prompt_fn: DomainPromptFn | None = None,
        agent_dir: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        before_names: list[str] = hook_config.get("before_tool", _DEFAULT_BEFORE)
        root_path = Path(workspace_root or ".").resolve()
        self._before: list[BeforeHook] = []
        for name in before_names:
            if name == "network_exfiltration_blocker":
                allowed = load_allowed_domains(hook_config, agent_dir)
                p_path = persist_path_for(agent_dir)
                self._before.append(make_network_blocker(allowed, domain_prompt_fn, p_path))
            elif name == "path_traversal_detector":
                self._before.append(lambda tc: _path_hook(tc, root_path))
            else:
                self._before.append(_BEFORE_REGISTRY[name])
        self._after: list[AfterHook] = [
            _AFTER_REGISTRY[name] for name in hook_config.get("after_tool", _DEFAULT_AFTER)
        ]

    def run_before_tool(self, tool_call: ToolCall) -> ToolCall | None:
        """Run before-tool hooks in order.

        Args:
            tool_call: Tool call to inspect.

        Returns:
            Possibly modified tool call, or `None` if any hook blocks the call.
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
            tool_call: Tool call that produced the result.
            result: Tool result to scan or modify.

        Returns:
            Possibly modified tool result after all after-tool hooks run.
        """
        current = result
        for hook in self._after:
            current = hook(tool_call, current)
        return current
