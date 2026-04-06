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


def _config(max_turns: int = 10) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test",
        instructions="test",
        max_turns=max_turns,
    )


def _response(content: str, stop_reason: str = "end_turn") -> Response:
    msg = Message(role="assistant", content=content)
    return Response(message=msg, usage=Usage(10, 5), stop_reason=stop_reason)


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
        """Planning call should have no tools."""
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
            if call_count <= 3:
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
            _response("step 1 done"),
            _response("step 2 done"),
            _response("summary"),
        ]
        chat_fn = MagicMock(side_effect=responses)
        messages = [Message(role="user", content="task")]
        run(chat_fn, messages, [], _config())
        # 1 plan + 2 steps + 1 summary = 4 calls
        assert chat_fn.call_count == 4

    def test_callbacks_passed_to_steps(self) -> None:
        """on_response should fire for each step."""
        plan_response = _response("1. Do it")
        step_response = _response("done")
        summary_response = _response("all done")
        chat_fn = MagicMock(side_effect=[plan_response, step_response, summary_response])
        on_response = MagicMock()
        cb = LoopCallbacks(on_response=on_response)
        messages = [Message(role="user", content="go")]
        run(chat_fn, messages, [], _config(), callbacks=cb)
        assert on_response.call_count >= 2  # at least step + summary

    def test_registered_in_loop_registry(self) -> None:
        from agent_harness.loops import registry
        assert "plan_execute" in registry
