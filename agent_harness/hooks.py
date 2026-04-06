"""Safety hooks for tool call filtering and output scanning."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

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


_NETWORK_COMMAND_PATTERNS = [
    r"\bcurl\b",
    r"\bwget\b",
    r"\bnc\b",
    r"\bncat\b",
]

_NETWORK_CODE_PATTERNS = [
    r"\brequests\.",
    r"\burllib\b",
    r"\bhttp\.client\b",
]


DomainPromptFn = Callable[[str], bool]

_URL_PATTERN = re.compile(r"https?://([^/\s:]+)")


def _extract_domain(text: str) -> str | None:
    """Extract the first domain from a URL in text.

    Args:
        text: Text that may contain a URL.

    Returns:
        Domain string or None.
    """
    match = _URL_PATTERN.search(text)
    return match.group(1) if match else None


def _has_network_intent(tool_call: ToolCall) -> tuple[bool, str]:
    """Check if a tool call involves network access.

    Args:
        tool_call: The tool call to check.

    Returns:
        Tuple of (is_network, text_to_scan).
    """
    if tool_call.name == "run_command":
        command = tool_call.arguments.get("command", "")
        for pattern in _NETWORK_COMMAND_PATTERNS:
            if re.search(pattern, command):
                return True, command
    elif tool_call.name == "execute_code":
        code = tool_call.arguments.get("code", "")
        for pattern in _NETWORK_CODE_PATTERNS:
            if re.search(pattern, code):
                return True, code
    return False, ""


def _make_network_blocker(
    allowed_domains: set[str],
    prompt_fn: DomainPromptFn | None = None,
    persist_path: str | None = None,
) -> BeforeHook:
    """Create a network exfiltration blocker with domain whitelist.

    Args:
        allowed_domains: Pre-approved domains.
        prompt_fn: Callback to ask user about new domains.
        persist_path: Path to save approved domains.

    Returns:
        A before-tool hook function.
    """
    def blocker(tool_call: ToolCall) -> ToolCall | None:
        is_network, text = _has_network_intent(tool_call)
        if not is_network:
            return tool_call

        domain = _extract_domain(text)
        if domain and domain in allowed_domains:
            return tool_call

        if domain and prompt_fn and prompt_fn(domain):
            allowed_domains.add(domain)
            if persist_path:
                Path(persist_path).write_text(yaml.dump({"domains": sorted(allowed_domains)}))
            logger.info("Domain whitelisted: %s", domain)
            return tool_call

        logger.warning("Blocked network access: %s", text[:80])
        return None

    return blocker


_SECRETS_PATTERNS = [
    (r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{6,}", "API key"),
    (r"ghp_[A-Za-z0-9]{6,}", "GitHub token"),
    (r"AKIA[A-Z0-9]{12,}", "AWS access key"),
    (r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", "private key"),
]


def secrets_leakage_scanner(tool_call: ToolCall, result: ToolResult) -> ToolResult:
    """Redact secrets from tool output before they reach the LLM.

    Args:
        tool_call: The tool call that produced the result.
        result: The tool result to scan.

    Returns:
        Result with secrets redacted, or original if clean.
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
    "path_traversal_detector": path_traversal_detector,
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


class Hooks:
    """Chainable safety hooks for tool calls and results.

    Args:
        hook_config: Dict with optional 'before_tool', 'after_tool', 'allowed_domains'.
        domain_prompt_fn: Callback to ask user about new domains.
        agent_dir: Agent directory for persisting domain whitelist.
    """

    def __init__(
        self,
        hook_config: dict[str, Any],
        domain_prompt_fn: DomainPromptFn | None = None,
        agent_dir: str | None = None,
    ) -> None:
        before_names: list[str] = hook_config.get("before_tool", _DEFAULT_BEFORE)
        self._before: list[BeforeHook] = []
        for name in before_names:
            if name == "network_exfiltration_blocker":
                self._before.append(self._build_network_blocker(hook_config, domain_prompt_fn, agent_dir))
            else:
                self._before.append(_BEFORE_REGISTRY[name])
        self._after: list[AfterHook] = [
            _AFTER_REGISTRY[name] for name in hook_config.get("after_tool", _DEFAULT_AFTER)
        ]

    def _build_network_blocker(
        self,
        hook_config: dict[str, Any],
        prompt_fn: DomainPromptFn | None,
        agent_dir: str | None,
    ) -> BeforeHook:
        """Build a network blocker with whitelist from config and disk.

        Args:
            hook_config: Hook configuration dict.
            prompt_fn: Domain approval callback.
            agent_dir: Agent directory for persistence.

        Returns:
            Configured network blocker hook.
        """
        allowed = set(hook_config.get("allowed_domains", []))
        persist_path = None
        if agent_dir:
            persist_path = str(Path(agent_dir) / ".allowed_domains.yaml")
            persist_file = Path(persist_path)
            if persist_file.exists():
                data = yaml.safe_load(persist_file.read_text())
                if data and "domains" in data:
                    allowed.update(data["domains"])
        return _make_network_blocker(allowed, prompt_fn, persist_path)

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
