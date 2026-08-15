"""Tests for agent_harness.loops.common's shared completion_check helpers."""

from agent_harness.loops.common import report_completion_status, run_completion_check
from agent_harness.types import AgentConfig, LoopCallbacks, ToolCall, ToolResult


def _config(completion_check: str | None = None) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test",
        instructions="test",
        completion_check=completion_check,
    )


class TestRunCompletionCheckDispatch:
    def test_dispatches_named_tool_with_no_args(self) -> None:
        calls: list[ToolCall] = []

        def on_tool_call(tc: ToolCall) -> ToolResult:
            calls.append(tc)
            return ToolResult(tool_call_id=tc.id, output="PASS")

        cb = LoopCallbacks(on_tool_call=on_tool_call)
        config = _config(completion_check="verify")
        tool_schemas = [{"name": "verify", "description": "d", "input_schema": {}}]

        verified, detail = run_completion_check(cb, tool_schemas, config)

        assert verified is True
        assert detail == "PASS"
        assert len(calls) == 1
        assert calls[0].name == "verify"
        assert calls[0].arguments == {}

    def test_falls_back_to_run_command_when_not_a_known_tool(self) -> None:
        calls: list[ToolCall] = []

        def on_tool_call(tc: ToolCall) -> ToolResult:
            calls.append(tc)
            return ToolResult(tool_call_id=tc.id, output="ok\n[exit code 0]")

        cb = LoopCallbacks(on_tool_call=on_tool_call)
        config = _config(completion_check="pytest -q")
        tool_schemas: list[dict[str, object]] = [{"name": "read_file", "description": "d", "input_schema": {}}]

        verified, _ = run_completion_check(cb, tool_schemas, config)

        assert verified is True
        assert len(calls) == 1
        assert calls[0].name == "run_command"
        assert calls[0].arguments == {"command": "pytest -q"}


class TestRunCompletionCheckInterpretation:
    def _cb_returning(self, output: str | None = None, error: str | None = None) -> LoopCallbacks:
        def on_tool_call(tc: ToolCall) -> ToolResult:
            return ToolResult(tool_call_id=tc.id, output=output, error=error)

        return LoopCallbacks(on_tool_call=on_tool_call)

    def test_pass_prefix_is_verified(self) -> None:
        cb = self._cb_returning(output="PASS: all good")
        verified, detail = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is True
        assert detail == "PASS: all good"

    def test_fail_prefix_is_not_verified(self) -> None:
        cb = self._cb_returning(output="FAIL: tests red")
        verified, detail = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is False
        assert detail == "FAIL: tests red"

    def test_pass_check_is_case_insensitive(self) -> None:
        cb = self._cb_returning(output="pass")
        verified, _ = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is True

    def test_tool_error_is_not_verified(self) -> None:
        cb = self._cb_returning(error="boom")
        verified, detail = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is False
        assert detail == "boom"

    def test_run_command_exit_code_zero_is_verified(self) -> None:
        cb = self._cb_returning(output="some test output\n[exit code 0]")
        verified, _ = run_completion_check(cb, [], _config(completion_check="pytest -q"))
        assert verified is True

    def test_run_command_nonzero_exit_is_not_verified(self) -> None:
        cb = self._cb_returning(output="1 failed\n[exit code 1]")
        verified, _ = run_completion_check(cb, [], _config(completion_check="pytest -q"))
        assert verified is False

    def test_no_on_tool_call_callback_fails_closed(self) -> None:
        cb = LoopCallbacks()
        verified, detail = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is False
        assert "on_tool_call" in detail

    def test_none_result_fails_closed(self) -> None:
        cb = LoopCallbacks(on_tool_call=lambda tc: None)
        verified, detail = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is False

    def test_ambiguous_output_fails_closed(self) -> None:
        cb = self._cb_returning(output="looks fine to me")
        verified, detail = run_completion_check(cb, [], _config(completion_check="check.sh"))
        assert verified is False
        assert detail == "looks fine to me"


class TestReportCompletionStatus:
    def test_noop_when_completion_check_unset(self) -> None:
        calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: calls.append((v, d)))
        report_completion_status(cb, _config(completion_check=None), True, "PASS")
        assert calls == []

    def test_noop_when_callback_unset(self) -> None:
        cb = LoopCallbacks()
        # Should not raise
        report_completion_status(cb, _config(completion_check="x"), True, "PASS")

    def test_fires_when_both_set(self) -> None:
        calls = []
        cb = LoopCallbacks(on_completion_status=lambda v, d: calls.append((v, d)))
        report_completion_status(cb, _config(completion_check="x"), False, "FAIL: red")
        assert calls == [(False, "FAIL: red")]
