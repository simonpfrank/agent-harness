"""Tests for agent_harness.runtime."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_harness.budget import Budget
from agent_harness.config import load as load_config
from agent_harness.permissions import PermissionDecision
from agent_harness.runtime import _make_callbacks, prepare_runtime
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall, ToolResult, Usage

VALID_AGENT = "tests/data/valid_agent"
WITH_MCP_SERVERS = "tests/data/agent_with_mcp_servers"


def _callbacks(*, stream: bool, show_thinking: bool, show_output: bool = True) -> LoopCallbacks:
    return _make_callbacks(
        budget=MagicMock(),
        hooks=MagicMock(),
        permissions=MagicMock(),
        tracer=MagicMock(),
        tool_registry={},
        max_output_chars=10_000,
        show_output=show_output,
        stream=stream,
        show_thinking=show_thinking,
    )


class TestOnDelta:
    @patch("agent_harness.runtime.show_delta")
    def test_shows_delta_when_show_output(self, mock_show_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        mock_show_delta.assert_called_once_with("hi")

    @patch("agent_harness.runtime.show_delta")
    def test_hidden_when_show_output_false(self, mock_show_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=False)
        assert cb.on_delta is not None
        cb.on_delta("default", "hi")
        mock_show_delta.assert_not_called()


class TestOnThinkingDelta:
    @patch("agent_harness.runtime.show_thinking_delta")
    def test_shows_when_show_thinking_true(self, mock_show_thinking_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=True, show_output=True)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_called_once_with("pondering")

    @patch("agent_harness.runtime.show_thinking_delta")
    def test_hidden_when_show_thinking_false(self, mock_show_thinking_delta: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_not_called()

    @patch("agent_harness.runtime.show_thinking_delta")
    def test_hidden_when_show_output_false_even_if_show_thinking_true(
        self, mock_show_thinking_delta: MagicMock,
    ) -> None:
        cb = _callbacks(stream=True, show_thinking=True, show_output=False)
        assert cb.on_thinking_delta is not None
        cb.on_thinking_delta("default", "pondering")
        mock_show_thinking_delta.assert_not_called()


class TestOnResponse:
    @patch("agent_harness.runtime.show_response")
    def test_skips_show_response_when_streaming(self, mock_show_response: MagicMock) -> None:
        cb = _callbacks(stream=True, show_thinking=False, show_output=True)
        response = Response(
            message=Message(role="assistant", content="hi"),
            usage=Usage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
        assert cb.on_response is not None
        cb.on_response(response)
        mock_show_response.assert_not_called()

    @patch("agent_harness.runtime.show_response")
    def test_shows_response_when_not_streaming(self, mock_show_response: MagicMock) -> None:
        cb = _callbacks(stream=False, show_thinking=False, show_output=True)
        response = Response(
            message=Message(role="assistant", content="hi"),
            usage=Usage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
        assert cb.on_response is not None
        cb.on_response(response)
        mock_show_response.assert_called_once_with(response)


class TestOnBudget:
    @patch("agent_harness.runtime.show_budget")
    def test_shows_plain_summary_when_not_exceeded(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = False
        budget.summary.return_value = "Turn 3/15 | $0.05/$0.30"
        cb = _make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        exceeded = cb.on_budget(Usage(10, 5))
        assert exceeded is False
        mock_show_budget.assert_called_once_with("Turn 3/15 | $0.05/$0.30")

    @patch("agent_harness.runtime.show_budget")
    def test_flags_stop_when_exceeded(self, mock_show_budget: MagicMock) -> None:
        budget = MagicMock()
        budget.record.return_value = True
        budget.summary.return_value = "Turn 15/15 | $0.2372/$0.30"
        cb = _make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_budget is not None
        exceeded = cb.on_budget(Usage(10, 5))
        assert exceeded is True
        shown = mock_show_budget.call_args.args[0]
        assert "Turn 15/15 | $0.2372/$0.30" in shown
        assert "stopping" in shown.lower()


class TestGetBudgetStatus:
    def test_wired_to_budget_status_note(self) -> None:
        budget = MagicMock()
        budget.status_note.return_value = "You have 3 turn(s) remaining."
        cb = _make_callbacks(
            budget=budget, hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.get_budget_status is not None
        assert cb.get_budget_status() == "You have 3 turn(s) remaining."
        budget.status_note.assert_called_once()


class TestOnPlanApproval:
    def test_none_when_no_plan_prompt_fn(self) -> None:
        cb = _make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=MagicMock(),
            tool_registry={}, max_output_chars=10_000, show_output=True,
        )
        assert cb.on_plan_approval is None

    def test_wired_to_plan_prompt_fn_and_traced(self) -> None:
        tracer = MagicMock()
        plan_prompt_fn = MagicMock(return_value=True)
        cb = _make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=True,
            plan_prompt_fn=plan_prompt_fn,
        )
        assert cb.on_plan_approval is not None
        result = cb.on_plan_approval(["Step one", "Step two"])
        assert result is True
        plan_prompt_fn.assert_called_once_with(["Step one", "Step two"])
        tracer.record.assert_called_with("plan_approval", steps=["Step one", "Step two"], approved=True)

    def test_records_denied_decision(self) -> None:
        tracer = MagicMock()
        plan_prompt_fn = MagicMock(return_value=False)
        cb = _make_callbacks(
            budget=MagicMock(), hooks=MagicMock(), permissions=MagicMock(), tracer=tracer,
            tool_registry={}, max_output_chars=10_000, show_output=True,
            plan_prompt_fn=plan_prompt_fn,
        )
        assert cb.on_plan_approval is not None
        assert cb.on_plan_approval(["Step one"]) is False
        tracer.record.assert_called_with("plan_approval", steps=["Step one"], approved=False)


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

        assert (agent_dir / "tmp").is_dir()
        runtime.finalize()

    def test_clears_pre_existing_tmp_dir_contents(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        stale_tmp = agent_dir / "tmp"
        stale_tmp.mkdir()
        (stale_tmp / "stale_file.png").write_bytes(b"old data")
        config = _tmp_agent_config(agent_dir)

        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.deny(), show_output=False, trace_enabled=False,
        )

        assert not (stale_tmp / "stale_file.png").exists()
        assert stale_tmp.is_dir()
        runtime.finalize()

    def test_tmp_dir_threaded_into_execute_tool(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        config = _tmp_agent_config(agent_dir, tools=["read_file"])

        with patch("agent_harness.runtime.execute_tool") as mock_execute_tool:
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
        assert kwargs["tmp_dir"] == str(agent_dir / "tmp")
        runtime.finalize()
