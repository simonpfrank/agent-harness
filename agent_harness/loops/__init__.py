"""Loop registry."""

from __future__ import annotations

from collections.abc import Callable

from agent_harness.loops import plan_execute, react

registry: dict[str, Callable[..., str]] = {
    "react": react.run,
    "plan_execute": plan_execute.run,
}
