"""Synchronous bridge to MCP (Model Context Protocol) servers over stdio.

FastMCP's Client is asyncio-native with no synchronous API. This module
runs one persistent background thread and event loop per McpManager,
holding server connections open for the manager's whole lifetime, and
exposes a plain synchronous call_tool/list_tools/close surface so the
harness's synchronous loop core never has to deal with asyncio directly.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

logger = logging.getLogger(__name__)

_UNAVAILABLE_MESSAGE = "MCP server '{server}' is unavailable (connection lost)"


@dataclass
class McpServerSpec:
    """Configuration for one MCP server to connect to over stdio."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tools: list[str] | None = None


class McpManager:
    """Owns a background event loop and one persistent Client per configured MCP server.

    Args:
        specs: Servers to connect to when `start()` is called.
    """

    def __init__(self, specs: list[McpServerSpec]) -> None:
        self._specs = specs
        self._clients: dict[str, Client[Any]] = {}
        self._dead: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: AsyncExitStack | None = None

    def _start_loop_thread(self) -> None:
        ready = threading.Event()

        def _run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
        ready.wait()

    def start(self) -> None:
        """Start the background loop and connect every configured server.

        A server that fails to connect is logged and skipped — not raised —
        so one broken server doesn't prevent the others (or the run) from
        working. Calling a skipped server's tools later fails fast via the
        same "unavailable" path as a server that dies mid-run.
        """
        self._start_loop_thread()
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(self._connect_all(), self._loop).result()

    async def _connect_all(self) -> None:
        self._stack = AsyncExitStack()
        for spec in self._specs:
            transport = StdioTransport(command=spec.command, args=spec.args, env=spec.env or None)
            client = Client(transport)
            try:
                await self._stack.enter_async_context(client)
            except Exception:
                logger.warning("MCP server '%s' failed to connect — skipping", spec.name, exc_info=True)
                self._dead.add(spec.name)
                continue
            self._clients[spec.name] = client

    def list_tools(self) -> list[dict[str, Any]]:
        """List every tool from every connected server.

        Returns:
            One dict per tool: `{"server", "name", "description", "input_schema"}`.
        """
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(self._list_tools_async(), self._loop).result()

    async def _list_tools_async(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for server_name, client in self._clients.items():
            tools = await client.list_tools()
            for tool in tools:
                results.append({
                    "server": server_name,
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                })
        return results

    def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on a connected server, blocking until it returns.

        Args:
            server: Which configured server owns this tool.
            name: Tool name as reported by that server.
            arguments: Tool call arguments.

        Returns:
            Joined text content from the tool's result.

        Raises:
            ToolError: The server ran the tool and reported a normal error
                (e.g. bad arguments) — recoverable, the caller can retry
                with corrected input.
            RuntimeError: The server's connection is dead — either this
                call or a prior one hit a transport-level failure. Fails
                immediately without attempting a doomed round-trip.
        """
        if server in self._dead:
            raise RuntimeError(_UNAVAILABLE_MESSAGE.format(server=server))
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(self._call_tool_async(server, name, arguments), self._loop)
        try:
            return future.result()
        except ToolError:
            raise
        except Exception as exc:
            self._dead.add(server)
            raise RuntimeError(_UNAVAILABLE_MESSAGE.format(server=server)) from exc

    async def _call_tool_async(self, server: str, name: str, arguments: dict[str, Any]) -> str:
        client = self._clients[server]
        result = await client.call_tool(name, arguments)
        text_parts = [block.text for block in result.content if isinstance(block, TextContent)]
        return "\n".join(text_parts)

    def close(self) -> None:
        """Close every connection and stop the background thread."""
        if self._loop is None:
            return
        if self._stack is not None:
            asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
