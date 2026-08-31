"""Tests for agent_harness.runtime."""

import threading
from pathlib import Path
from unittest.mock import patch

from agent_harness.budget import Budget
from agent_harness.config import load as load_config
from agent_harness.permissions import PermissionDecision
from agent_harness.runtime import prepare_runtime
from agent_harness.types import AgentConfig, OutputSink, ToolCall, ToolResult

VALID_AGENT = "tests/data/valid_agent"
WITH_MCP_SERVERS = "tests/data/agent_with_mcp_servers"


class TestOutputSinkThreading:
    def test_output_sink_passed_through_to_callbacks(self) -> None:
        config = load_config(VALID_AGENT)
        deltas: list[str] = []
        sink = OutputSink(on_delta=lambda _agent_id, text: deltas.append(text))
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
            show_output=False,
            trace_enabled=False,
            output_sink=sink,
        )
        assert runtime.callbacks.on_delta is not None
        runtime.callbacks.on_delta("default", "hello")
        assert deltas == ["hello"]
        runtime.finalize()


class TestIsCancelledThreading:
    def test_is_cancelled_fn_passed_through_to_callbacks(self) -> None:
        config = load_config(VALID_AGENT)
        is_cancelled = lambda: True  # noqa: E731
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
            show_output=False,
            trace_enabled=False,
            is_cancelled_fn=is_cancelled,
        )
        assert runtime.callbacks.is_cancelled is is_cancelled
        runtime.finalize()


class TestPreparedRuntimeBudget:
    def test_exposes_budget_instance(self) -> None:
        config = load_config(VALID_AGENT)
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
            show_output=False,
            trace_enabled=False,
        )
        assert isinstance(runtime.budget, Budget)
        assert runtime.budget.turns == 0
        assert runtime.budget.total_cost == 0.0


class TestMcpWiring:
    def test_no_mcp_servers_configured_no_manager_built(self) -> None:
        config = load_config(VALID_AGENT)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        mock_manager_cls.assert_not_called()
        assert runtime.mcp_manager is None

    def test_mcp_servers_configured_manager_started_and_tools_merged(self) -> None:
        config = load_config(WITH_MCP_SERVERS)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mcp_tool = {"server": "filesystem", "name": "mcp_read", "description": "reads a file", "input_schema": {}}
            mock_manager.list_tools.return_value = [mcp_tool]
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )

        mock_manager_cls.assert_called_once()
        mock_manager.start.assert_called_once()
        assert runtime.mcp_manager is mock_manager
        assert "mcp_read" in runtime.tool_registry
        schema_names = [s["name"] for s in runtime.tool_schemas]
        assert "mcp_read" in schema_names

    def test_mcp_tool_calls_go_through_manager(self) -> None:
        config = load_config(WITH_MCP_SERVERS)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mcp_tool = {"server": "filesystem", "name": "mcp_read", "description": "reads a file", "input_schema": {}}
            mock_manager.list_tools.return_value = [mcp_tool]
            mock_manager.call_tool.return_value = "file contents"
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
            result = runtime.tool_registry["mcp_read"](path="a.txt")
        assert result == "file contents"
        mock_manager.call_tool.assert_called_once_with("filesystem", "mcp_read", {"path": "a.txt"})

    def test_mcp_tool_name_collision_with_builtin_is_skipped(self) -> None:
        config = load_config(WITH_MCP_SERVERS)  # already has "read_file" as a builtin tool
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            colliding_tool = {"server": "filesystem", "name": "read_file", "description": "collides"}
            mock_manager.list_tools.return_value = [{**colliding_tool, "input_schema": {}}]
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        # The builtin read_file wins — not overwritten by the MCP tool of the same name.
        from agent_harness.tools import read_file

        assert runtime.tool_registry["read_file"] is read_file

    def test_mcp_tool_not_exposed_by_agent_is_not_skipped(self) -> None:
        """A built-in tool that exists but isn't in this agent's `tools:` list doesn't block MCP.

        WITH_MCP_SERVERS only exposes "read_file" — `write_file` is a real
        built-in but this agent never opted into it, so there's nothing
        actually competing for that name from the model's point of view.
        """
        config = load_config(WITH_MCP_SERVERS)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mcp_write = {"server": "filesystem", "name": "write_file", "description": "mcp write", "input_schema": {}}
            mock_manager.list_tools.return_value = [mcp_write]
            mock_manager.call_tool.return_value = "written"
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        assert "write_file" in [s["name"] for s in runtime.tool_schemas]
        result = runtime.tool_registry["write_file"](path="a.txt", content="hi")
        assert result == "written"
        mock_manager.call_tool.assert_called_once_with("filesystem", "write_file", {"path": "a.txt", "content": "hi"})

    def test_two_mcp_servers_offering_same_tool_name_second_is_skipped(self) -> None:
        config = load_config(WITH_MCP_SERVERS)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            first = {"server": "server_a", "name": "shared_tool", "description": "from a", "input_schema": {}}
            second = {"server": "server_b", "name": "shared_tool", "description": "from b", "input_schema": {}}
            mock_manager.list_tools.return_value = [first, second]
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        schema_names = [s["name"] for s in runtime.tool_schemas]
        assert schema_names.count("shared_tool") == 1
        runtime.tool_registry["shared_tool"](x=1)
        mock_manager.call_tool.assert_called_once_with("server_a", "shared_tool", {"x": 1})

    def test_server_declared_tools_allowlist_filters_out_other_tools(self) -> None:
        config = load_config(WITH_MCP_SERVERS)
        config.mcp_servers[0]["tools"] = ["allowed_tool"]
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            allowed = {"server": "filesystem", "name": "allowed_tool", "description": "ok", "input_schema": {}}
            blocked = {"server": "filesystem", "name": "blocked_tool", "description": "no", "input_schema": {}}
            mock_manager.list_tools.return_value = [allowed, blocked]
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        assert "allowed_tool" in runtime.tool_registry
        assert "blocked_tool" not in runtime.tool_registry
        schema_names = [s["name"] for s in runtime.tool_schemas]
        assert "allowed_tool" in schema_names
        assert "blocked_tool" not in schema_names

    def test_no_server_declared_tools_key_exposes_everything_unchanged(self) -> None:
        """Regression guard: WITH_MCP_SERVERS declares no `tools:` allow-list —
        today's all-or-nothing behavior must be unaffected."""
        config = load_config(WITH_MCP_SERVERS)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            first = {"server": "filesystem", "name": "tool_a", "description": "a", "input_schema": {}}
            second = {"server": "filesystem", "name": "tool_b", "description": "b", "input_schema": {}}
            mock_manager.list_tools.return_value = [first, second]
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        assert "tool_a" in runtime.tool_registry
        assert "tool_b" in runtime.tool_registry

    def test_builtin_tool_can_reach_the_live_mcp_manager(self) -> None:
        """read_live_page_content (a built-in) needs a reference to the same
        McpManager instance MCP tools are merged through — proves the
        connect-before-build_tool_registry reorder actually threads it in,
        not just that MCP passthrough tools work (already covered above)."""
        config = load_config(WITH_MCP_SERVERS)
        config.tools = [*config.tools, "read_live_page_content"]
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mock_manager.list_tools.return_value = []
            mock_manager.call_tool.return_value = "<html><body>hi</body></html>"
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
            runtime.tool_registry["read_live_page_content"]()
        mock_manager.call_tool.assert_called_once_with(
            "playwright", "browser_evaluate", {"function": "() => document.documentElement.outerHTML"},
        )

    def test_finalize_closes_mcp_manager_when_present(self) -> None:
        config = load_config(WITH_MCP_SERVERS)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mock_manager.list_tools.return_value = []
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
        runtime.finalize()
        mock_manager.close.assert_called_once()

    def test_finalize_no_error_when_no_mcp_manager(self) -> None:
        config = load_config(VALID_AGENT)
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
            show_output=False,
            trace_enabled=False,
        )
        runtime.finalize()  # should not raise


class TestBrowserNavDomainGuard:
    """browser_click/browser_navigate on a server named 'playwright' get a
    post-call domain gate — browser_click's own arguments carry an opaque
    element ref, not a URL, so the harness can't know the destination
    before the call runs; this checks the *result* instead, reusing the
    existing network_exfiltration_blocker hook chain rather than a new
    mechanism. Real Playwright MCP result format ("- Page URL: <url>")
    verified against a live server, not assumed."""

    _NAV_RESULT = "### Page\n- Page URL: https://newdomain.com/page\n- Page Title: X\n### Snapshot\n"

    def _config_with_playwright_server(self, tmp_path: Path, allowed_domains: list[str] | None = None) -> AgentConfig:
        """Fresh AgentConfig per test — network_exfiltration_blocker persists
        approved domains to `{agent_dir}/.allowed_domains.yaml` on disk, so
        reusing a shared fixture directory across tests in this class would
        let one test's approval leak into another's "should prompt" case."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        return AgentConfig(
            name="test",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            agent_dir=str(agent_dir),
            instructions="test",
            tools=[],
            max_turns=5,
            hooks={"allowed_domains": allowed_domains or []},
            mcp_servers=[{"name": "playwright", "command": "npx", "args": ["@playwright/mcp@latest"]}],
        )

    def test_new_domain_approved_passes_result_through(self, tmp_path: Path) -> None:
        config = self._config_with_playwright_server(tmp_path)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            tool = {"server": "playwright", "name": "browser_click", "description": "d", "input_schema": {}}
            mock_manager.list_tools.return_value = [tool]
            mock_manager.call_tool.return_value = self._NAV_RESULT
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                domain_prompt_fn=lambda _domain: True,
                show_output=False,
                trace_enabled=False,
            )
            result = runtime.tool_registry["browser_click"](target="e1")
        assert result == self._NAV_RESULT
        assert not any(c.args[1] == "browser_navigate_back" for c in mock_manager.call_tool.call_args_list)

    def test_new_domain_denied_reverts_and_withholds_content(self, tmp_path: Path) -> None:
        config = self._config_with_playwright_server(tmp_path)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            tool = {"server": "playwright", "name": "browser_click", "description": "d", "input_schema": {}}
            mock_manager.list_tools.return_value = [tool]
            mock_manager.call_tool.return_value = self._NAV_RESULT
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                domain_prompt_fn=lambda _domain: False,
                show_output=False,
                trace_enabled=False,
            )
            result = runtime.tool_registry["browser_click"](target="e1")
        assert "newdomain.com" in result
        assert "not approved" in result
        mock_manager.call_tool.assert_any_call("playwright", "browser_navigate_back", {})

    def test_already_allowed_domain_does_not_prompt(self, tmp_path: Path) -> None:
        prompted: list[str] = []
        config = self._config_with_playwright_server(tmp_path, allowed_domains=["newdomain.com"])
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            tool = {"server": "playwright", "name": "browser_click", "description": "d", "input_schema": {}}
            mock_manager.list_tools.return_value = [tool]
            mock_manager.call_tool.return_value = self._NAV_RESULT
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                domain_prompt_fn=lambda domain: prompted.append(domain) or True,
                show_output=False,
                trace_enabled=False,
            )
            result = runtime.tool_registry["browser_click"](target="e1")
        assert prompted == []
        assert result == self._NAV_RESULT

    def test_browser_navigate_also_wrapped_catches_redirect(self, tmp_path: Path) -> None:
        """browser_navigate's pre-call check only validates the URL the agent
        wrote — this proves a redirect to a different domain is still caught
        via the same post-call wrapper, not just browser_click."""
        config = self._config_with_playwright_server(tmp_path)
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            tool = {"server": "playwright", "name": "browser_navigate", "description": "d", "input_schema": {}}
            mock_manager.list_tools.return_value = [tool]
            mock_manager.call_tool.return_value = self._NAV_RESULT
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                domain_prompt_fn=lambda _domain: False,
                show_output=False,
                trace_enabled=False,
            )
            result = runtime.tool_registry["browser_navigate"](url="https://short.ly/x")
        assert "not approved" in result
        mock_manager.call_tool.assert_any_call("playwright", "browser_navigate_back", {})

    def test_non_playwright_server_browser_named_tool_not_wrapped(self) -> None:
        """The wrapper is keyed on the server being named 'playwright', not
        just the tool name — a different server's same-named tool stays a
        plain passthrough."""
        config = load_config(WITH_MCP_SERVERS)  # server named "filesystem"
        with patch("agent_harness.runtime.McpManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            tool = {"server": "filesystem", "name": "browser_click", "description": "d", "input_schema": {}}
            mock_manager.list_tools.return_value = [tool]
            mock_manager.call_tool.return_value = self._NAV_RESULT
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
            result = runtime.tool_registry["browser_click"](target="e1")
        # No domain approval attempted at all — plain passthrough, unapproved domain leaks through.
        assert result == self._NAV_RESULT
        mock_manager.call_tool.assert_called_once_with("filesystem", "browser_click", {"target": "e1"})


def _tmp_agent_config(agent_dir: Path, tools: list[str] | None = None) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir=str(agent_dir),
        instructions="test",
        tools=tools or [],
        max_turns=5,
    )


class TestTmpDirLifecycle:
    def test_creates_tmp_dir_if_absent(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        config = _tmp_agent_config(agent_dir)

        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.deny(), show_output=False, trace_enabled=False,
        )

        assert Path(runtime.tmp_dir).is_dir()
        assert Path(runtime.tmp_dir).parent == agent_dir / "tmp"
        runtime.finalize()

    def test_stale_content_in_other_run_dirs_is_left_alone(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        stale_run_dir = agent_dir / "tmp" / "old-run-id"
        stale_run_dir.mkdir(parents=True)
        stale_file = stale_run_dir / "stale_file.png"
        stale_file.write_bytes(b"old data")
        config = _tmp_agent_config(agent_dir)

        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.deny(), show_output=False, trace_enabled=False,
        )

        assert stale_file.exists()
        assert Path(runtime.tmp_dir) != stale_run_dir
        runtime.finalize()

    def test_tmp_dir_threaded_into_execute_tool(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        config = _tmp_agent_config(agent_dir, tools=["read_file"])

        with patch("agent_harness.runtime_callbacks.execute_tool") as mock_execute_tool:
            mock_execute_tool.return_value = ToolResult(tool_call_id="tc", output="ok")
            runtime = prepare_runtime(
                config,
                permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False,
                trace_enabled=False,
            )
            tc = ToolCall(id="tc", name="read_file", arguments={"path": "x"})
            assert runtime.callbacks.on_tool_call is not None
            runtime.callbacks.on_tool_call(tc)

        _, kwargs = mock_execute_tool.call_args
        assert kwargs["tmp_dir"] == runtime.tmp_dir
        runtime.finalize()

    def test_concurrent_prepare_runtime_calls_get_isolated_tmp_dirs(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        config = _tmp_agent_config(agent_dir)
        results: list[str] = []
        lock = threading.Lock()

        def run() -> None:
            rt = prepare_runtime(
                config, permission_prompt_fn=lambda _tc: PermissionDecision.deny(),
                show_output=False, trace_enabled=False,
            )
            (Path(rt.tmp_dir) / "marker.txt").write_text(rt.tmp_dir)
            with lock:
                results.append(rt.tmp_dir)
            rt.finalize()

        threads = [threading.Thread(target=run) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(results)) == 10  # every run got its own dir
        for tmp_dir in results:
            assert (Path(tmp_dir) / "marker.txt").read_text() == tmp_dir  # nothing clobbered
