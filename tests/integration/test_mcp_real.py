"""Real (zero-mock) integration tests against the reference MCP filesystem server.

Spawns the actual `@modelcontextprotocol/server-filesystem` stdio server via
npx and talks to it through McpManager exactly as the harness would in a
real run — no mocking of fastmcp, mcp, or the subprocess.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_harness.mcp_client import McpManager, McpServerSpec

requires_npx = pytest.mark.skipif(shutil.which("npx") is None, reason="npx not on PATH")


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "greeting.txt").write_text("hello from mcp integration test\n")
    return tmp_path


def _filesystem_manager(sandbox: Path) -> McpManager:
    args = ["-y", "@modelcontextprotocol/server-filesystem", str(sandbox)]
    return McpManager([McpServerSpec(name="fs", command="npx", args=args)])


@requires_npx
class TestMcpFilesystemServer:
    def test_list_tools_returns_real_server_tools(self, sandbox: Path) -> None:
        manager = _filesystem_manager(sandbox)
        manager.start()
        try:
            tools = manager.list_tools()
            names = {t["name"] for t in tools}
            assert "read_text_file" in names
            assert "list_directory" in names
            assert all(t["server"] == "fs" for t in tools)
            assert all(t["input_schema"] for t in tools)
        finally:
            manager.close()

    def test_call_tool_reads_a_real_file(self, sandbox: Path) -> None:
        manager = _filesystem_manager(sandbox)
        manager.start()
        try:
            result = manager.call_tool("fs", "read_text_file", {"path": str(sandbox / "greeting.txt")})
            assert result == "hello from mcp integration test\n"
        finally:
            manager.close()

    def test_call_tool_lists_a_real_directory(self, sandbox: Path) -> None:
        manager = _filesystem_manager(sandbox)
        manager.start()
        try:
            result = manager.call_tool("fs", "list_directory", {"path": str(sandbox)})
            assert "greeting.txt" in result
        finally:
            manager.close()

    def test_close_leaves_no_orphaned_process(self, sandbox: Path) -> None:
        manager = _filesystem_manager(sandbox)
        manager.start()
        manager.call_tool("fs", "read_text_file", {"path": str(sandbox / "greeting.txt")})
        thread = manager._thread
        manager.close()
        assert thread is not None
        thread.join(timeout=5)
        assert not thread.is_alive()
