"""Integration tests for custom tools and skills loading."""

from agent_harness.config import load
from agent_harness.skills import load_skills
from agent_harness.tools import discover_tools, execute_tool, registry
from agent_harness.types import ToolCall


class TestCustomToolIntegration:
    def test_word_count_tool_discovered(self) -> None:
        """tools/word_count.py should be discoverable."""
        discover_tools("tools")
        assert "word_count" in registry
        tc = ToolCall(id="tc_1", name="word_count", arguments={"text": "hello world foo"})
        result = execute_tool(tc)
        assert result.output == "3"

    def test_file_search_tool_discovered(self) -> None:
        """tools/file_search.py should be discoverable."""
        discover_tools("tools")
        assert "file_search" in registry
        tc = ToolCall(id="tc_1", name="file_search", arguments={"pattern": "*.yaml", "directory": "agents/hello"})
        result = execute_tool(tc)
        assert "config.yaml" in (result.output or "")


class TestSkillsIntegration:
    def test_shared_skills_loaded(self) -> None:
        """skills/ directory should have loadable SKILL.md files."""
        content = load_skills("skills")
        assert "CSV Analysis" in content
        assert "Code Review" in content

    def test_agent_config_loads_with_skills(self) -> None:
        """Agent with skills/ dir should load normally."""
        cfg = load("agents/analyst")
        assert cfg.name == "analyst"
        assert cfg.loop == "reflection"


class TestDefaultAgentsUnchanged:
    def test_hello_agent_unaffected(self) -> None:
        """Agent without custom tools/skills works identically."""
        cfg = load("agents/hello")
        assert cfg.name == "hello"
        # Skills from project-level skills/ still load, but agent works fine
        content = load_skills("skills", f"{cfg.agent_dir}/skills")
        # Should include shared skills even for hello agent
        assert "CSV Analysis" in content
