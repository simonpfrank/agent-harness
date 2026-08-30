"""API-specific implementations of the harness's pluggable callbacks.

Each factory here mirrors one of `cli.py`'s console-driven callbacks
(`_permission_prompt`, `_domain_prompt`, `_plan_prompt`) or the new
`OutputSink` hooks, wired to a `RunRegistry` + run id instead of terminal
I/O — the same "supply your own callback" extension point, a different
transport.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from agent_harness.api import events
from agent_harness.api.events import SseEvent
from agent_harness.api.registry import RunRegistry
from agent_harness.permissions import PermissionDecision
from agent_harness.types import OutputSink, ToolCall, ToolResult

APPROVAL_TIMEOUT_SECONDS = 300.0  # default-deny past this — see docs/roadmap.md's "HTTP API server" entry


class SeqCounter:
    """Per-run monotonic sequence number for the SSE `id:` field.

    Not thread-safe by design: a single run's harness loop (and therefore
    all its callback invocations) executes on one worker thread; only the
    separate signal-endpoint thread ever touches the registry concurrently,
    and it never pushes events.
    """

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n


class CompletionStatus:
    """Captures the loop's last `on_completion_status` call, if any, for
    the route handler to fold into the final `done` event."""

    def __init__(self) -> None:
        self.verified: bool | None = None
        self.detail: str | None = None


def _await_approval(
    registry: RunRegistry,
    run_id: str,
    seq: SeqCounter,
    kind: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any] | None:
    approval_id = uuid.uuid4().hex
    registry.try_push_event(
        run_id,
        SseEvent(
            event=events.APPROVAL_NEEDED,
            data={"approval_id": approval_id, "kind": kind, **payload},
            seq=seq.next(),
        ),
    )
    return registry.await_signal(run_id, approval_id, timeout=timeout)


def make_permission_prompt(
    registry: RunRegistry, run_id: str, seq: SeqCounter, timeout: float = APPROVAL_TIMEOUT_SECONDS,
) -> Callable[[ToolCall], PermissionDecision]:
    """Build a permission-prompt callback that blocks on a real approval reply.

    Args:
        registry: Shared run registry.
        run_id: Run this prompt belongs to.
        seq: This run's sequence counter.
        timeout: Max seconds to wait before default-denying.

    Returns:
        Callback matching `runtime.PermissionPromptFn`'s shape.
    """
    def prompt(tool_call: ToolCall) -> PermissionDecision:
        result = _await_approval(
            registry, run_id, seq, "tool",
            {"tool_name": tool_call.name, "arguments": tool_call.arguments},
            timeout,
        )
        decision = result.get("decision") if result is not None else None
        if decision == "allow_once":
            return PermissionDecision.allow_once()
        if decision == "allow_session":
            return PermissionDecision.allow_session()
        if decision == "allow_persistent":
            return PermissionDecision.allow_persistent()
        return PermissionDecision.deny()
    return prompt


def make_domain_prompt(
    registry: RunRegistry, run_id: str, seq: SeqCounter, timeout: float = APPROVAL_TIMEOUT_SECONDS,
) -> Callable[[str], bool]:
    """Build a domain-prompt callback that blocks on a real approval reply.

    Args:
        registry: Shared run registry.
        run_id: Run this prompt belongs to.
        seq: This run's sequence counter.
        timeout: Max seconds to wait before default-denying.

    Returns:
        Callback matching `runtime.DomainPromptFn`'s shape.
    """
    def prompt(domain: str) -> bool:
        result = _await_approval(registry, run_id, seq, "domain", {"domain": domain}, timeout)
        return result is not None and result.get("decision") == "allow"
    return prompt


def make_plan_prompt(
    registry: RunRegistry, run_id: str, seq: SeqCounter, timeout: float = APPROVAL_TIMEOUT_SECONDS,
) -> Callable[[list[str]], bool]:
    """Build a plan-approval callback that blocks on a real approval reply.

    Args:
        registry: Shared run registry.
        run_id: Run this prompt belongs to.
        seq: This run's sequence counter.
        timeout: Max seconds to wait before default-denying.

    Returns:
        Callback matching `types.OnPlanApproval`'s shape.
    """
    def prompt(steps: list[str]) -> bool:
        result = _await_approval(registry, run_id, seq, "plan", {"plan_steps": steps}, timeout)
        return result is not None and result.get("decision") == "approve"
    return prompt


def build_output_sink(
    registry: RunRegistry, run_id: str, seq: SeqCounter, completion_status: CompletionStatus,
) -> OutputSink:
    """Build an `OutputSink` that pushes run events onto the registry's queue.

    Args:
        registry: Shared run registry.
        run_id: Run this sink belongs to.
        seq: This run's sequence counter.
        completion_status: Mutated in place when `on_completion_status`
            fires — the route handler reads it after the run finishes.

    Returns:
        An `OutputSink` ready to pass into `prepare_runtime`.
    """
    def on_delta(agent_id: str, text: str) -> None:
        registry.try_push_event(run_id, SseEvent(events.DELTA, {"agent": agent_id, "text": text}, seq.next()))

    def on_thinking_delta(agent_id: str, text: str) -> None:
        registry.try_push_event(
            run_id, SseEvent(events.THINKING_DELTA, {"agent": agent_id, "text": text}, seq.next()),
        )

    def on_tool_call(tool_call: ToolCall) -> None:
        data = {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments}
        registry.try_push_event(run_id, SseEvent(events.TOOL_CALL, data, seq.next()))

    def on_tool_result(result: ToolResult) -> None:
        data = {
            "tool_call_id": result.tool_call_id,
            "output": result.output,
            "error": result.error,
            "has_attachment": result.attachment is not None,
        }
        registry.try_push_event(run_id, SseEvent(events.TOOL_RESULT, data, seq.next()))

    def on_budget(summary: str) -> None:
        registry.try_push_event(run_id, SseEvent(events.BUDGET, {"summary": summary}, seq.next()))

    def on_completion_status(verified: bool, detail: str) -> None:
        completion_status.verified = verified
        completion_status.detail = detail

    def on_thrash_detected(tool_name: str, detail: str) -> None:
        data = {"tool": tool_name, "detail": detail}
        registry.try_push_event(run_id, SseEvent(events.THRASH_WARNING, data, seq.next()))

    return OutputSink(
        on_delta=on_delta,
        on_thinking_delta=on_thinking_delta,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        on_budget=on_budget,
        on_completion_status=on_completion_status,
        on_thrash_detected=on_thrash_detected,
    )
