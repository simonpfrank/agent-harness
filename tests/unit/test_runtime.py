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
