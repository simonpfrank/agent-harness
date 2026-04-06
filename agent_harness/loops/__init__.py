"""Loop registry."""

from __future__ import annotations

from collections.abc import Callable

from agent_harness.loops import react

registry: dict[str, Callable[..., str]] = {
    "react": react.run,
}
