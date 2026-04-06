"""Tests for agent_harness.providers.openai_provider."""

from unittest.mock import MagicMock, patch

from agent_harness.providers.openai_provider import (
    _to_openai_messages,
    _to_openai_tools,
    _to_response,
    chat,
)
from agent_harness.types import Message, ToolCall, ToolResult


class TestToOpenaiMessages:
    def test_user_message(self) -> None:
        msgs = [Message(role="user", content="hello")]
        result = _to_openai_messages(msgs)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "hello"}

    def test_system_message(self) -> None:
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hi"),
        ]
        result = _to_openai_messages(msgs)
        assert len(result) == 2
        assert result[0] == {"role": "system", "content": "You are helpful"}

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo"})
        msgs = [Message(role="assistant", content="Let me read", tool_calls=[tc])]
        result = _to_openai_messages(msgs)
        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me read"
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["id"] == "tc_1"
        assert msg["tool_calls"][0]["type"] == "function"
        assert msg["tool_calls"][0]["function"]["name"] == "read_file"

    def test_tool_result_message(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        msgs = [Message(role="tool", tool_result=tr)]
        result = _to_openai_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc_1"
        assert result[0]["content"] == "file data"

    def test_tool_result_error(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", error="not found")
        msgs = [Message(role="tool", tool_result=tr)]
        result = _to_openai_messages(msgs)
        assert result[0]["content"] == "not found"


class TestToOpenaiTools:
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
        result = _to_openai_tools(schemas)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "read_file"
        assert result[0]["function"]["parameters"]["properties"]["path"]["type"] == "string"


class TestToResponse:
    def test_text_response(self) -> None:
        choice = MagicMock()
        choice.message.role = "assistant"
        choice.message.content = "Hello"
        choice.message.tool_calls = None
        choice.finish_reason = "stop"

        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 50

        response = _to_response(mock_resp)
        assert response.message.role == "assistant"
        assert response.message.content == "Hello"
        assert response.message.tool_calls is None
        assert response.usage.input_tokens == 100
        assert response.usage.output_tokens == 50
        assert response.stop_reason == "end_turn"

    def test_tool_use_response(self) -> None:
        tool_call = MagicMock()
        tool_call.id = "tc_1"
        tool_call.function.name = "read_file"
        tool_call.function.arguments = '{"path": "x"}'

        choice = MagicMock()
        choice.message.role = "assistant"
        choice.message.content = "thinking"
        choice.message.tool_calls = [tool_call]
        choice.finish_reason = "tool_calls"

        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 50

        response = _to_response(mock_resp)
        assert response.message.content == "thinking"
        assert response.message.tool_calls is not None
        assert len(response.message.tool_calls) == 1
        assert response.message.tool_calls[0].name == "read_file"
        assert response.message.tool_calls[0].arguments == {"path": "x"}
        assert response.stop_reason == "tool_use"

    def test_tool_calls_with_stop_finish_reason(self) -> None:
        """OpenAI sometimes returns finish_reason=stop with tool_calls present."""
        tool_call = MagicMock()
        tool_call.id = "tc_1"
        tool_call.function.name = "run_command"
        tool_call.function.arguments = '{"command": "ls"}'

        choice = MagicMock()
        choice.message.role = "assistant"
        choice.message.content = None
        choice.message.tool_calls = [tool_call]
        choice.finish_reason = "stop"  # bug: should be "tool_calls"

        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage.prompt_tokens = 50
        mock_resp.usage.completion_tokens = 20

        response = _to_response(mock_resp)
        assert response.stop_reason == "tool_use"  # we detect from tool_calls presence
        assert response.message.tool_calls is not None


class TestChat:
    @patch("agent_harness.providers.openai_provider._get_client")
    def test_calls_api(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        choice = MagicMock()
        choice.message.role = "assistant"
        choice.message.content = "hi"
        choice.message.tool_calls = None
        choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [choice]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_client.chat.completions.create.return_value = mock_response

        msgs = [
            Message(role="system", content="be helpful"),
            Message(role="user", content="hello"),
        ]
        result = chat(msgs, tools=[], model="gpt-4o-mini")
        assert result.message.content == "hi"
        mock_client.chat.completions.create.assert_called_once()
