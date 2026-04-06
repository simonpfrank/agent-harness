"""Tests for memory tools (save_memory, recall_memory, list_memories)."""

import tempfile
from pathlib import Path

from agent_harness import tools as tools_module
from agent_harness.tools import list_memories, recall_memory, save_memory


class TestMemoryTools:
    def test_save_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_module.memory_dir = str(Path(tmpdir) / "memory")
            save_memory("test-key", "some value")
            result = recall_memory("test-key")
            assert result == "some value"

    def test_recall_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_module.memory_dir = str(Path(tmpdir) / "memory")
            try:
                recall_memory("nonexistent")
                raise AssertionError("Should have raised")
            except FileNotFoundError:
                pass

    def test_list_memories_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_module.memory_dir = str(Path(tmpdir) / "memory")
            result = list_memories()
            assert result == "No memories saved."

    def test_list_memories_with_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_module.memory_dir = str(Path(tmpdir) / "memory")
            save_memory("alpha", "first")
            save_memory("beta", "second")
            result = list_memories()
            assert "alpha" in result
            assert "beta" in result

    def test_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_module.memory_dir = str(Path(tmpdir) / "memory")
            save_memory("key", "old value")
            save_memory("key", "new value")
            assert recall_memory("key") == "new value"
