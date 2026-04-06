"""Tests for agent_harness.config."""

import pytest

from agent_harness.config import load

VALID = "tests/data/valid_agent"
NO_INSTRUCTIONS = "tests/data/invalid_agent_no_instructions"


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


class TestLoadInvalid:
    def test_missing_instructions(self) -> None:
        with pytest.raises(FileNotFoundError):
            load(NO_INSTRUCTIONS)

    def test_nonexistent_dir(self) -> None:
        with pytest.raises(FileNotFoundError):
            load("/no/such/agent")
