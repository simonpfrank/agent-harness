"""Builds the `LoopCallbacks` a prepared runtime uses to drive display, tool
execution, and budget handling for one run."""

from __future__ import annotations

from collections.abc import Callable

from agent_harness.budget import Budget
from agent_harness.display import (
    show_budget,
    show_completion_status,
    show_delta,
    show_response,
    show_thinking_delta,
    show_thrash_warning,
    show_tool_call,
    show_tool_result,
)
from agent_harness.hooks import Hooks
from agent_harness.permissions import Permissions
from agent_harness.tools import execute_tool
from agent_harness.trace import Tracer
from agent_harness.types import (
    LoopCallbacks,
    OnPlanApproval,
    OutputSink,
    Response,
    ToolCall,
    ToolResult,
    Usage,
)


class _NullTracer:
    def record(self, _event: str, **_data: object) -> None:
        return


def make_callbacks(
    budget: Budget,
    hooks: Hooks,
    permissions: Permissions,
    tracer: Tracer | _NullTracer,
    tool_registry: dict[str, Callable[..., str]],
    max_output_chars: int,
    show_output: bool,
    stream: bool = False,
    show_thinking: bool = False,
    plan_prompt_fn: OnPlanApproval | None = None,
    tmp_dir: str = "tmp",
    output_sink: OutputSink | None = None,
) -> LoopCallbacks:
    def on_delta(agent_id: str, text: str) -> None:
        if show_output:
            show_delta(text)
        if output_sink and output_sink.on_delta:
            output_sink.on_delta(agent_id, text)

    def on_thinking_delta(agent_id: str, text: str) -> None:
        if show_output and show_thinking:
            show_thinking_delta(text)
        if output_sink and output_sink.on_thinking_delta:
            output_sink.on_thinking_delta(agent_id, text)

    def on_response(response: Response) -> None:
        if show_output and not stream:
            show_response(response)
        tracer.record(
            "turn",
            stop_reason=response.stop_reason,
            response=response.message.content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def _report_tool_result(result: ToolResult) -> None:
        if show_output:
            show_tool_result(result)
        if output_sink and output_sink.on_tool_result:
            output_sink.on_tool_result(result)

    def on_tool_call(tool_call: ToolCall) -> ToolResult:
        if show_output:
            show_tool_call(tool_call)
        if output_sink and output_sink.on_tool_call:
            output_sink.on_tool_call(tool_call)
        checked = hooks.run_before_tool(tool_call)
        if checked is None:
            tracer.record("tool_blocked", tool=tool_call.name, reason="safety_hook", args=tool_call.arguments)
            result = ToolResult(tool_call_id=tool_call.id, error="Blocked by safety hook")
            _report_tool_result(result)
            return result
        if not permissions.check(checked):
            tracer.record("tool_denied", tool=checked.name, reason="user_denied", args=checked.arguments)
            result = ToolResult(tool_call_id=checked.id, error="Denied by user")
            _report_tool_result(result)
            return result
        tracer.record("tool_call", tool=checked.name, args=checked.arguments)
        result = execute_tool(checked, max_output_chars=max_output_chars, tool_registry=tool_registry, tmp_dir=tmp_dir)
        result = hooks.run_after_tool(checked, result)
        tracer.record("tool_result", tool=checked.name, output=result.output, error=result.error)
        _report_tool_result(result)
        return result

    def on_budget(usage: Usage) -> bool:
        exceeded = budget.record(usage)
        summary = budget.summary()
        summary += f" | {usage.input_tokens / 1000:.1f}k in / {usage.output_tokens / 1000:.1f}k out"
        if exceeded:
            summary += " — stopping (budget limit reached, task may be incomplete)"
        if show_output:
            show_budget(summary)
        if output_sink and output_sink.on_budget:
            output_sink.on_budget(summary)
        tracer.record("budget", summary=budget.summary(), exceeded=exceeded)
        return exceeded

    def is_budget_exceeded() -> bool:
        return budget.is_exceeded()

    def on_completion_status(verified: bool, detail: str) -> None:
        if show_output:
            show_completion_status(verified, detail)
        if output_sink and output_sink.on_completion_status:
            output_sink.on_completion_status(verified, detail)
        tracer.record("completion_status", verified=verified, detail=detail)

    def on_thrash_detected(tool_name: str, detail: str) -> None:
        if show_output:
            show_thrash_warning(tool_name, detail)
        if output_sink and output_sink.on_thrash_detected:
            output_sink.on_thrash_detected(tool_name, detail)
        tracer.record("thrash_detected", tool=tool_name, detail=detail)

    on_plan_approval: OnPlanApproval | None = None
    if plan_prompt_fn is not None:
        def _on_plan_approval(steps: list[str]) -> bool:
            approved = plan_prompt_fn(steps)
            tracer.record("plan_approval", steps=steps, approved=approved)
            return approved
        on_plan_approval = _on_plan_approval

    return LoopCallbacks(
        on_response=on_response,
        on_tool_call=on_tool_call,
        on_budget=on_budget,
        get_budget_status=budget.status_note,
        on_plan_approval=on_plan_approval,
        on_delta=on_delta,
        on_thinking_delta=on_thinking_delta,
        on_completion_status=on_completion_status,
        is_budget_exceeded=is_budget_exceeded,
        on_thrash_detected=on_thrash_detected,
    )
