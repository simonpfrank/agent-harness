"""Tests for agent_harness.cli."""

from unittest.mock import MagicMock, patch

import pytest

from agent_harness.cli import parse_args, run_agent


class TestParseArgs:
    def test_run_with_agent_dir_and_prompt(self) -> None:
        args = parse_args(["run", "./agents/hello", "list files"])
        assert args.command == "run"
        assert args.agent_dir == "./agents/hello"
        assert args.prompt == "list files"

    def test_run_without_prompt(self) -> None:
        args = parse_args(["run", "./agents/hello"])
        assert args.prompt is None

    def test_verbose_flag(self) -> None:
        args = parse_args(["run", "./agents/hello", "--verbose"])
        assert args.verbose is True

    def test_run_requires_agent_dir(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["run"])


class TestRunAgent:
    @patch("agent_harness.cli.config_loader")
    @patch("agent_harness.cli.loop_registry")
    @patch("agent_harness.cli.provider_registry")
    def test_single_command_mode(
        self,
        mock_providers: MagicMock,
        mock_loops: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        from agent_harness.types import AgentConfig

        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            tools=["run_command"],
            max_turns=5,
        )
        mock_config.load.return_value = cfg
        mock_loops.__getitem__ = MagicMock(return_value=MagicMock(return_value="result"))
        mock_providers.__getitem__ = MagicMock(return_value=MagicMock())

        run_agent("./agents/hello", prompt="list files")
        mock_config.load.assert_called_once_with("./agents/hello")

    @patch("agent_harness.cli.config_loader")
    def test_invalid_agent_dir(self, mock_config: MagicMock) -> None:
        mock_config.load.side_effect = FileNotFoundError("not found")
        with pytest.raises(SystemExit):
            run_agent("/bad/path", prompt="test")

    @patch("agent_harness.cli.prompt_user")
    @patch("agent_harness.cli.config_loader")
    @patch("agent_harness.cli.loop_registry")
    @patch("agent_harness.cli.provider_registry")
    def test_repl_mode_exit(
        self,
        mock_providers: MagicMock,
        mock_loops: MagicMock,
        mock_config: MagicMock,
        mock_prompt: MagicMock,
    ) -> None:
        from agent_harness.types import AgentConfig

        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        mock_config.load.return_value = cfg
        mock_loops.__getitem__ = MagicMock(return_value=MagicMock(return_value="ok"))
        mock_providers.__getitem__ = MagicMock(return_value=MagicMock())
        mock_prompt.return_value = "exit"

        run_agent("./agents/hello")  # no prompt = REPL, "exit" stops it

    @patch("agent_harness.cli.prompt_user")
    @patch("agent_harness.cli.config_loader")
    @patch("agent_harness.cli.loop_registry")
    @patch("agent_harness.cli.provider_registry")
    def test_repl_mode_keyboard_interrupt(
        self,
        mock_providers: MagicMock,
        mock_loops: MagicMock,
        mock_config: MagicMock,
        mock_prompt: MagicMock,
    ) -> None:
        from agent_harness.types import AgentConfig

        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        mock_config.load.return_value = cfg
        mock_loops.__getitem__ = MagicMock(return_value=MagicMock(return_value="ok"))
        mock_providers.__getitem__ = MagicMock(return_value=MagicMock())
        mock_prompt.side_effect = KeyboardInterrupt

        run_agent("./agents/hello")  # should exit gracefully
