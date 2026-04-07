"""Tests for run_agent tool (agent-as-tool routing)."""

from unittest.mock import MagicMock, patch

from agent_harness.tools import run_agent


class TestRunAgent:
    @patch("agent_harness.tools._run_sub_agent")
    def test_returns_sub_agent_response(self, mock_run: MagicMock) -> None:
        mock_run.return_value = "Sub-agent says hello"
        result = run_agent("hello", "say hi")
        assert result == "Sub-agent says hello"
        mock_run.assert_called_once_with("hello", "say hi")

    @patch("agent_harness.tools._run_sub_agent")
    def test_missing_agent_returns_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("Agent not found: nonexistent")
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
        from agent_harness import tools as tools_module
        old_depth = tools_module._call_depth
        tools_module._call_depth = 3  # already at max
        try:
            run_agent("hello", "hi")
            raise AssertionError("Should have raised")
        except RuntimeError as exc:
            assert "depth" in str(exc).lower()
        finally:
            tools_module._call_depth = old_depth

    def test_depth_resets_after_call(self) -> None:
        from agent_harness import tools as tools_module
        assert tools_module._call_depth == 0
