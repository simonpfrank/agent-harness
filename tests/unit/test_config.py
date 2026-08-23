"""Tests for agent_harness.config."""

from pathlib import Path

import pytest

from agent_harness.config import list_agent_names, load

VALID = "tests/data/valid_agent"
NO_INSTRUCTIONS = "tests/data/invalid_agent_no_instructions"
STREAMING = "tests/data/streaming_agent"
WITH_MCP_SERVERS = "tests/data/agent_with_mcp_servers"
WITH_COMPLETION_CHECK = "tests/data/agent_with_completion_check"


class TestLoadValid:
    def test_loads_name(self) -> None:
        cfg = load(VALID)
        assert cfg.name == "test-agent"

    def test_loads_provider_and_model(self) -> None:
        cfg = load(VALID)
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-haiku-4-5-20251001"

    def test_loads_instructions(self) -> None:
        cfg = load(VALID)
        assert "test agent" in cfg.instructions.lower()

    def test_loads_tools_guidance(self) -> None:
        cfg = load(VALID)
        assert cfg.tools_guidance is not None
        assert "run_command" in cfg.tools_guidance

    def test_loads_tools_list(self) -> None:
        cfg = load(VALID)
        assert cfg.tools == ["run_command", "read_file"]

    def test_loads_budget(self) -> None:
        cfg = load(VALID)
        assert cfg.max_turns == 5
        assert cfg.max_cost == 0.05

    def test_agent_dir_set(self) -> None:
        cfg = load(VALID)
        assert cfg.agent_dir == VALID

    def test_stream_and_show_thinking_default_false(self) -> None:
        cfg = load(VALID)
        assert cfg.stream is False
        assert cfg.show_thinking is False

    def test_loads_stream_and_show_thinking(self) -> None:
        cfg = load(STREAMING)
        assert cfg.stream is True
        assert cfg.show_thinking is True
        assert cfg.provider_kwargs["thinking"] == {"budget_tokens": 2000}

    def test_mcp_servers_defaults_empty(self) -> None:
        cfg = load(VALID)
        assert cfg.mcp_servers == []

    def test_loads_mcp_servers(self) -> None:
        cfg = load(WITH_MCP_SERVERS)
        assert cfg.mcp_servers == [
            {
                "name": "filesystem",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "env": {"SOME_VAR": "1"},
            },
        ]


    def test_completion_check_defaults_to_none(self) -> None:
        cfg = load(VALID)
        assert cfg.completion_check is None

    def test_loads_completion_check(self) -> None:
        cfg = load(WITH_COMPLETION_CHECK)
        assert cfg.completion_check == "pytest -q"

    def test_thrash_threshold_defaults_to_3(self) -> None:
        cfg = load(VALID)
        assert cfg.thrash_threshold == 3

    def test_parallel_tool_calls_defaults_to_true(self) -> None:
        cfg = load(VALID)
        assert cfg.parallel_tool_calls is True

    def test_loads_parallel_tool_calls_disabled(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "config.yaml").write_text("name: test\nparallel_tool_calls: false\n")
        (agent_dir / "instructions.md").write_text("test agent")
        cfg = load(str(agent_dir))
        assert cfg.parallel_tool_calls is False


class TestLoadInvalid:
    def test_missing_instructions(self) -> None:
        with pytest.raises(FileNotFoundError):
            load(NO_INSTRUCTIONS)

    def test_nonexistent_dir(self) -> None:
        with pytest.raises(FileNotFoundError):
            load("/no/such/agent")


class TestListAgentNames:
    def test_lists_sorted_agent_names(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        for name in ("zeta", "alpha", "mid"):
            (agents_dir / name).mkdir(parents=True)
            (agents_dir / name / "config.yaml").write_text("name: " + name)
        assert list_agent_names(str(agents_dir)) == ["alpha", "mid", "zeta"]

    def test_ignores_dirs_without_config_yaml(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        (agents_dir / "real").mkdir(parents=True)
        (agents_dir / "real" / "config.yaml").write_text("name: real")
        (agents_dir / "not-an-agent").mkdir(parents=True)
        assert list_agent_names(str(agents_dir)) == ["real"]

    def test_empty_when_dir_does_not_exist(self, tmp_path: Path) -> None:
        assert list_agent_names(str(tmp_path / "never-created")) == []
