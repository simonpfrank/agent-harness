"""Skill loading — scan skill directories for SKILL.md files."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_skills(
    project_skills_dir: str | None = None,
    agent_skills_dir: str | None = None,
) -> str:
    """Load skills from project and agent directories.

    Each skill is a directory containing SKILL.md. Agent-local skills
    override shared skills with the same directory name.

    Args:
        project_skills_dir: Path to project-level skills/ directory.
        agent_skills_dir: Path to agent-local skills/ directory.

    Returns:
        Concatenated SKILL.md contents, or empty string if none found.
    """
    skills: dict[str, str] = {}

    # Load shared skills first
    if project_skills_dir:
        _scan_skills_dir(Path(project_skills_dir), skills)

    # Agent-local overrides shared on name collision
    if agent_skills_dir:
        _scan_skills_dir(Path(agent_skills_dir), skills)

    if skills:
        logger.info("Loaded %d skills: %s", len(skills), ", ".join(sorted(skills.keys())))

    return "\n\n".join(skills[k] for k in sorted(skills))


def _scan_skills_dir(base: Path, skills: dict[str, str]) -> None:
    """Scan a directory for skill subdirectories containing SKILL.md.

    Args:
        base: Directory to scan.
        skills: Dict to update (name → content). Overwrites on collision.
    """
    if not base.is_dir():
        return
    for skill_dir in sorted(base.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skills[skill_dir.name] = skill_file.read_text()
