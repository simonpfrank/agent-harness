"""Tests for agent_harness.tools."""

import os
import tempfile

from agent_harness.tools import (
    execute_code,
    execute_tool,
    generate_schema,
    read_file,
    registry,
    run_command,
)
from agent_harness.types import ToolCall


class TestGenerateSchema:
    def test_simple_function(self) -> None:
        def greet(name: str, loud: bool = False) -> str:
            """Say hello.

            Args:
                name: Who to greet
                loud: Whether to shout
            """
            return f"hi {name}"

        schema = generate_schema(greet)
        assert schema["name"] == "greet"
        assert schema["description"] == "Say hello."
        props = schema["input_schema"]["properties"]
        assert "name" in props
        assert props["name"]["type"] == "string"
        assert "loud" in props
        assert props["loud"]["type"] == "boolean"
        assert "name" in schema["input_schema"]["required"]
        assert "loud" not in schema["input_schema"]["required"]

    def test_no_params(self) -> None:
        def noop() -> str:
            """Do nothing."""
            return ""

        schema = generate_schema(noop)
        assert schema["input_schema"]["properties"] == {}
        assert schema["input_schema"]["required"] == []


class TestRegistry:
    def test_builtins_registered(self) -> None:
        assert "run_command" in registry
        assert "read_file" in registry
        assert "execute_code" in registry


class TestExecuteTool:
    def test_success(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": __file__})
        result = execute_tool(tc)
        assert result.tool_call_id == "tc_1"
        assert result.output is not None
        assert "TestExecuteTool" in result.output
        assert result.error is None

    def test_unknown_tool(self) -> None:
        tc = ToolCall(id="tc_2", name="nonexistent", arguments={})
        result = execute_tool(tc)
        assert result.error is not None
        assert "Unknown tool" in result.error

    def test_tool_exception(self) -> None:
        tc = ToolCall(id="tc_3", name="read_file", arguments={"path": "/no/such/file"})
        result = execute_tool(tc)
        assert result.error is not None


class TestRunCommand:
    def test_simple_command(self) -> None:
        output = run_command("echo hello")
        assert output.strip() == "hello"

    def test_working_dir(self) -> None:
        output = run_command("pwd", working_dir="/tmp")
        assert "/tmp" in output.strip() or "/private/tmp" in output.strip()

    def test_failing_command(self) -> None:
        output = run_command("ls /nonexistent_dir_xyz")
        assert "No such file" in output or "cannot access" in output


class TestReadFile:
    def test_reads_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            f.flush()
            content = read_file(f.name)
        os.unlink(f.name)
        assert content == "test content"

    def test_missing_file_raises(self) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            read_file("/no/such/file.txt")


class TestExecuteCode:
    def test_python(self) -> None:
        output = execute_code("print(2 + 2)")
        assert "4" in output

    def test_bash(self) -> None:
        output = execute_code("echo hello", language="bash")
        assert "hello" in output

    def test_stderr_captured(self) -> None:
        output = execute_code("import sys; print('err', file=sys.stderr)")
        assert "err" in output


class TestExecuteToolTruncation:
    def test_output_truncated(self) -> None:
        tc = ToolCall(id="tc_1", name="execute_code", arguments={"code": "print('x' * 200)"})
        result = execute_tool(tc, max_output_chars=50)
        assert result.output is not None
        assert len(result.output) <= 80  # 50 + truncation message
        assert "[truncated" in result.output

    def test_output_not_truncated_when_under_limit(self) -> None:
        tc = ToolCall(id="tc_1", name="execute_code", arguments={"code": "print('hi')"})
        result = execute_tool(tc, max_output_chars=10000)
        assert result.output is not None
        assert "[truncated" not in result.output

    def test_default_no_truncation_for_small_output(self) -> None:
        tc = ToolCall(id="tc_1", name="execute_code", arguments={"code": "print('hi')"})
        result = execute_tool(tc)
        assert result.output is not None
        assert "[truncated" not in result.output
