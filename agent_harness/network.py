"""Network exfiltration blocker with domain whitelist."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from agent_harness.types import ToolCall

logger = logging.getLogger(__name__)

DomainPromptFn = Callable[[str], bool]

BeforeHook = Callable[[ToolCall], ToolCall | None]

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


def make_network_blocker(
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
                try:
                    Path(persist_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(persist_path).write_text(yaml.dump({"domains": sorted(allowed_domains)}))
                except OSError:
                    logger.warning("Could not save domain whitelist to %s", persist_path)
            logger.info("Domain whitelisted: %s", domain)
            return tool_call

        logger.warning("Blocked network access: %s", text[:80])
        return None

    return blocker


def load_allowed_domains(hook_config: dict[str, Any], agent_dir: str | None) -> set[str]:
    """Load allowed domains from config and persistent file.

    Args:
        hook_config: Hook configuration dict.
        agent_dir: Agent directory for persistence file.

    Returns:
        Set of allowed domain strings.
    """
    allowed = set(hook_config.get("allowed_domains", []))
    if agent_dir:
        persist_file = Path(agent_dir) / ".allowed_domains.yaml"
        if persist_file.exists():
            data = yaml.safe_load(persist_file.read_text())
            if data and "domains" in data:
                allowed.update(data["domains"])
    return allowed


def persist_path_for(agent_dir: str | None) -> str | None:
    """Get the persistence file path for an agent directory.

    Args:
        agent_dir: Agent directory, or None.

    Returns:
        Path string, or None.
    """
    return str(Path(agent_dir) / ".allowed_domains.yaml") if agent_dir else None
