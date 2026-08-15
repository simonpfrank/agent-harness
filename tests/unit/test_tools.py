"""Tests for agent_harness.tools."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_harness.attachments import wrap_binary_output
from agent_harness.tools import (
    ToolRuntimeContext,
    build_tool_registry,
    edit_file,
    execute_code,
    execute_tool,
    generate_schema,
    list_directory,
    list_provider_models,
    read_file,
    registry,
    run_command,
    view_document,
    view_image,
    web_fetch,
    web_search,
    write_file,
)
from agent_harness.types import ToolCall

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_PDF_BYTES = b"%PDF-1.7\n" + b"\x00" * 32


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
        assert "view_image" in registry
        assert "view_document" in registry


class TestViewImage:
    def test_returns_confirmation(self, tmp_path: Path) -> None:
        path = tmp_path / "chart.png"
        path.write_bytes(_PNG_BYTES)
        result = view_image(str(path))
        assert "chart.png" in result

    def test_missing_file_raises(self) -> None:
        try:
            view_image("/no/such/chart.png")
        except FileNotFoundError:
            return
        raise AssertionError("expected FileNotFoundError")


class TestViewDocument:
    def test_returns_confirmation(self, tmp_path: Path) -> None:
        path = tmp_path / "report.pdf"
        path.write_bytes(_PDF_BYTES)
        result = view_document(str(path))
        assert "report.pdf" in result


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
            tool_registry = build_tool_registry(ToolRuntimeContext(executor="fake"))
            tc = ToolCall(id="tc_1", name="execute_code", arguments={"code": "print('hi')"})
            result = execute_tool(tc, tool_registry=tool_registry)
            output = result.output or ""
            assert output == "fake: print('hi')"
        finally:
            del executor_registry["fake"]


class TestWriteFile:
    def test_writes_content(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.txt")
            result = write_file(path, "hello world")
            with open(path) as handle:
                assert handle.read() == "hello world"
            assert "11" in result  # char count

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "deep", "file.txt")
            write_file(path, "nested")
            with open(path) as handle:
                assert handle.read() == "nested"

    def test_overwrites_existing(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("old")
            f.flush()
            write_file(f.name, "new")
            with open(f.name) as handle:
                assert handle.read() == "new"
        os.unlink(f.name)

    def test_registered(self) -> None:
        assert "write_file" in registry


class TestEditFile:
    def test_replaces_single_match(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "file.py")
            with open(path, "w") as f:
                f.write("def foo():\n    return 1\n")
            result = edit_file(path, "return 1", "return 2")
            with open(path) as f:
                assert f.read() == "def foo():\n    return 2\n"
            assert "file.py" in result

    def test_no_match_raises(self) -> None:
        import pytest

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "file.py")
            with open(path, "w") as f:
                f.write("def foo():\n    return 1\n")
            with pytest.raises(ValueError, match="not found"):
                edit_file(path, "return 99", "return 2")

    def test_multiple_matches_raises(self) -> None:
        import pytest

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "file.py")
            with open(path, "w") as f:
                f.write("x = 1\nx = 1\n")
            with pytest.raises(ValueError, match="not unique"):
                edit_file(path, "x = 1", "x = 2")

    def test_missing_file_raises(self) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            edit_file("/no/such/file.py", "a", "b")

    def test_registered(self) -> None:
        assert "edit_file" in registry


class TestWebFetch:
    @patch("agent_harness.tools.trafilatura.extract")
    @patch("agent_harness.tools.httpx.get")
    def test_extracts_main_content(self, mock_get: MagicMock, mock_extract: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = "<html><body><nav>menu</nav><p>The real content</p></body></html>"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        mock_extract.return_value = "The real content"

        result = web_fetch("https://example.com/pricing")

        assert result == "The real content"
        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == "https://example.com/pricing"
        mock_extract.assert_called_once_with(mock_response.text, output_format="markdown")

    @patch("agent_harness.tools.trafilatura.extract")
    @patch("agent_harness.tools.httpx.get")
    def test_falls_back_to_raw_text_when_extraction_fails(
        self, mock_get: MagicMock, mock_extract: MagicMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.text = "short page"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        mock_extract.return_value = None

        result = web_fetch("https://example.com/tiny")
        assert result == "short page"

    @patch("agent_harness.tools.httpx.get")
    def test_raises_on_http_error(self, mock_get: MagicMock) -> None:
        import httpx
        import pytest

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404),
        )
        mock_get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            web_fetch("https://example.com/missing")

    def test_registered(self) -> None:
        assert "web_fetch" in registry


class TestListProviderModels:
    @patch("agent_harness.tools.anthropic.Anthropic")
    def test_lists_anthropic_models(self, mock_anthropic_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            MagicMock(id="claude-haiku-4-5-20251001"),
            MagicMock(id="claude-opus-5-20260101"),
        ]
        mock_anthropic_cls.return_value = mock_client

        result = list_provider_models("anthropic")

        assert "claude-haiku-4-5-20251001" in result
        assert "claude-opus-5-20260101" in result

    @patch("agent_harness.tools.openai.OpenAI")
    def test_lists_openai_models(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            MagicMock(id="gpt-4o"),
            MagicMock(id="o4-mini"),
        ]
        mock_openai_cls.return_value = mock_client

        result = list_provider_models("openai")

        assert "gpt-4o" in result
        assert "o4-mini" in result

    def test_unknown_provider_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown provider"):
            list_provider_models("fakellm")

    @patch("agent_harness.tools.anthropic.Anthropic")
    def test_no_models_found(self, mock_anthropic_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_anthropic_cls.return_value = mock_client

        result = list_provider_models("anthropic")
        assert result == "No models found."

    def test_registered(self) -> None:
        assert "list_provider_models" in registry


class TestWebSearch:
    @patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test-key"})
    @patch("agent_harness.tools.httpx.post")
    def test_formats_results(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {"title": "Anthropic Pricing", "url": "https://anthropic.com/pricing", "content": "Rates per model."},
            ],
        }
        mock_post.return_value = mock_response

        result = web_search("anthropic api pricing")

        assert "Anthropic Pricing" in result
        assert "https://anthropic.com/pricing" in result
        assert "Rates per model." in result
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer tvly-test-key"
        assert call_kwargs["json"]["query"] == "anthropic api pricing"

    @patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test-key"})
    @patch("agent_harness.tools.httpx.post")
    def test_no_results(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"results": []}
        mock_post.return_value = mock_response

        assert web_search("a query with no hits") == "No results found."

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_raises(self) -> None:
        import pytest

        with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
            web_search("anything")

    def test_registered(self) -> None:
        assert "web_search" in registry


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


class TestExecuteToolAttachment:
    def test_view_image_call_builds_attachment(self, tmp_path: Path) -> None:
        path = tmp_path / "chart.png"
        path.write_bytes(_PNG_BYTES)
        tc = ToolCall(id="tc_1", name="view_image", arguments={"path": str(path)})
        result = execute_tool(tc)
        assert result.error is None
        assert result.attachment is not None
        assert result.attachment.kind == "image"
        assert result.attachment.media_type == "image/png"
        assert result.output is not None
        assert "chart.png" in result.output

    def test_view_document_call_builds_attachment(self, tmp_path: Path) -> None:
        path = tmp_path / "report.pdf"
        path.write_bytes(_PDF_BYTES)
        tc = ToolCall(id="tc_1", name="view_document", arguments={"path": str(path)})
        result = execute_tool(tc)
        assert result.error is None
        assert result.attachment is not None
        assert result.attachment.kind == "document"

    def test_view_image_missing_file_is_a_tool_error_not_a_crash(self) -> None:
        tc = ToolCall(id="tc_1", name="view_image", arguments={"path": "/no/such/chart.png"})
        result = execute_tool(tc)
        assert result.error is not None
        assert result.attachment is None

    def test_ordinary_tool_call_has_no_attachment(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": __file__})
        result = execute_tool(tc)
        assert result.attachment is None

    def test_mechanism_b_envelope_saved_and_output_replaced(self, tmp_path: Path) -> None:
        def fake_tool() -> str:
            return wrap_binary_output(_PNG_BYTES, filename="generated.png", media_type="image/png")

        fake_registry = {"fake_tool": fake_tool}
        tc = ToolCall(id="tc_1", name="fake_tool", arguments={})
        result = execute_tool(tc, tool_registry=fake_registry, tmp_dir=str(tmp_path))
        assert result.error is None
        assert result.attachment is None
        assert result.output is not None
        assert "generated.png" in result.output
        assert (tmp_path / "generated.png").read_bytes() == _PNG_BYTES

    def test_mechanism_b_survives_tiny_max_output_chars(self, tmp_path: Path) -> None:
        """Regression: extraction must run before truncation, or a large
        base64 payload gets corrupted before the envelope is ever found."""
        big_payload = _PNG_BYTES * 1000  # comfortably larger than max_output_chars below

        def fake_tool() -> str:
            return wrap_binary_output(big_payload, filename="big.png", media_type="image/png")

        fake_registry = {"fake_tool": fake_tool}
        tc = ToolCall(id="tc_1", name="fake_tool", arguments={})
        result = execute_tool(tc, tool_registry=fake_registry, tmp_dir=str(tmp_path), max_output_chars=20)
        assert result.error is None
        assert (tmp_path / "big.png").read_bytes() == big_payload

    def test_mcp_shadowed_view_image_does_not_build_attachment(self, tmp_path: Path) -> None:
        """Regression: an MCP server's own tool named 'view_image' is a
        different function object and must not be treated as the harness's
        built-in — only identity, not the string name, should trigger
        attachment-building."""

        def other_view_image(path: str) -> str:
            return f"mcp says: {path}"

        fake_registry = {"view_image": other_view_image}
        tc = ToolCall(id="tc_1", name="view_image", arguments={"path": str(tmp_path / "whatever.png")})
        result = execute_tool(tc, tool_registry=fake_registry)
        assert result.error is None
        assert result.attachment is None
        assert result.output == f"mcp says: {tmp_path / 'whatever.png'}"


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
