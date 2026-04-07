"""Tests for run_agent tool (agent-as-tool routing)."""

from unittest.mock import MagicMock, patch

from agent_harness.routing import handoff_agent, run_agent


class TestRunAgent:
    @patch("agent_harness.routing._with_depth_check")
    def test_returns_sub_agent_response(self, mock_depth: MagicMock) -> None:
        mock_depth.return_value = "Sub-agent says hello"
        result = run_agent("hello", "say hi")
        assert result == "Sub-agent says hello"

    @patch("agent_harness.routing._with_depth_check")
    def test_missing_agent_returns_error(self, mock_depth: MagicMock) -> None:
        mock_depth.side_effect = FileNotFoundError("Agent not found: nonexistent")
        try:
            run_agent("nonexistent", "hello")
            raise AssertionError("Should have raised")
        except FileNotFoundError as exc:
            assert "nonexistent" in str(exc)

    def test_registered_in_registry(self) -> None:
        from agent_harness.tools import registry
        assert "run_agent" in registry


class TestCascadingDepthLimit:
    def test_depth_limit_exceeded(self) -> None:
        from agent_harness import routing as routing_module
        old_depth = routing_module._call_depth
        routing_module._call_depth = 3
        try:
            run_agent("hello", "hi")
            raise AssertionError("Should have raised")
        except RuntimeError as exc:
            assert "depth" in str(exc).lower()
        finally:
            routing_module._call_depth = old_depth

    def test_depth_resets_after_call(self) -> None:
        from agent_harness import routing as routing_module
        assert routing_module._call_depth == 0


class TestHandoffAgent:
    @patch("agent_harness.routing._load_and_run")
    def test_passes_messages_through(self, mock_run: MagicMock) -> None:
        mock_run.return_value = "continued conversation"
        from agent_harness.types import Message
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
        ]
        result = handoff_agent("specialist", msgs)
        assert result == "continued conversation"
        mock_run.assert_called_once_with("specialist", msgs)

    def test_not_in_tool_registry(self) -> None:
        """handoff_agent takes list[Message] — not serialisable as LLM tool."""
        from agent_harness.tools import registry
        assert "handoff_agent" not in registry
