"""Tests for agent_harness.cli."""

from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from agent_harness.cli import (
    _apply_overrides,
    _domain_prompt,
    _permission_prompt,
    _plan_prompt,
    parse_args,
    run_agent,
    validate_config,
)
from agent_harness.types import AgentConfig, ToolCall


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
        args = parse_args(["run", "./agents/hello", "--model", "gpt-5-mini"])
        assert args.model == "gpt-5-mini"

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

    def test_stream_flag(self) -> None:
        args = parse_args(["run", "./agents/hello", "--stream"])
        assert args.stream is True

    def test_no_stream_flag(self) -> None:
        args = parse_args(["run", "./agents/hello", "--no-stream"])
        assert args.stream is False

    def test_stream_flag_default_none(self) -> None:
        args = parse_args(["run", "./agents/hello"])
        assert args.stream is None

    def test_show_thinking_flag(self) -> None:
        args = parse_args(["run", "./agents/hello", "--show-thinking"])
        assert args.show_thinking is True

    def test_no_show_thinking_flag(self) -> None:
        args = parse_args(["run", "./agents/hello", "--no-show-thinking"])
        assert args.show_thinking is False


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

    def test_stream_override(self) -> None:
        config = self._base_config()
        _apply_overrides(config, {"stream": True})
        assert config.stream is True

    def test_show_thinking_override(self) -> None:
        config = self._base_config()
        _apply_overrides(config, {"show_thinking": True})
        assert config.show_thinking is True

    def test_no_stream_override_leaves_default(self) -> None:
        config = self._base_config()
        _apply_overrides(config, {"stream": None})
        assert config.stream is False

    def test_no_overrides_default_none(self) -> None:
        args = parse_args(["run", "./agents/hello"])
        assert args.model is None
        assert args.provider is None
        assert args.max_turns is None

    def test_multiple_overrides(self) -> None:
        args = parse_args(
            [
                "run",
                "./agents/hello",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
                "--max-turns",
                "3",
            ]
        )
        assert args.provider == "openai"
        assert args.model == "gpt-5-mini"
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

    def test_stream_on_anthropic_passes(self) -> None:
        validate_config(_valid_config(provider="anthropic", stream=True))

    def test_stream_on_openai_passes(self) -> None:
        validate_config(_valid_config(provider="openai", stream=True))

    def test_stream_on_openai_with_base_url_passes(self) -> None:
        validate_config(
            _valid_config(
                provider="openai",
                stream=True,
                provider_kwargs={"base_url": "http://localhost:1234/v1"},
            )
        )

    def test_completion_check_on_unsupported_loop_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            validate_config(_valid_config(loop="react", completion_check="pytest -q"))
        assert any("completion_check" in r.message for r in caplog.records)

    def test_completion_check_on_supported_loop_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            validate_config(_valid_config(loop="ralph", completion_check="pytest -q"))
        assert not any("completion_check" in r.message for r in caplog.records)

    def test_thinking_on_non_anthropic_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="thinking"):
            validate_config(
                _valid_config(
                    provider="openai",
                    provider_kwargs={"thinking": {"budget_tokens": 2000}},
                )
            )


class TestPermissionPromptMarkup:
    """Args/domains are arbitrary content — must not be parsed as Rich markup."""

    @patch("agent_harness.cli._console")
    def test_permission_prompt_hint_disables_markup(
        self, mock_console: MagicMock
    ) -> None:
        mock_console.input.return_value = "o"
        _permission_prompt(
            ToolCall(id="1", name="read_file", arguments={"path": "a.txt"})
        )
        _, kwargs = mock_console.input.call_args
        assert kwargs.get("markup") is False

    @patch("agent_harness.cli._console")
    def test_permission_prompt_args_immune_to_markup(
        self, mock_console: MagicMock
    ) -> None:
        mock_console.input.return_value = "o"
        _permission_prompt(
            ToolCall(id="1", name="read_file", arguments={"path": "list[str]"})
        )
        printed = [call.args[0] for call in mock_console.print.call_args_list]
        assert any(
            isinstance(obj, Text) and "list[str]" in obj.plain for obj in printed
        )

    @patch("agent_harness.cli._console")
    def test_domain_prompt_disables_markup(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "y"
        _domain_prompt("[malicious].example.com")
        _, kwargs = mock_console.input.call_args
        assert kwargs.get("markup") is False

    @patch("agent_harness.cli._console")
    def test_domain_prompt_announcement_immune_to_markup(
        self, mock_console: MagicMock
    ) -> None:
        mock_console.input.return_value = "y"
        _domain_prompt("[malicious].example.com")
        printed = [call.args[0] for call in mock_console.print.call_args_list]
        assert any(
            isinstance(obj, Text) and "[malicious].example.com" in obj.plain
            for obj in printed
        )


class TestPlanPromptMarkup:
    """Step text is arbitrary content — must not be parsed as Rich markup."""

    @patch("agent_harness.cli._console")
    def test_disables_markup_on_input(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "y"
        _plan_prompt(["Read the file", "Summarise it"])
        _, kwargs = mock_console.input.call_args
        assert kwargs.get("markup") is False

    @patch("agent_harness.cli._console")
    def test_step_text_immune_to_markup(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "y"
        _plan_prompt(["Run list[str] through the parser"])
        printed = [call.args[0] for call in mock_console.print.call_args_list]
        assert any(
            isinstance(obj, Text) and "list[str]" in obj.plain for obj in printed
        )

    @patch("agent_harness.cli._console")
    def test_approves_on_y(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "y"
        assert _plan_prompt(["Do it"]) is True

    @patch("agent_harness.cli._console")
    def test_rejects_on_n(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "n"
        assert _plan_prompt(["Do it"]) is False

    @patch("agent_harness.cli._console")
    def test_rejects_on_anything_else(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = ""
        assert _plan_prompt(["Do it"]) is False


def _bright_spans(prompt: Text, style: str = "bold cyan") -> list[str]:
    """Extract the substrings styled `style` from a prompt Text, in order."""
    return [prompt.plain[span.start : span.end] for span in prompt.spans if span.style == style]


class TestPromptChoiceHighlighting:
    """The keystroke a prompt expects should stand out from the rest of the hint."""

    @patch("agent_harness.cli._console")
    def test_permission_prompt_highlights_each_letter(
        self, mock_console: MagicMock
    ) -> None:
        mock_console.input.return_value = "o"
        _permission_prompt(
            ToolCall(id="1", name="read_file", arguments={"path": "a.txt"})
        )
        prompt_arg = mock_console.input.call_args.args[0]
        assert isinstance(prompt_arg, Text)
        assert prompt_arg.plain == "[o]nce / allow for [s]ession / allow [p]ersistently / [d]eny? "
        assert _bright_spans(prompt_arg) == ["o", "s", "p", "d"]

    @patch("agent_harness.cli._console")
    def test_domain_prompt_highlights_choice(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "y"
        _domain_prompt("example.com")
        prompt_arg = mock_console.input.call_args.args[0]
        assert isinstance(prompt_arg, Text)
        assert prompt_arg.plain == "[y/n] "
        assert _bright_spans(prompt_arg) == ["y/n"]

    @patch("agent_harness.cli._console")
    def test_plan_prompt_highlights_choice(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "y"
        _plan_prompt(["Do it"])
        prompt_arg = mock_console.input.call_args.args[0]
        assert isinstance(prompt_arg, Text)
        assert prompt_arg.plain == "Approve this plan? [y/n] "
        assert _bright_spans(prompt_arg) == ["y/n"]


class TestRunAgent:
    @patch("agent_harness.cli.prepare_runtime")
    @patch("agent_harness.cli.config_loader")
    def test_single_command_mode(
        self,
        mock_config: MagicMock,
        mock_prepare_runtime: MagicMock,
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
        runtime = MagicMock()
        runtime.init_messages.return_value = []
        mock_config.load.return_value = cfg
        mock_prepare_runtime.return_value = runtime

        run_agent("./agents/hello", prompt="list files")

        mock_config.load.assert_called_once_with("./agents/hello")
        runtime.run_messages.assert_called_once()
        runtime.finalize.assert_called_once()

    @patch("agent_harness.cli.config_loader")
    def test_invalid_agent_dir(self, mock_config: MagicMock) -> None:
        mock_config.load.side_effect = FileNotFoundError("not found")
        with pytest.raises(SystemExit):
            run_agent("/bad/path", prompt="test")

    @patch("agent_harness.cli.prompt_user")
    @patch("agent_harness.cli.prepare_runtime")
    @patch("agent_harness.cli.config_loader")
    def test_repl_mode_exit(
        self,
        mock_config: MagicMock,
        mock_prepare_runtime: MagicMock,
        mock_prompt: MagicMock,
    ) -> None:
        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        runtime = MagicMock()
        runtime.init_messages.return_value = []
        mock_config.load.return_value = cfg
        mock_prepare_runtime.return_value = runtime
        mock_prompt.return_value = "exit"

        run_agent("./agents/hello")

        runtime.run_messages.assert_not_called()
        runtime.finalize.assert_called_once()

    @patch("agent_harness.cli.prompt_user")
    @patch("agent_harness.cli.prepare_runtime")
    @patch("agent_harness.cli.config_loader")
    def test_repl_mode_skips_empty_input(
        self,
        mock_config: MagicMock,
        mock_prepare_runtime: MagicMock,
        mock_prompt: MagicMock,
    ) -> None:
        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        runtime = MagicMock()
        runtime.init_messages.return_value = []
        mock_config.load.return_value = cfg
        mock_prepare_runtime.return_value = runtime
        mock_prompt.side_effect = ["", "   ", "exit"]

        run_agent("./agents/hello")

        runtime.run_messages.assert_not_called()
        runtime.finalize.assert_called_once()

    @patch("agent_harness.cli.prepare_runtime")
    @patch("agent_harness.cli.config_loader")
    def test_single_command_runtime_error_exits_cleanly(
        self,
        mock_config: MagicMock,
        mock_prepare_runtime: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        runtime = MagicMock()
        runtime.init_messages.return_value = []
        runtime.run_messages.side_effect = RuntimeError("OpenAI rejected the request: bad content")
        mock_config.load.return_value = cfg
        mock_prepare_runtime.return_value = runtime

        with pytest.raises(SystemExit) as exc_info:
            run_agent("./agents/hello", prompt="view this")

        assert exc_info.value.code == 1
        assert "Error: OpenAI rejected the request" in capsys.readouterr().err
        runtime.finalize.assert_called_once()

    @patch("agent_harness.cli.prompt_user")
    @patch("agent_harness.cli.prepare_runtime")
    @patch("agent_harness.cli.config_loader")
    def test_repl_mode_runtime_error_continues_loop(
        self,
        mock_config: MagicMock,
        mock_prepare_runtime: MagicMock,
        mock_prompt: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        runtime = MagicMock()
        runtime.init_messages.return_value = []
        runtime.run_messages.side_effect = [RuntimeError("bad content"), None]
        mock_config.load.return_value = cfg
        mock_prepare_runtime.return_value = runtime
        mock_prompt.side_effect = ["view this", "exit"]

        run_agent("./agents/hello")

        assert runtime.run_messages.call_count == 1
        assert "Error: bad content" in capsys.readouterr().err
        runtime.finalize.assert_called_once()

    @patch("agent_harness.cli.prompt_user")
    @patch("agent_harness.cli.prepare_runtime")
    @patch("agent_harness.cli.config_loader")
    def test_repl_mode_keyboard_interrupt(
        self,
        mock_config: MagicMock,
        mock_prepare_runtime: MagicMock,
        mock_prompt: MagicMock,
    ) -> None:
        cfg = AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir="/tmp/test",
            instructions="Be helpful",
            max_turns=5,
        )
        runtime = MagicMock()
        runtime.init_messages.return_value = []
        mock_config.load.return_value = cfg
        mock_prepare_runtime.return_value = runtime
        mock_prompt.side_effect = KeyboardInterrupt

        run_agent("./agents/hello")

        runtime.finalize.assert_called_once()
