"""Tests for agent_harness.types dataclasses."""

from agent_harness.types import (
    AgentConfig,
    Message,
    OnBudget,
    OnResponse,
    OnToolCall,
    Response,
    ToolCall,
    ToolResult,
    Usage,
)


class TestToolCall:
    def test_construction(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo.txt"})
        assert tc.id == "tc_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "foo.txt"}


class TestToolResult:
    def test_success(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="hello")
        assert tr.output == "hello"
        assert tr.error is None

    def test_error(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", error="not found")
        assert tr.output is None
        assert tr.error == "not found"


class TestMessage:
    def test_user_message(self) -> None:
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.tool_calls is None
        assert m.tool_result is None

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={})
        m = Message(role="assistant", content="thinking", tool_calls=[tc])
        assert m.tool_calls == [tc]

    def test_tool_result_message(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="data")
        m = Message(role="tool", tool_result=tr)
        assert m.tool_result == tr


class TestUsage:
    def test_construction(self) -> None:
        u = Usage(input_tokens=100, output_tokens=50)
        assert u.input_tokens == 100
        assert u.output_tokens == 50


class TestResponse:
    def test_construction(self) -> None:
        msg = Message(role="assistant", content="hi")
        usage = Usage(input_tokens=10, output_tokens=5)
        r = Response(message=msg, usage=usage, stop_reason="end_turn")
        assert r.stop_reason == "end_turn"


class TestAgentConfig:
    def test_defaults(self) -> None:
        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Do stuff",
        )
        assert cfg.tools == []
        assert cfg.loop == "react"
        assert cfg.max_turns == 10
        assert cfg.max_cost is None
        assert cfg.permissions == {}
        assert cfg.hooks == {}
        assert cfg.tools_guidance is None


class TestCallbackAliases:
    def test_types_exist(self) -> None:
        """Callback type aliases should be importable."""
        assert OnResponse is not None
        assert OnToolCall is not None
        assert OnBudget is not None
