"""Tool permission system with session memory and persistence."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from agent_harness.types import ToolCall

logger = logging.getLogger(__name__)

PromptFn = Callable[[ToolCall], bool]


class Permissions:
    """Tool approval with three tiers: always_allow, always_ask, session memory.

    Inert by default — if no config is provided, all tools are allowed.

    Args:
        perm_config: Dict with optional 'always_allow' and 'always_ask' lists.
        prompt_fn: Callback that asks the user for approval. Returns True if approved.
        persist_path: Optional path to save/load persistent permissions.
    """

    def __init__(
        self,
        perm_config: dict[str, Any],
        prompt_fn: PromptFn,
        persist_path: str | None = None,
    ) -> None:
        self._always_allow: set[str] = set(perm_config.get("always_allow", []))
        self._always_ask: set[str] = set(perm_config.get("always_ask", []))
        self._active = bool(self._always_allow or self._always_ask)
        self._prompt_fn = prompt_fn
        self._session_approved: set[str] = set()
        self._persist_path = persist_path
        self._persistent_approved: set[str] = set()

    def check(self, tool_call: ToolCall) -> bool:
        """Check if a tool call is approved.

        Args:
            tool_call: The tool call to check.

        Returns:
            True if the tool call is approved.
        """
        if not self._active:
            return True

        name = tool_call.name

        if name in self._always_allow:
            return True

        if name in self._always_ask:
            approved = self._prompt_fn(tool_call)
            logger.info("Tool %s: user %s", name, "approved" if approved else "denied")
            return approved

        # Default tier: check session/persistent memory, then ask once
        if name in self._session_approved or name in self._persistent_approved:
            return True

        approved = self._prompt_fn(tool_call)
        if approved:
            self._session_approved.add(name)
            logger.info("Tool %s: session-approved", name)
        return approved

    def save(self) -> None:
        """Save persistent permissions to disk."""
        if not self._persist_path:
            return
        try:
            persist = Path(self._persist_path)
            persist.parent.mkdir(parents=True, exist_ok=True)
            all_approved = sorted(self._session_approved | self._persistent_approved)
            persist.write_text(yaml.dump({"approved": all_approved}))
        except OSError:
            logger.warning("Could not save permissions to %s", self._persist_path)

    def load(self) -> None:
        """Load persistent permissions from disk."""
        if not self._persist_path:
            return
        path = Path(self._persist_path)
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text())
        if data and "approved" in data:
            self._persistent_approved = set(data["approved"])
