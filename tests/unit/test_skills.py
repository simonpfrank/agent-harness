"""Tests for agent_harness.skills — skill loading from directories."""

import tempfile
from pathlib import Path

from agent_harness.skills import load_skills


class TestLoadSkills:
    def test_loads_shared_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "skills" / "csv-analysis"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# CSV Analysis\nUse pandas.")
            result = load_skills(str(Path(tmpdir) / "skills"))
            assert "CSV Analysis" in result
            assert "pandas" in result

    def test_loads_agent_local_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "agent-skills" / "local-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# Local Skill\nAgent-specific.")
            result = load_skills(agent_skills_dir=str(Path(tmpdir) / "agent-skills"))
            assert "Local Skill" in result

    def test_agent_local_overrides_shared(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            shared = Path(tmpdir) / "shared" / "my-skill"
            shared.mkdir(parents=True)
            (shared / "SKILL.md").write_text("SHARED VERSION")

            local = Path(tmpdir) / "local" / "my-skill"
            local.mkdir(parents=True)
            (local / "SKILL.md").write_text("LOCAL VERSION")

            result = load_skills(
                project_skills_dir=str(Path(tmpdir) / "shared"),
                agent_skills_dir=str(Path(tmpdir) / "local"),
            )
            assert "LOCAL VERSION" in result
            assert "SHARED VERSION" not in result

    def test_multiple_skills_concatenated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["alpha", "beta"]:
                skill_dir = Path(tmpdir) / "skills" / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# Skill {name}")
            result = load_skills(str(Path(tmpdir) / "skills"))
            assert "Skill alpha" in result
            assert "Skill beta" in result

    def test_no_dirs_returns_empty(self) -> None:
        result = load_skills()
        assert result == ""

    def test_missing_dirs_returns_empty(self) -> None:
        result = load_skills("/nonexistent/shared", "/nonexistent/local")
        assert result == ""
