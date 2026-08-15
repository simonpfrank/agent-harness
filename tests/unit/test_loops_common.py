"""Tests for agent_harness.loops.common's shared completion_check helpers."""

from agent_harness.loops.common import check_tool_thrashing, report_completion_status, run_completion_check
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


class TestCheckToolThrashing:
    def _tc(self, name: str = "search", args: dict[str, object] | None = None) -> ToolCall:
        return ToolCall(id="tc_1", name=name, arguments=args if args is not None else {"q": "x"})

    def test_below_threshold_no_nudge(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        tc = self._tc()
        for _ in range(2):
            detail = check_tool_thrashing(tc, ToolResult(tool_call_id="tc_1", output="ok"), counts, streaks, 3)
        assert detail is None

    def test_duplicate_args_threshold_reached(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        tc = self._tc()
        detail = None
        for _ in range(3):
            detail = check_tool_thrashing(tc, ToolResult(tool_call_id="tc_1", output="ok"), counts, streaks, 3)
        assert detail is not None
        assert "search" in detail
        assert "3" in detail

    def test_consecutive_error_streak_reached(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        detail = None
        for i in range(3):
            tc = self._tc(args={"q": f"attempt-{i}"})  # different args each time
            detail = check_tool_thrashing(tc, ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3)
        assert detail is not None
        assert "3" in detail

    def test_success_resets_error_streak(self) -> None:
        # Different args per call to isolate the error-streak signal from
        # the duplicate-args signal (identical args would trip that too).
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        check_tool_thrashing(
            self._tc(args={"q": "a"}), ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3,
        )
        check_tool_thrashing(
            self._tc(args={"q": "b"}), ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3,
        )
        check_tool_thrashing(
            self._tc(args={"q": "c"}), ToolResult(tool_call_id="tc_1", output="ok"), counts, streaks, 3,
        )
        # streak reset — one more error shouldn't hit the threshold of 3 yet
        detail = check_tool_thrashing(
            self._tc(args={"q": "d"}), ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3,
        )
        assert streaks["search"] == 1
        assert detail is None

    def test_error_streak_is_per_tool_name(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        search_tc = self._tc(name="search")
        other_tc = self._tc(name="read_file")
        check_tool_thrashing(search_tc, ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3)
        check_tool_thrashing(other_tc, ToolResult(tool_call_id="tc_2", error="boom"), counts, streaks, 3)
        check_tool_thrashing(other_tc, ToolResult(tool_call_id="tc_2", error="boom"), counts, streaks, 3)
        assert streaks["search"] == 1
        assert streaks["read_file"] == 2

    def test_threshold_zero_disables_detection(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        tc = self._tc()
        detail = None
        for _ in range(10):
            detail = check_tool_thrashing(tc, ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 0)
        assert detail is None

    def test_both_conditions_true_error_streak_wins(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        tc = self._tc()
        detail = None
        for _ in range(3):
            # same args every time AND erroring every time -> both signals true
            detail = check_tool_thrashing(tc, ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3)
        assert detail is not None
        assert "failed" in detail.lower() or "error" in detail.lower()

    def test_none_result_counts_toward_duplicate_args_not_streak(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        tc = self._tc()
        detail = None
        for _ in range(3):
            detail = check_tool_thrashing(tc, None, counts, streaks, 3)
        assert detail is not None
        assert streaks.get("search", 0) == 0

    def test_dicts_mutated_in_place(self) -> None:
        counts: dict[str, int] = {}
        streaks: dict[str, int] = {}
        tc = self._tc()
        check_tool_thrashing(tc, ToolResult(tool_call_id="tc_1", error="boom"), counts, streaks, 3)
        assert streaks["search"] == 1
        assert any(k.startswith("search:") for k in counts)
