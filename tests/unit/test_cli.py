"""Tests for agent_harness.cli."""

from unittest.mock import MagicMock, patch

import pytest

from agent_harness.cli import _apply_overrides, parse_args, run_agent, validate_config
from agent_harness.types import AgentConfig


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

    def test_model_override(self) -> None:
        args = parse_args(["run", "./agents/hello", "--model", "gpt-4o-mini"])
        assert args.model == "gpt-4o-mini"

    def test_provider_override(self) -> None:
        args = parse_args(["run", "./agents/hello", "--provider", "openai"])
        assert args.provider == "openai"

    def test_max_turns_override(self) -> None:
        args = parse_args(["run", "./agents/hello", "--max-turns", "3"])
        assert args.max_turns == 3

    def test_max_cost_override(self) -> None:
        args = parse_args(["run", "./agents/hello", "--max-cost", "0.02"])
        assert args.max_cost == 0.02

    def test_temperature_override(self) -> None:
        args = parse_args(["run", "./agents/hello", "--temperature", "0.0"])
        assert args.temperature == 0.0


class TestApplyOverrides:
    def _base_config(self) -> AgentConfig:
        return AgentConfig(
            name="t",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="./agents/t",
            instructions="hi",
            provider_kwargs={"max_tokens": 8192},
        )

    def test_temperature_merges_into_provider_kwargs(self) -> None:
        config = self._base_config()
        _apply_overrides(config, {"temperature": 0.0})
        assert config.provider_kwargs == {"max_tokens": 8192, "temperature": 0.0}

    def test_no_temperature_leaves_kwargs_untouched(self) -> None:
        config = self._base_config()
        _apply_overrides(config, {"temperature": None})
        assert config.provider_kwargs == {"max_tokens": 8192}

    def test_model_override_still_works(self) -> None:
        config = self._base_config()
        _apply_overrides(config, {"model": "gpt-4o"})
        assert config.model == "gpt-4o"

    def test_loop_override(self) -> None:
        args = parse_args(["run", "./agents/hello", "--loop", "reflection"])
        assert args.loop == "reflection"

    def test_no_overrides_default_none(self) -> None:
        args = parse_args(["run", "./agents/hello"])
        assert args.model is None
        assert args.provider is None
        assert args.max_turns is None

    def test_multiple_overrides(self) -> None:
        args = parse_args([
            "run", "./agents/hello",
            "--provider", "openai", "--model", "gpt-4o-mini", "--max-turns", "3",
        ])
        assert args.provider == "openai"
        assert args.model == "gpt-4o-mini"
        assert args.max_turns == 3

    def test_run_requires_agent_dir(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["run"])


def _valid_config(**overrides: object) -> AgentConfig:
    defaults = {
        "name": "test",
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "agent_dir": "/tmp/test",
        "instructions": "Be helpful",
        "max_turns": 5,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)  # type: ignore[arg-type]


class TestValidateConfig:
    def test_valid_config_passes(self) -> None:
        validate_config(_valid_config(tools=["run_command"]))

    def test_bad_provider(self) -> None:
        with pytest.raises(ValueError, match="provider"):
            validate_config(_valid_config(provider="fakellm"))

    def test_bad_tool(self) -> None:
        with pytest.raises(ValueError, match="tool"):
            validate_config(_valid_config(tools=["nonexistent"]))

    def test_bad_loop(self) -> None:
        with pytest.raises(ValueError, match="loop"):
            validate_config(_valid_config(loop="nonexistent"))

    def test_bad_max_turns(self) -> None:
        with pytest.raises(ValueError, match="max_turns"):
            validate_config(_valid_config(max_turns=0))


class TestRunAgent:
    @patch("agent_harness.cli.validate_config")
    @patch("agent_harness.cli.config_loader")
    @patch("agent_harness.cli.loop_registry")
    @patch("agent_harness.cli.provider_registry")
    def test_single_command_mode(
        self,
        mock_providers: MagicMock,
        mock_loops: MagicMock,
        mock_config: MagicMock,
        _mock_validate: MagicMock,
    ) -> None:
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

    @patch("agent_harness.cli.validate_config")
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
        _mock_validate: MagicMock,
    ) -> None:
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

    @patch("agent_harness.cli.validate_config")
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
        _mock_validate: MagicMock,
    ) -> None:
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
