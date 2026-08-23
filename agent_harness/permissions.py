"""Tool permission system with session memory and persistence."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from agent_harness.atomic_write import atomic_write_text
from agent_harness.types import ToolCall

logger = logging.getLogger(__name__)


class ApprovalMode(StrEnum):
    """Supported user approval modes for tool execution prompts."""

    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_PERSISTENT = "allow_persistent"


@dataclass(frozen=True)
class PermissionDecision:
    """Normalized result from a permission prompt.

    Attributes:
        approved: Whether the tool call should proceed.
        mode: How long the approval should be remembered.
    """

    approved: bool
    mode: ApprovalMode

    @classmethod
    def deny(cls) -> PermissionDecision:
        return cls(approved=False, mode=ApprovalMode.DENY)

    @classmethod
    def allow_once(cls) -> PermissionDecision:
        return cls(approved=True, mode=ApprovalMode.ALLOW_ONCE)

    @classmethod
    def allow_session(cls) -> PermissionDecision:
        return cls(approved=True, mode=ApprovalMode.ALLOW_SESSION)

    @classmethod
    def allow_persistent(cls) -> PermissionDecision:
        return cls(approved=True, mode=ApprovalMode.ALLOW_PERSISTENT)


PromptFn = Callable[[ToolCall], PermissionDecision | bool]


def _normalize_decision(decision: PermissionDecision | bool) -> PermissionDecision:
    """Normalize legacy boolean prompt results into explicit decisions.

    Args:
        decision: Prompt callback result.

    Returns:
        Explicit permission decision. Legacy `True` becomes session approval and
        `False` becomes denial.
    """
    if isinstance(decision, PermissionDecision):
        return decision
    if decision:
        return PermissionDecision.allow_session()
    return PermissionDecision.deny()


class Permissions:
    """Tool approval with three tiers: always_allow, always_ask, and remembered approvals.

    Inert by default — if no config is provided, all tools are allowed.

    Args:
        perm_config: Dict with optional 'always_allow' and 'always_ask' lists.
        prompt_fn: Callback that asks the user for approval.
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
        self._dirty = False
        self._lock = threading.Lock()

    def check(self, tool_call: ToolCall) -> bool:
        """Check if a tool call is approved.

        Parallel tool-call execution means this can now be called from
        multiple threads within the same turn. The whole method (after the
        immutable `_active` fast path) is serialized: `_prompt_fn` may be a
        blocking, interactive call (e.g. the CLI's `Console.input()`), and
        unserialized concurrent prompts would race on stdin/stdout as well
        as double-prompt for the same tool via a check-then-record race on
        the approved sets below.

        Args:
            tool_call: The tool call to check.

        Returns:
            True if the tool call is approved.
        """
        if not self._active:
            return True

        with self._lock:
            name = tool_call.name
            if name in self._always_allow:
                return True

            if name in self._always_ask:
                decision = _normalize_decision(self._prompt_fn(tool_call))
                logger.info("Tool %s: user %s", name, "approved" if decision.approved else "denied")
                return decision.approved

            if name in self._persistent_approved or name in self._session_approved:
                return True

            decision = _normalize_decision(self._prompt_fn(tool_call))
            if not decision.approved:
                logger.info("Tool %s: denied", name)
                return False
            if decision.mode is ApprovalMode.ALLOW_SESSION:
                self._session_approved.add(name)
            elif decision.mode is ApprovalMode.ALLOW_PERSISTENT:
                self._persistent_approved.add(name)
                self._dirty = True
            logger.info("Tool %s: approved via %s", name, decision.mode.value)
            return True

    def save(self) -> None:
        """Save persistent permissions to disk.

        Does nothing if no persistence path was configured or no persistent approvals
        changed during the current process.
        """
        if not self._persist_path or not self._dirty:
            return
        try:
            persist = Path(self._persist_path)
            persist.parent.mkdir(parents=True, exist_ok=True)
            approved = sorted(self._persistent_approved)
            atomic_write_text(persist, yaml.dump({"approved": approved}))
            self._dirty = False
        except OSError:
            logger.warning("Could not save permissions to %s", self._persist_path)

    def load(self) -> None:
        """Load persistent permissions from disk.

        Missing files are treated as "no saved approvals".
        """
        if not self._persist_path:
            return
        path = Path(self._persist_path)
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text())
        if data and "approved" in data:
            self._persistent_approved = set(data["approved"])
