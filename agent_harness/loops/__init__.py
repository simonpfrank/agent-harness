"""Loop registry."""

from __future__ import annotations

from collections.abc import Callable

from agent_harness.loops import debate, eval_optimize, plan_execute, ralph, react, reflection, rewoo

registry: dict[str, Callable[..., str]] = {
    "react": react.run,
    "plan_execute": plan_execute.run,
    "rewoo": rewoo.run,
    "reflection": reflection.run,
    "eval_optimize": eval_optimize.run,
    "ralph": ralph.run,
    "debate": debate.run,
}
