"""Tests for agent_harness.loops.plan_execute."""

from unittest.mock import MagicMock

from agent_harness.loops.plan_execute import _parse_plan, run
from agent_harness.types import (
    AgentConfig,
    LoopCallbacks,
    Message,
    Response,
    Usage,
)


def _config(max_turns: int = 10, stream: bool = False) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test",
        instructions="test",
        max_turns=max_turns,
        stream=stream,
    )


def _response(content: str, stop_reason: str = "end_turn") -> Response:
    msg = Message(role="assistant", content=content)
    return Response(message=msg, usage=Usage(10, 5), stop_reason=stop_reason)


_DONE = _response("DONE")


class TestParsePlan:
    def test_extracts_numbered_steps(self) -> None:
        text = "Here's my plan:\n1. Read the file\n2. Parse the data\n3. Write output"
        steps = _parse_plan(text)
        assert len(steps) == 3
        assert "Read the file" in steps[0]
        assert "Parse the data" in steps[1]
        assert "Write output" in steps[2]

    def test_handles_no_steps(self) -> None:
        steps = _parse_plan("I'll just do it directly.")
        assert len(steps) == 0

    def test_handles_mixed_content(self) -> None:
        text = "Plan:\n1. First step\nSome explanation\n2. Second step"
        steps = _parse_plan(text)
        assert len(steps) == 2


class TestPlanExecuteLoop:
    def test_planning_phase_no_tools(self) -> None:
        """Planning call (and the critique call after it) should have no tools."""
        plan_response = _response("1. Read file\n2. Summarise")
        step_response = _response("Done with step")
        summary_response = _response("All done")

        call_count = 0

        def mock_chat(messages: list[Message], tools: list[object], **kw: object) -> Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Planning call — verify no tools
                assert tools == []
                return plan_response
            if call_count == 2:
                # Critique call — also no tools
                assert tools == []
                return _DONE
            if call_count <= 4:
                return step_response
            return summary_response

        messages = [Message(role="user", content="do something")]
        result = run(mock_chat, messages, [{"name": "t"}], _config())
        assert "All done" in result

    def test_executes_each_step(self) -> None:
        """Each plan step should trigger a react sub-loop."""
        plan_response = _response("1. Step one\n2. Step two")
        responses = [
            plan_response,
            _DONE,
            _response("step 1 done"),
            _response("step 2 done"),
            _response("summary"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="task")]
        run(chat_fn, messages, [], _config())
        # 1 plan + 1 critique + 2 steps + 1 summary = 5 calls
        assert chat_fn.call_count == 5

    def test_callbacks_passed_to_steps(self) -> None:
        """on_response should fire for the critique call plus each step."""
        plan_response = _response("1. Do it")
        step_response = _response("done")
        summary_response = _response("all done")
        chat_fn = MagicMock(side_effect=[plan_response, _DONE, step_response, summary_response])
        on_response = MagicMock()
        cb = LoopCallbacks(on_response=on_response)
        messages = [Message(role="user", content="go")]
        run(chat_fn, messages, [], _config(), callbacks=cb)
        assert on_response.call_count >= 3  # at least critique + step + summary

    def test_registered_in_loop_registry(self) -> None:
        from agent_harness.loops import registry
        assert "plan_execute" in registry

    def test_forwards_stream_flag(self) -> None:
        plan_response = _response("1. Do it")
        step_response = _response("done")
        summary_response = _response("all done")
        chat_fn = MagicMock(side_effect=[plan_response, _DONE, step_response, summary_response])
        messages = [Message(role="user", content="go")]
        run(chat_fn, messages, [], _config(stream=True))
        for call in chat_fn.call_args_list:
            assert call.kwargs["stream"] is True


class TestPlanCritique:
    def test_done_critique_leaves_plan_unchanged(self) -> None:
        plan_response = _response("1. Step A\n2. Step B")
        chat_fn = MagicMock(
            side_effect=[
                plan_response,
                _DONE,
                _response("step A done"),
                _response("step B done"),
                _response("summary"),
            ],
        )
        messages = [Message(role="user", content="task")]
        run(chat_fn, messages, [], _config())
        # Only one critique call (DONE on round 1) + both original steps executed.
        assert chat_fn.call_count == 5
        step_messages = [m.content or "" for m in messages if m.role == "user" and "Execute step" in (m.content or "")]
        assert any("Step A" in m for m in step_messages)
        assert any("Step B" in m for m in step_messages)

    def test_revised_plan_changes_execution(self) -> None:
        plan_response = _response("1. Step A\n2. Step B")
        revised = _response("1. Only step")
        chat_fn = MagicMock(
            side_effect=[
                plan_response,
                revised,  # round 1: non-DONE, revises the plan to 1 step
                _DONE,  # round 2: critiques the revision, approves it
                _response("only step done"),
                _response("summary"),
            ],
        )
        messages = [Message(role="user", content="task")]
        run(chat_fn, messages, [], _config())
        assert chat_fn.call_count == 5
        step_messages = [m.content or "" for m in messages if m.role == "user" and "Execute step" in (m.content or "")]
        assert len(step_messages) == 1
        assert "Only step" in step_messages[0]

    def test_unparseable_critique_falls_back_to_current_plan(self) -> None:
        plan_response = _response("1. Do it")
        garbage_critique = _response("I have thoughts but no numbered list here.")
        chat_fn = MagicMock(
            side_effect=[
                plan_response,
                garbage_critique,
                _response("done"),
                _response("summary"),
            ],
        )
        messages = [Message(role="user", content="task")]
        run(chat_fn, messages, [], _config())
        # Falls back after round 1 — no second critique call, original single step still runs.
        assert chat_fn.call_count == 4

    def test_max_critique_rounds_reached_still_proceeds(self) -> None:
        plan_response = _response("1. Do it")
        revised_1 = _response("1. Revision one")
        revised_2 = _response("1. Revision two")
        chat_fn = MagicMock(
            side_effect=[
                plan_response,
                revised_1,
                revised_2,
                _response("done"),
                _response("summary"),
            ],
        )
        messages = [Message(role="user", content="task")]
        run(chat_fn, messages, [], _config())
        # Exactly 2 critique rounds (the cap), no third critique call.
        assert chat_fn.call_count == 5
        step_messages = [m.content or "" for m in messages if m.role == "user" and "Execute step" in (m.content or "")]
        assert "Revision two" in step_messages[0]


class TestPlanApprovalGate:
    def test_no_approval_callback_proceeds_normally(self) -> None:
        plan_response = _response("1. Do it")
        chat_fn = MagicMock(side_effect=[plan_response, _DONE, _response("done"), _response("summary")])
        messages = [Message(role="user", content="task")]
        result = run(chat_fn, messages, [], _config())
        assert "summary" in result
        assert chat_fn.call_count == 4

    def test_approval_true_proceeds(self) -> None:
        plan_response = _response("1. Do it")
        chat_fn = MagicMock(side_effect=[plan_response, _DONE, _response("done"), _response("summary")])
        on_plan_approval = MagicMock(return_value=True)
        cb = LoopCallbacks(on_plan_approval=on_plan_approval)
        messages = [Message(role="user", content="task")]
        result = run(chat_fn, messages, [], _config(), callbacks=cb)
        assert "summary" in result
        on_plan_approval.assert_called_once_with(["Do it"])

    def test_approval_false_skips_execution(self) -> None:
        plan_response = _response("1. Do it")
        chat_fn = MagicMock(side_effect=[plan_response, _DONE])
        on_plan_approval = MagicMock(return_value=False)
        cb = LoopCallbacks(on_plan_approval=on_plan_approval)
        messages = [Message(role="user", content="task")]
        result = run(chat_fn, messages, [], _config(), callbacks=cb)
        assert "not approved" in result.lower()
        # Only plan + critique calls happen — no step execution, no summary.
        assert chat_fn.call_count == 2
        on_plan_approval.assert_called_once_with(["Do it"])
