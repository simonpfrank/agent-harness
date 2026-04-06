"""Tests for agent scaffolding (init command)."""

import tempfile
from pathlib import Path

from agent_harness.scaffold import create_agent


class TestCreateAgent:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = str(Path(tmpdir) / "test-agent")
            create_agent(agent_dir)
            assert Path(agent_dir).is_dir()

    def test_creates_config_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = str(Path(tmpdir) / "test-agent")
            create_agent(agent_dir)
            config_path = Path(agent_dir) / "config.yaml"
            assert config_path.exists()
            content = config_path.read_text()
            assert "provider:" in content
            assert "model:" in content
            assert "tools:" in content

    def test_creates_instructions_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = str(Path(tmpdir) / "test-agent")
            create_agent(agent_dir)
            instructions = Path(agent_dir) / "instructions.md"
            assert instructions.exists()
            assert len(instructions.read_text()) > 0

    def test_creates_tools_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = str(Path(tmpdir) / "test-agent")
            create_agent(agent_dir)
            tools_md = Path(agent_dir) / "tools.md"
            assert tools_md.exists()

    def test_scaffolded_agent_loads(self) -> None:
        """Scaffolded agent should pass config loading without errors."""
        from agent_harness.config import load

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = str(Path(tmpdir) / "test-agent")
            create_agent(agent_dir)
            config = load(agent_dir)
            assert config.name == "test-agent"

    def test_does_not_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = str(Path(tmpdir) / "test-agent")
            create_agent(agent_dir)
            try:
                create_agent(agent_dir)
                raise AssertionError("Should have raised")
            except FileExistsError:
                pass
