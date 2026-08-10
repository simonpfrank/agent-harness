"""Tests for tools.content_search."""

from pathlib import Path

import pytest

from tools.content_search import content_search


class TestContentSearch:
    def test_finds_matching_lines(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\ndef foo():\n    return x\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        result = content_search("def foo", str(tmp_path))
        assert "a.py:2: def foo():" in result
        assert "b.py" not in result

    def test_searches_recursively(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("TARGET_PATTERN = 1\n")
        result = content_search("TARGET_PATTERN", str(tmp_path))
        assert "nested.py:1:" in result

    def test_regex_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("model_a = 1\nmodel_b = 2\nother = 3\n")
        result = content_search(r"model_\w+", str(tmp_path))
        assert "model_a" in result
        assert "model_b" in result
        assert "other" not in result

    def test_no_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("nothing here\n")
        result = content_search("NOT_PRESENT", str(tmp_path))
        assert "No matches" in result

    def test_missing_directory(self) -> None:
        result = content_search("anything", "/no/such/dir")
        assert "No matches" in result or "not found" in result.lower()

    def test_skips_unreadable_binary_files_gracefully(self, tmp_path: Path) -> None:
        (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
        (tmp_path / "text.py").write_text("PATTERN_HERE = 1\n")
        result = content_search("PATTERN_HERE", str(tmp_path))
        assert "text.py:1:" in result

    def test_default_directory_is_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "here.py").write_text("FIND_ME = 1\n")
        result = content_search("FIND_ME")
        assert "here.py:1:" in result
