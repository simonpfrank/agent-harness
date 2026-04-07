"""Long-term memory tools — save, recall, and list agent memories."""

from __future__ import annotations

import re
from pathlib import Path

from agent_harness.hooks import INJECTION_PATTERNS

memory_dir: str = ""


def save_memory(key: str, content: str) -> str:
    """Save information to long-term memory.

    Scans content for injection patterns before saving.

    Args:
        key: Memory key (used as filename).
        content: Content to save.

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


def recall_memory(key: str) -> str:
    """Recall information from long-term memory.

    Args:
        key: Memory key to recall.

    Returns:
        Stored content.

    Raises:
        FileNotFoundError: If the memory key doesn't exist.
    """
    return (Path(memory_dir) / f"{key}.md").read_text()


def list_memories() -> str:
    """List all saved memory keys.

    Returns:
        Newline-separated list of keys, or a message if empty.
    """
    mem_path = Path(memory_dir)
    if not mem_path.exists():
        return "No memories saved."
    keys = sorted(p.stem for p in mem_path.glob("*.md"))
    return "\n".join(keys) if keys else "No memories saved."
