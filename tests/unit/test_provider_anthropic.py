"""Tests for agent_harness.providers.anthropic."""

from unittest.mock import MagicMock, patch

import anthropic

from agent_harness.providers.anthropic import (
    _to_anthropic_messages,
    _to_anthropic_tools,
    _to_response,
    chat,
)
from agent_harness.types import Message, ToolCall, ToolResult


class TestToAnthropicMessages:
    def test_user_message(self) -> None:
        msgs = [Message(role="user", content="hello")]
        system, result = _to_anthropic_messages(msgs)
        assert system is None
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "hello"}

    def test_system_extracted(self) -> None:
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hi"),
        ]
        system, result = _to_anthropic_messages(msgs)
        assert system == "You are helpful"
        assert len(result) == 1

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo"})
        msgs = [Message(role="assistant", content="Let me read", tool_calls=[tc])]
        _, result = _to_anthropic_messages(msgs)
        assert len(result) == 1
        content = result[0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "tool_use"
        assert content[1]["id"] == "tc_1"

    def test_tool_result_message(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        msgs = [Message(role="tool", tool_result=tr)]
        _, result = _to_anthropic_messages(msgs)
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "tc_1"


class TestToAnthropicTools:
    def test_converts_schema(self) -> None:
        schemas = [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]
        result = _to_anthropic_tools(schemas)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert result[0]["input_schema"]["properties"]["path"]["type"] == "string"


class TestToResponse:
    def test_text_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text="Hello")]
        mock_resp.usage.input_tokens = 100
        mock_resp.usage.output_tokens = 50
        mock_resp.stop_reason = "end_turn"

        response = _to_response(mock_resp)
        assert response.message.role == "assistant"
        assert response.message.content == "Hello"
        assert response.message.tool_calls is None
        assert response.usage.input_tokens == 100
        assert response.stop_reason == "end_turn"

    def test_tool_use_response(self) -> None:
        text_block = MagicMock(type="text", text="thinking")
        tool_block = MagicMock(type="tool_use", id="tc_1", input={"path": "x"})
        tool_block.name = "read_file"
        mock_resp = MagicMock()
        mock_resp.content = [text_block, tool_block]
        mock_resp.usage.input_tokens = 100
        mock_resp.usage.output_tokens = 50
        mock_resp.stop_reason = "tool_use"

        response = _to_response(mock_resp)
        assert response.message.content == "thinking"
        assert response.message.tool_calls is not None
        assert len(response.message.tool_calls) == 1
        assert response.message.tool_calls[0].name == "read_file"
        assert response.stop_reason == "tool_use"


class TestChat:
    @patch("agent_harness.providers.anthropic._get_client")
    def test_calls_api(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        text_block = MagicMock(type="text", text="hi")
        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response

        msgs = [
            Message(role="system", content="be helpful"),
            Message(role="user", content="hello"),
        ]
        result = chat(msgs, tools=[], model="claude-haiku-4-5-20251001")
        assert result.message.content == "hi"
        mock_client.messages.create.assert_called_once()

    @patch("agent_harness.providers.anthropic._get_client")
    def test_passes_temperature(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        text_block = MagicMock(type="text", text="ok")
        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response

        chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
            top_p=0.3,
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["top_p"] == 0.3

    @patch("agent_harness.providers.anthropic._get_client")
    @patch("agent_harness.providers.retry.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep: MagicMock, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 429
        rate_limit_error = anthropic.RateLimitError(
            message="rate limited", response=error_response, body=None,
        )
        text_block = MagicMock(type="text", text="ok")
        success = MagicMock()
        success.content = [text_block]
        success.usage.input_tokens = 10
        success.usage.output_tokens = 5
        success.stop_reason = "end_turn"
        mock_client.messages.create.side_effect = [rate_limit_error, success]

        result = chat([Message(role="user", content="hi")], tools=[])
        assert result.message.content == "ok"
        assert mock_client.messages.create.call_count == 2
        mock_sleep.assert_called_once()

    @patch("agent_harness.providers.anthropic._get_client")
    def test_auth_error_fails_immediately(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 401
        auth_error = anthropic.AuthenticationError(
            message="bad key", response=error_response, body=None,
        )
        mock_client.messages.create.side_effect = auth_error

        try:
            chat([Message(role="user", content="hi")], tools=[])
            raise AssertionError("Should have raised")
        except RuntimeError as exc:
            assert "API key" in str(exc) or "authentication" in str(exc).lower()
        assert mock_client.messages.create.call_count == 1

    @patch("agent_harness.providers.anthropic._get_client")
    @patch("agent_harness.providers.retry.time.sleep")
    def test_max_retries_exceeded(self, mock_sleep: MagicMock, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 500
        server_error = anthropic.InternalServerError(
            message="server error", response=error_response, body=None,
        )
        mock_client.messages.create.side_effect = server_error

        try:
            chat([Message(role="user", content="hi")], tools=[])
            raise AssertionError("Should have raised")
        except RuntimeError as exc:
            assert "3 attempts" in str(exc)
        assert mock_client.messages.create.call_count == 3
