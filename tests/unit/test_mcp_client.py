"""Tests for agent_harness.mcp_client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from agent_harness.mcp_client import McpManager, McpServerSpec


def _text_block(text: str) -> TextContent:
    return TextContent(type="text", text=text)


def _tool(name: str, description: str = "does a thing", input_schema: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description, inputSchema=input_schema or {"type": "object"})


def _call_result(*texts: str) -> SimpleNamespace:
    return SimpleNamespace(content=[_text_block(t) for t in texts])


def _manager_with_mock_client(mock_client: AsyncMock, server_name: str = "server1") -> McpManager:
    """Build a manager with a real running background loop, but a mocked fastmcp.Client injected directly."""
    manager = McpManager([McpServerSpec(name=server_name, command="fake", args=[])])
    manager._start_loop_thread()
    manager._clients[server_name] = mock_client
    return manager


class TestListTools:
    def test_merges_schema_dicts_with_server_name(self) -> None:
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [_tool("read_file"), _tool("write_file")]
        manager = _manager_with_mock_client(mock_client)
        try:
            tools = manager.list_tools()
            schema = {"type": "object"}
            desc = "does a thing"
            assert tools == [
                {"server": "server1", "name": "read_file", "description": desc, "input_schema": schema},
                {"server": "server1", "name": "write_file", "description": desc, "input_schema": schema},
            ]
        finally:
            manager.close()

    def test_multiple_servers_merged_in_order(self) -> None:
        client_a = AsyncMock()
        client_a.list_tools.return_value = [_tool("tool_a")]
        client_b = AsyncMock()
        client_b.list_tools.return_value = [_tool("tool_b")]
        manager = McpManager([McpServerSpec(name="a", command="fake"), McpServerSpec(name="b", command="fake")])
        manager._start_loop_thread()
        manager._clients["a"] = client_a
        manager._clients["b"] = client_b
        try:
            tools = manager.list_tools()
            assert [t["server"] for t in tools] == ["a", "b"]
            assert [t["name"] for t in tools] == ["tool_a", "tool_b"]
        finally:
            manager.close()


class TestCallTool:
    def test_joins_multiple_text_blocks(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = _call_result("line one", "line two")
        manager = _manager_with_mock_client(mock_client)
        try:
            result = manager.call_tool("server1", "read_file", {"path": "a.txt"})
            assert result == "line one\nline two"
        finally:
            manager.close()

    def test_passes_name_and_arguments_through(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = _call_result("ok")
        manager = _manager_with_mock_client(mock_client)
        try:
            manager.call_tool("server1", "read_file", {"path": "a.txt"})
            mock_client.call_tool.assert_awaited_once_with("read_file", {"path": "a.txt"})
        finally:
            manager.close()

    def test_tool_error_propagates_and_does_not_mark_server_dead(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = ToolError("invalid arguments: missing 'path'")
        manager = _manager_with_mock_client(mock_client)
        try:
            with pytest.raises(ToolError):
                manager.call_tool("server1", "read_file", {})
            # Server not marked dead — a second call still reaches the client.
            mock_client.call_tool.side_effect = None
            mock_client.call_tool.return_value = _call_result("ok")
            result = manager.call_tool("server1", "read_file", {"path": "a.txt"})
            assert result == "ok"
            assert mock_client.call_tool.await_count == 2
        finally:
            manager.close()

    def test_transport_failure_marks_server_dead_and_fails_fast(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = ConnectionError("broken pipe")
        manager = _manager_with_mock_client(mock_client)
        try:
            with pytest.raises(RuntimeError, match="unavailable"):
                manager.call_tool("server1", "read_file", {"path": "a.txt"})
            # Second call fails fast — the mock client is not invoked again.
            with pytest.raises(RuntimeError, match="unavailable"):
                manager.call_tool("server1", "read_file", {"path": "a.txt"})
            assert mock_client.call_tool.await_count == 1
        finally:
            manager.close()

    def test_dead_server_does_not_affect_other_servers(self) -> None:
        dead_client = AsyncMock()
        dead_client.call_tool.side_effect = ConnectionError("broken pipe")
        healthy_client = AsyncMock()
        healthy_client.call_tool.return_value = _call_result("ok")
        specs = [McpServerSpec(name="dead", command="fake"), McpServerSpec(name="healthy", command="fake")]
        manager = McpManager(specs)
        manager._start_loop_thread()
        manager._clients["dead"] = dead_client
        manager._clients["healthy"] = healthy_client
        try:
            with pytest.raises(RuntimeError):
                manager.call_tool("dead", "some_tool", {})
            result = manager.call_tool("healthy", "some_tool", {})
            assert result == "ok"
        finally:
            manager.close()


class TestClose:
    def test_close_stops_background_thread(self) -> None:
        mock_client = AsyncMock()
        manager = _manager_with_mock_client(mock_client)
        thread = manager._thread
        manager.close()
        assert thread is not None
        thread.join(timeout=2)
        assert not thread.is_alive()

    def test_close_before_start_is_a_noop(self) -> None:
        manager = McpManager([McpServerSpec(name="server1", command="fake")])
        manager.close()  # should not raise


class TestStart:
    def test_start_connects_each_configured_server(self) -> None:
        with patch("agent_harness.mcp_client.Client") as mock_client_cls, patch(
            "agent_harness.mcp_client.StdioTransport"
        ) as mock_transport_cls:
            entered_client = AsyncMock()
            mock_client_cls.return_value = entered_client
            entered_client.__aenter__.return_value = entered_client

            specs = [
                McpServerSpec(name="fs", command="npx", args=["-y", "server-filesystem"], env={"X": "1"}),
            ]
            manager = McpManager(specs)
            try:
                manager.start()
                mock_transport_cls.assert_called_once_with(
                    command="npx", args=["-y", "server-filesystem"], env={"X": "1"},
                )
                assert "fs" in manager._clients
            finally:
                manager.close()

    def test_failed_connection_is_skipped_with_warning_not_raised(self) -> None:
        with patch("agent_harness.mcp_client.Client") as mock_client_cls, patch(
            "agent_harness.mcp_client.StdioTransport"
        ):
            broken_client = AsyncMock()
            broken_client.__aenter__.side_effect = ConnectionError("no such command")
            mock_client_cls.return_value = broken_client

            specs = [McpServerSpec(name="broken", command="does-not-exist")]
            manager = McpManager(specs)
            try:
                manager.start()  # should not raise
                assert "broken" not in manager._clients
                with pytest.raises(RuntimeError, match="unavailable"):
                    manager.call_tool("broken", "anything", {})
            finally:
                manager.close()
