"""Long-term memory helpers and tools."""

from __future__ import annotations

import re
from pathlib import Path

from agent_harness.hooks import INJECTION_PATTERNS

DEFAULT_MEMORY_DIR = "memory"


def save_memory(key: str, content: str, memory_dir: str = DEFAULT_MEMORY_DIR) -> str:
    """Save information to long-term memory.

    Scans content for injection patterns before saving.

    Args:
        key: Memory key (used as filename).
        content: Content to save.
        memory_dir: Directory where memory files are stored.

    Returns:
        Confirmation message.
    """
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            content = f"[WARNING: content flagged by injection scanner]\n{content}"
            break
    mem_path = Path(memory_dir)
    mem_path.mkdir(parents=True, exist_ok=True)
    (mem_path / f"{key}.md").write_text(content)
    return f"Saved memory: {key}"


def recall_memory(key: str, memory_dir: str = DEFAULT_MEMORY_DIR) -> str:
    """Recall information from long-term memory.

    Args:
        key: Memory key to recall.
        memory_dir: Directory where memory files are stored.

    Returns:
        Stored content.

    Raises:
        FileNotFoundError: If the memory key doesn't exist.
    """
    return (Path(memory_dir) / f"{key}.md").read_text()


def list_memories(memory_dir: str = DEFAULT_MEMORY_DIR) -> str:
    """List all saved memory keys.

    Args:
        memory_dir: Directory where memory files are stored.

    Returns:
        Newline-separated list of keys, or a message if empty.
    """
    mem_path = Path(memory_dir)
    if not mem_path.exists():
        return "No memories saved."
    keys = sorted(p.stem for p in mem_path.glob("*.md"))
    return "\n".join(keys) if keys else "No memories saved."
