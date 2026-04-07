"""Tests for custom tool discovery from tools/ directory."""

import tempfile
from pathlib import Path

from agent_harness.tools import discover_tools, execute_tool, registry
from agent_harness.types import ToolCall


class TestDiscoverTools:
    def test_discovers_custom_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_file = Path(tmpdir) / "greet.py"
            tool_file.write_text(
                'def greet(name: str) -> str:\n'
                '    """Say hello to someone.\\n\\n    Args:\\n        name: Who to greet"""\n'
                '    return f"Hello, {name}!"\n'
            )
            discover_tools(tmpdir)
            assert "greet" in registry
            tc = ToolCall(id="tc_1", name="greet", arguments={"name": "World"})
            result = execute_tool(tc)
            assert result.output == "Hello, World!"
            # Cleanup
            del registry["greet"]

    def test_missing_dir_no_error(self) -> None:
        discover_tools("/nonexistent/tools/dir")
        # Should not raise

    def test_builtin_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_file = Path(tmpdir) / "read_file.py"
            tool_file.write_text(
                'def read_file(path: str) -> str:\n'
                '    """Fake read_file."""\n'
                '    return "OVERWRITTEN"\n'
            )
            # Create a test file to read
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("real content")
            discover_tools(tmpdir)
            # Built-in read_file should still work — not the fake one
            tc = ToolCall(id="tc_1", name="read_file", arguments={"path": str(test_file)})
            result = execute_tool(tc)
            assert result.output == "real content"

    def test_skips_files_without_return_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_file = Path(tmpdir) / "bad_tool.py"
            tool_file.write_text(
                'def bad_tool(x):\n'
                '    """No type hints."""\n'
                '    return str(x)\n'
            )
            discover_tools(tmpdir)
            assert "bad_tool" not in registry

    def test_skips_private_functions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_file = Path(tmpdir) / "helper.py"
            tool_file.write_text(
                'def _private(x: str) -> str:\n'
                '    """Private helper."""\n'
                '    return x\n'
            )
            discover_tools(tmpdir)
            assert "_private" not in registry
