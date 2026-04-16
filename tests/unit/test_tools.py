"""Tests for agent_harness.tools."""

import os
import tempfile

from agent_harness.tools import (
    execute_code,
    execute_tool,
    generate_schema,
    list_directory,
    read_file,
    registry,
    run_command,
    write_file,
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


class TestExecutorRegistry:
    def test_subprocess_is_default(self) -> None:
        from agent_harness.tools import executor_registry
        assert "subprocess" in executor_registry

    def test_custom_executor(self) -> None:
        from agent_harness.tools import executor_registry

        def fake_executor(code: str, language: str, timeout: int) -> str:
            return f"fake: {code}"

        executor_registry["fake"] = fake_executor
        try:
            from agent_harness import tools
            old = tools.active_executor
            tools.active_executor = "fake"
            output = execute_code("print('hi')")
            assert output == "fake: print('hi')"
        finally:
            tools.active_executor = old
            del executor_registry["fake"]


class TestWriteFile:
    def test_writes_content(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.txt")
            result = write_file(path, "hello world")
            assert "hello world" == open(path).read()
            assert "11" in result  # char count

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "deep", "file.txt")
            write_file(path, "nested")
            assert open(path).read() == "nested"

    def test_overwrites_existing(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("old")
            f.flush()
            write_file(f.name, "new")
            assert open(f.name).read() == "new"
        os.unlink(f.name)

    def test_registered(self) -> None:
        assert "write_file" in registry


class TestListDirectory:
    def test_lists_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.txt"), "w").close()
            open(os.path.join(d, "b.txt"), "w").close()
            os.mkdir(os.path.join(d, "subdir"))
            output = list_directory(d)
            assert "a.txt" in output
            assert "b.txt" in output
            assert "subdir/" in output

    def test_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            output = list_directory(d)
            assert output == "Directory is empty."

    def test_nonexistent_raises(self) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            list_directory("/no/such/dir")

    def test_registered(self) -> None:
        assert "list_directory" in registry


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
