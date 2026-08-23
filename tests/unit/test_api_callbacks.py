"""Tests for agent_harness.api.callbacks."""

import threading

from agent_harness.api.callbacks import (
    CompletionStatus,
    SeqCounter,
    build_output_sink,
    make_domain_prompt,
    make_permission_prompt,
    make_plan_prompt,
)
from agent_harness.api.events import APPROVAL_NEEDED
from agent_harness.api.registry import RunRegistry
from agent_harness.permissions import PermissionDecision
from agent_harness.types import ToolCall, ToolResult


class TestMakePermissionPrompt:
    def test_approval_needed_event_pushed_and_decision_translated(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_permission_prompt(registry, "run-1", seq, timeout=2.0)
        results: list[PermissionDecision] = []

        def worker() -> None:
            results.append(prompt(ToolCall(id="tc", name="run_command", arguments={"cmd": "ls"})))

        t = threading.Thread(target=worker)
        t.start()

        event = registry.pop_event("run-1", timeout=2.0)
        assert event is not None
        assert event.event == APPROVAL_NEEDED
        assert event.data["kind"] == "tool"
        assert event.data["tool_name"] == "run_command"
        assert event.data["arguments"] == {"cmd": "ls"}
        approval_id = event.data["approval_id"]

        registry.resolve_signal("run-1", approval_id, {"decision": "allow_once"})
        t.join(timeout=2.0)

        assert results == [PermissionDecision.allow_once()]

    def test_denied_decision_translated(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_permission_prompt(registry, "run-1", seq, timeout=2.0)
        results: list[PermissionDecision] = []

        def worker() -> None:
            results.append(prompt(ToolCall(id="tc", name="run_command", arguments={})))

        t = threading.Thread(target=worker)
        t.start()
        event = registry.pop_event("run-1", timeout=2.0)
        assert event is not None
        registry.resolve_signal("run-1", event.data["approval_id"], {"decision": "deny"})
        t.join(timeout=2.0)

        assert results == [PermissionDecision.deny()]

    def test_timeout_defaults_to_deny(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_permission_prompt(registry, "run-1", seq, timeout=0.05)
        decision = prompt(ToolCall(id="tc", name="run_command", arguments={}))
        assert decision == PermissionDecision.deny()


class TestMakeDomainPrompt:
    def test_allow_decision_translated(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_domain_prompt(registry, "run-1", seq, timeout=2.0)
        results: list[bool] = []

        def worker() -> None:
            results.append(prompt("example.com"))

        t = threading.Thread(target=worker)
        t.start()
        event = registry.pop_event("run-1", timeout=2.0)
        assert event is not None
        assert event.data["kind"] == "domain"
        assert event.data["domain"] == "example.com"
        registry.resolve_signal("run-1", event.data["approval_id"], {"decision": "allow"})
        t.join(timeout=2.0)

        assert results == [True]

    def test_timeout_defaults_to_false(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_domain_prompt(registry, "run-1", seq, timeout=0.05)
        assert prompt("example.com") is False


class TestMakePlanPrompt:
    def test_approve_decision_translated(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_plan_prompt(registry, "run-1", seq, timeout=2.0)
        results: list[bool] = []

        def worker() -> None:
            results.append(prompt(["Step one", "Step two"]))

        t = threading.Thread(target=worker)
        t.start()
        event = registry.pop_event("run-1", timeout=2.0)
        assert event is not None
        assert event.data["kind"] == "plan"
        assert event.data["plan_steps"] == ["Step one", "Step two"]
        registry.resolve_signal("run-1", event.data["approval_id"], {"decision": "approve"})
        t.join(timeout=2.0)

        assert results == [True]

    def test_timeout_defaults_to_false(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seq = SeqCounter()
        prompt = make_plan_prompt(registry, "run-1", seq, timeout=0.05)
        assert prompt(["Do it"]) is False


class TestBuildOutputSink:
    def test_on_delta_pushes_event(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        sink = build_output_sink(registry, "run-1", SeqCounter(), CompletionStatus())
        assert sink.on_delta is not None
        sink.on_delta("default", "hi")
        event = registry.pop_event("run-1", timeout=1.0)
        assert event is not None
        assert event.event == "delta"
        assert event.data == {"agent": "default", "text": "hi"}
        assert event.seq == 1

    def test_seq_increments_across_calls(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        sink = build_output_sink(registry, "run-1", SeqCounter(), CompletionStatus())
        assert sink.on_delta is not None
        assert sink.on_thinking_delta is not None
        sink.on_delta("default", "a")
        sink.on_thinking_delta("default", "b")
        first = registry.pop_event("run-1", timeout=1.0)
        second = registry.pop_event("run-1", timeout=1.0)
        assert first is not None and second is not None
        assert first.seq == 1
        assert second.seq == 2

    def test_on_tool_call_pushes_event(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        sink = build_output_sink(registry, "run-1", SeqCounter(), CompletionStatus())
        assert sink.on_tool_call is not None
        sink.on_tool_call(ToolCall(id="tc", name="read_file", arguments={"path": "a"}))
        event = registry.pop_event("run-1", timeout=1.0)
        assert event is not None
        assert event.event == "tool_call"
        assert event.data == {"id": "tc", "name": "read_file", "arguments": {"path": "a"}}

    def test_on_tool_result_pushes_event_with_has_attachment_flag(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        sink = build_output_sink(registry, "run-1", SeqCounter(), CompletionStatus())
        assert sink.on_tool_result is not None
        sink.on_tool_result(ToolResult(tool_call_id="tc", output="ok"))
        event = registry.pop_event("run-1", timeout=1.0)
        assert event is not None
        assert event.event == "tool_result"
        assert event.data == {"tool_call_id": "tc", "output": "ok", "error": None, "has_attachment": False}

    def test_on_budget_pushes_event(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        sink = build_output_sink(registry, "run-1", SeqCounter(), CompletionStatus())
        assert sink.on_budget is not None
        sink.on_budget("Turn 1/10 | $0.00/$0.30")
        event = registry.pop_event("run-1", timeout=1.0)
        assert event is not None
        assert event.event == "budget"
        assert event.data == {"summary": "Turn 1/10 | $0.00/$0.30"}

    def test_on_thrash_detected_pushes_event(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        sink = build_output_sink(registry, "run-1", SeqCounter(), CompletionStatus())
        assert sink.on_thrash_detected is not None
        sink.on_thrash_detected("search", "thrashing")
        event = registry.pop_event("run-1", timeout=1.0)
        assert event is not None
        assert event.event == "thrash_warning"
        assert event.data == {"tool": "search", "detail": "thrashing"}

    def test_on_completion_status_captures_into_holder_not_a_pushed_event(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        status = CompletionStatus()
        sink = build_output_sink(registry, "run-1", SeqCounter(), status)
        assert sink.on_completion_status is not None
        sink.on_completion_status(True, "PASS: good")
        assert status.verified is True
        assert status.detail == "PASS: good"
        assert registry.pop_event("run-1", timeout=0.05) is None
