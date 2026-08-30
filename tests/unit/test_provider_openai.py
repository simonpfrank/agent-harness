"""Tests for agent_harness.providers.openai_provider."""

from typing import Any
from unittest.mock import MagicMock, patch

import openai

from agent_harness.providers.openai_provider import (
    _build_create_kwargs,
    _response_endpoint_for_model,
    _to_openai_input,
    _to_openai_messages,
    _to_openai_tools,
    _to_response,
    chat,
)
from agent_harness.types import Attachment, Message, ToolCall, ToolResult


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

    def test_tool_result_without_attachment_has_no_extra_message(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        msgs = [Message(role="tool", tool_result=tr)]
        result = _to_openai_messages(msgs)
        assert len(result) == 1

    def test_tool_result_with_image_attachment_emits_image_url_message(self) -> None:
        attachment = Attachment(kind="image", media_type="image/png", data="abc123", filename="chart.png")
        tr = ToolResult(tool_call_id="tc_1", output="Viewing chart.png", attachment=attachment)
        msgs = [Message(role="tool", tool_result=tr)]
        result = _to_openai_messages(msgs)
        assert len(result) == 2
        assert result[1] == {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}}],
        }

    def test_tool_result_with_document_attachment_emits_unsupported_note(self) -> None:
        attachment = Attachment(kind="document", media_type="application/pdf", data="pdfdata", filename="r.pdf")
        tr = ToolResult(tool_call_id="tc_1", output="Viewing r.pdf", attachment=attachment)
        msgs = [Message(role="tool", tool_result=tr)]
        result = _to_openai_messages(msgs)
        assert len(result) == 2
        assert result[1]["role"] == "user"
        assert "r.pdf" in result[1]["content"]
        assert "Chat Completions" in result[1]["content"]


class TestToOpenaiInput:
    def test_converts_system_message_to_instructions(self) -> None:
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hello"),
        ]

        instructions, input_items = _to_openai_input(messages)

        assert instructions == "You are helpful"
        assert input_items == [{"role": "user", "content": "hello"}]

    def test_converts_assistant_tool_calls_and_tool_output(self) -> None:
        tool_call = ToolCall(
            id="call_1", name="read_file", arguments={"path": "foo.txt"}
        )
        tool_result = ToolResult(tool_call_id="call_1", output="contents")
        messages = [
            Message(role="assistant", content="Checking", tool_calls=[tool_call]),
            Message(role="tool", tool_result=tool_result),
        ]

        _, input_items = _to_openai_input(messages)

        assert input_items[0]["type"] == "function_call"
        assert input_items[0]["call_id"] == "call_1"
        assert input_items[0]["name"] == "read_file"
        assert input_items[1] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "contents",
        }

    def test_tool_result_without_attachment_has_no_extra_item(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        messages = [Message(role="tool", tool_result=tr)]
        _, input_items = _to_openai_input(messages)
        assert len(input_items) == 1

    def test_tool_result_with_image_attachment_emits_input_image(self) -> None:
        attachment = Attachment(kind="image", media_type="image/png", data="abc123", filename="chart.png")
        tr = ToolResult(tool_call_id="tc_1", output="Viewing chart.png", attachment=attachment)
        messages = [Message(role="tool", tool_result=tr)]
        _, input_items = _to_openai_input(messages)
        assert len(input_items) == 2
        assert input_items[1] == {
            "role": "user",
            "content": [{"type": "input_image", "image_url": "data:image/png;base64,abc123"}],
        }

    def test_tool_result_with_document_attachment_emits_input_file(self) -> None:
        attachment = Attachment(kind="document", media_type="application/pdf", data="pdfdata", filename="r.pdf")
        tr = ToolResult(tool_call_id="tc_1", output="Viewing r.pdf", attachment=attachment)
        messages = [Message(role="tool", tool_result=tr)]
        _, input_items = _to_openai_input(messages)
        assert len(input_items) == 2
        assert input_items[1] == {
            "role": "user",
            "content": [
                {"type": "input_file", "file_data": "data:application/pdf;base64,pdfdata", "filename": "r.pdf"},
            ],
        }


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
        assert (
            result[0]["function"]["parameters"]["properties"]["path"]["type"]
            == "string"
        )


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

    def test_reasoning_content_populates_thinking(self) -> None:
        """Non-streaming LM Studio/vLLM-style responses put reasoning-model
        thinking on message.reasoning_content — confirmed directly against
        a real LM Studio response, including the observed case where the
        model exhausts max_tokens entirely on thinking (content == '')."""
        choice = MagicMock()
        choice.message.role = "assistant"
        choice.message.content = ""
        choice.message.reasoning_content = "still thinking..."
        choice.message.tool_calls = None
        choice.finish_reason = "length"

        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 20

        response = _to_response(mock_resp)
        assert response.message.content is None
        assert response.message.thinking == "still thinking..."

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

    def test_responses_api_text_response(self) -> None:
        output_text = MagicMock()
        output_text.type = "output_text"
        output_text.text = "Hello"

        output_message = MagicMock()
        output_message.type = "message"
        output_message.content = [output_text]

        mock_resp = MagicMock()
        mock_resp.output = [output_message]
        mock_resp.usage.input_tokens = 12
        mock_resp.usage.output_tokens = 7
        mock_resp.choices = None

        response = _to_response(mock_resp)
        assert response.message.content == "Hello"
        assert response.message.tool_calls is None
        assert response.stop_reason == "end_turn"

    def test_responses_api_function_call_response(self) -> None:
        function_call = MagicMock()
        function_call.type = "function_call"
        function_call.call_id = "call_1"
        function_call.name = "run_command"
        function_call.arguments = '{"command": "pwd"}'

        mock_resp = MagicMock()
        mock_resp.output = [function_call]
        mock_resp.usage.input_tokens = 20
        mock_resp.usage.output_tokens = 5
        mock_resp.choices = None

        response = _to_response(mock_resp)
        assert response.message.tool_calls is not None
        assert response.message.tool_calls[0].id == "call_1"
        assert response.message.tool_calls[0].name == "run_command"
        assert response.message.tool_calls[0].arguments == {"command": "pwd"}
        assert response.stop_reason == "tool_use"


class TestEndpointRouting:
    def test_any_non_o_series_model_uses_responses_api(self) -> None:
        """No allowlist — any model name routes to Responses by default."""
        assert _response_endpoint_for_model("gpt-4o") == "responses"
        assert _response_endpoint_for_model("gpt-5.6-luna") == "responses"
        assert _response_endpoint_for_model("gpt-5-mini") == "responses"
        assert _response_endpoint_for_model("gpt-5-nano") == "responses"
        assert _response_endpoint_for_model("some-brand-new-future-model") == "responses"

    def test_base_url_forces_chat_completions(self) -> None:
        assert _response_endpoint_for_model("gpt-4o", base_url="http://localhost:1234/v1") == "chat_completions"

    def test_excluded_o_series_model_is_rejected(self) -> None:
        try:
            _response_endpoint_for_model("o4-mini")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "unsupported" in str(exc).lower()


class TestCreateKwargs:
    def test_builds_responses_kwargs_for_gpt_5_model(self) -> None:
        instructions, input_items = _to_openai_input(
            [Message(role="user", content="hi")]
        )
        kwargs = _build_create_kwargs(
            model="gpt-5.6-luna",
            instructions=instructions,
            input_items=input_items,
            tools=[],
            temperature=None,
            max_tokens=123,
            top_p=None,
        )

        assert kwargs["model"] == "gpt-5.6-luna"
        assert kwargs["input"] == [{"role": "user", "content": "hi"}]
        assert kwargs["max_output_tokens"] == 123
        assert "messages" not in kwargs
        assert "reasoning" not in kwargs

    def test_older_gpt_5_nano_defaults_to_minimal_reasoning(self) -> None:
        instructions, input_items = _to_openai_input(
            [Message(role="user", content="hi")]
        )
        kwargs = _build_create_kwargs(
            model="gpt-5-nano",
            instructions=instructions,
            input_items=input_items,
            tools=[],
            temperature=None,
            max_tokens=123,
            top_p=None,
        )

        assert kwargs["reasoning"] == {"effort": "minimal"}

    def test_builds_responses_kwargs_for_gpt_4o_model(self) -> None:
        instructions, input_items = _to_openai_input(
            [Message(role="user", content="hi")]
        )
        kwargs = _build_create_kwargs(
            model="gpt-5-mini",
            instructions=instructions,
            input_items=input_items,
            tools=[],
            temperature=0.0,
            max_tokens=123,
            top_p=0.5,
        )

        assert kwargs["temperature"] == 0.0
        assert kwargs["top_p"] == 0.5
        assert kwargs["max_output_tokens"] == 123
        assert kwargs["input"] == [{"role": "user", "content": "hi"}]


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
        mock_client.responses.create.return_value = mock_response

        msgs = [
            Message(role="system", content="be helpful"),
            Message(role="user", content="hello"),
        ]
        result = chat(msgs, tools=[], model="gpt-5-mini")
        assert result.message.content == "hi"
        mock_client.responses.create.assert_called_once()

    @patch("agent_harness.providers.openai_provider._get_client")
    @patch("agent_harness.providers.retry.time.sleep")
    def test_retries_on_rate_limit(
        self, mock_sleep: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 429
        error_response.headers = {}
        rate_error = openai.RateLimitError(
            message="rate limited",
            response=error_response,
            body=None,
        )
        choice = MagicMock()
        choice.message.role = "assistant"
        choice.message.content = "ok"
        choice.message.tool_calls = None
        choice.finish_reason = "stop"
        success = MagicMock()
        success.choices = [choice]
        success.usage.prompt_tokens = 10
        success.usage.completion_tokens = 5
        mock_client.responses.create.side_effect = [rate_error, success]

        result = chat([Message(role="user", content="hi")], tools=[])
        assert result.message.content == "ok"
        assert mock_client.responses.create.call_count == 2

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_passes_temperature_and_max_tokens(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        choice = MagicMock()
        choice.message.content = "ok"
        choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [choice]
        mock_response.usage.prompt_tokens = 1
        mock_response.usage.completion_tokens = 1
        mock_client.responses.create.return_value = mock_response

        chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="gpt-5-mini",
            temperature=0.0,
            max_tokens=1234,
            top_p=0.5,
        )
        call_kwargs = mock_client.responses.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["max_output_tokens"] == 1234
        assert call_kwargs["top_p"] == 0.5

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_excluded_model_fails_clearly(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        try:
            chat([Message(role="user", content="hi")], tools=[], model="o4-mini")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "unsupported" in str(exc).lower()
        mock_client.responses.create.assert_not_called()
        mock_client.chat.completions.create.assert_not_called()

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_custom_base_url_uses_chat_completions(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        choice = MagicMock()
        choice.message.content = "ok"
        choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [choice]
        mock_response.usage.prompt_tokens = 1
        mock_response.usage.completion_tokens = 1
        mock_client.chat.completions.create.return_value = mock_response

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
        )

        assert result.message.content == "ok"
        mock_client.chat.completions.create.assert_called_once()
        mock_client.responses.create.assert_not_called()

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_auth_error_fails_immediately(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 401
        error_response.headers = {}
        auth_error = openai.AuthenticationError(
            message="bad key",
            response=error_response,
            body=None,
        )
        mock_client.responses.create.side_effect = auth_error

        try:
            chat([Message(role="user", content="hi")], tools=[])
            raise AssertionError("Should have raised")
        except RuntimeError as exc:
            assert "API key" in str(exc) or "authentication" in str(exc).lower()
        assert mock_client.responses.create.call_count == 1


class TestChatStreaming:
    @patch("agent_harness.providers.openai_provider._get_client")
    def test_streams_text_deltas(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        delta_event1 = MagicMock(type="response.output_text.delta", delta="Hel")
        delta_event2 = MagicMock(type="response.output_text.delta", delta="lo")

        output_text = MagicMock(type="output_text", text="Hello")
        output_message = MagicMock(type="message", content=[output_text])
        final_response = MagicMock()
        final_response.output = [output_message]
        final_response.usage.input_tokens = 10
        final_response.usage.output_tokens = 5
        final_response.choices = None

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter([delta_event1, delta_event2])
        mock_stream.get_final_response.return_value = final_response
        mock_client.responses.stream.return_value = mock_stream

        received: list[tuple[str, str]] = []

        def on_delta(agent_id: str, chunk: str) -> None:
            received.append((agent_id, chunk))

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="gpt-5-mini",
            stream=True,
            on_delta=on_delta,
        )
        assert result.message.content == "Hello"
        assert received == [("default", "Hel"), ("default", "lo")]
        mock_client.responses.stream.assert_called_once()
        mock_client.responses.create.assert_not_called()

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_stream_without_callback_still_returns_response(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        delta_event = MagicMock(type="response.output_text.delta", delta="hi")
        output_text = MagicMock(type="output_text", text="hi")
        output_message = MagicMock(type="message", content=[output_text])
        final_response = MagicMock()
        final_response.output = [output_message]
        final_response.usage.input_tokens = 1
        final_response.usage.output_tokens = 1
        final_response.choices = None

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter([delta_event])
        mock_stream.get_final_response.return_value = final_response
        mock_client.responses.stream.return_value = mock_stream

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="gpt-5-mini",
            stream=True,
        )
        assert result.message.content == "hi"


def _cc_chunk(
    content: str | None = None, tool_calls: list[Any] | None = None, reasoning_content: str | None = None,
) -> MagicMock:
    delta = MagicMock(content=content, tool_calls=tool_calls, reasoning_content=reasoning_content)
    choice = MagicMock(delta=delta)
    return MagicMock(choices=[choice], usage=None)


def _cc_tool_call_delta(index: int, tc_id: str | None, name: str | None, arguments: str | None) -> MagicMock:
    function = MagicMock(arguments=arguments)
    function.name = name  # avoid MagicMock(name=...) special-casing the constructor kwarg
    return MagicMock(index=index, id=tc_id, function=function)


class TestChatCompletionsStreaming:
    @patch("agent_harness.providers.openai_provider._get_client")
    def test_streams_text_deltas(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        final_chunk = MagicMock(choices=[], usage=MagicMock(prompt_tokens=10, completion_tokens=5))
        mock_client.chat.completions.create.return_value = iter(
            [_cc_chunk(content="Hel"), _cc_chunk(content="lo"), final_chunk],
        )

        received: list[tuple[str, str]] = []
        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
            on_delta=lambda agent_id, chunk: received.append((agent_id, chunk)),
        )

        assert result.message.content == "Hello"
        assert received == [("default", "Hel"), ("default", "lo")]
        assert result.stop_reason == "end_turn"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_options"] == {"include_usage": True}

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_reasoning_content_deltas_fire_on_thinking_delta_not_on_delta(self, mock_get_client: MagicMock) -> None:
        """LM Studio/vLLM-style backends stream thinking-model reasoning as
        `delta.reasoning_content`, a separate field from `delta.content` —
        confirmed directly against a real LM Studio response, not assumed."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([
            _cc_chunk(reasoning_content="Let"),
            _cc_chunk(reasoning_content=" me think"),
            _cc_chunk(content="The"),
            _cc_chunk(content=" answer"),
        ])

        thinking_received: list[tuple[str, str]] = []
        answer_received: list[tuple[str, str]] = []
        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
            on_delta=lambda agent_id, chunk: answer_received.append((agent_id, chunk)),
            on_thinking_delta=lambda agent_id, chunk: thinking_received.append((agent_id, chunk)),
        )

        assert thinking_received == [("default", "Let"), ("default", " me think")]
        assert answer_received == [("default", "The"), ("default", " answer")]
        assert result.message.thinking == "Let me think"
        assert result.message.content == "The answer"

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_reasoning_only_response_leaves_content_none_not_empty_string(self, mock_get_client: MagicMock) -> None:
        """Real observed case: the model exhausts max_tokens entirely on
        thinking (finish_reason='length') before emitting any real content —
        content must be None, not '', so callers can tell nothing was said."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([_cc_chunk(reasoning_content="still thinking...")])

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
        )

        assert result.message.content is None
        assert result.message.thinking == "still thinking..."

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_no_thinking_delta_callback_does_not_raise(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([
            _cc_chunk(reasoning_content="thinking"), _cc_chunk(content="hi"),
        ])

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
        )
        assert result.message.content == "hi"
        assert result.message.thinking == "thinking"

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_tool_call_arguments_concatenated_across_chunks(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunk1 = _cc_chunk(tool_calls=[_cc_tool_call_delta(0, "call_1", "get_weather", '{"loc')])
        chunk2 = _cc_chunk(tool_calls=[_cc_tool_call_delta(0, None, None, 'ation": "NYC"}')])
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])

        result = chat(
            [Message(role="user", content="weather in NYC")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
        )

        assert result.stop_reason == "tool_use"
        assert result.message.tool_calls is not None
        assert len(result.message.tool_calls) == 1
        tc = result.message.tool_calls[0]
        assert tc.id == "call_1"
        assert tc.name == "get_weather"
        assert tc.arguments == {"location": "NYC"}

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_multiple_tool_calls_bucketed_by_index(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunk1 = _cc_chunk(
            tool_calls=[
                _cc_tool_call_delta(0, "call_1", "get_weather", '{"loc": "NYC"}'),
                _cc_tool_call_delta(1, "call_2", "get_time", '{"tz'),
            ],
        )
        chunk2 = _cc_chunk(tool_calls=[_cc_tool_call_delta(1, None, None, '": "UTC"}')])
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])

        result = chat(
            [Message(role="user", content="weather and time")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
        )

        assert result.message.tool_calls is not None
        assert len(result.message.tool_calls) == 2
        first, second = result.message.tool_calls
        assert first.id == "call_1"
        assert first.arguments == {"loc": "NYC"}
        assert second.id == "call_2"
        assert second.arguments == {"tz": "UTC"}

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_no_usage_chunk_defaults_to_zero(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([_cc_chunk(content="hi")])

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
        )

        assert result.message.content == "hi"
        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_cancellation_stops_early_and_returns_partial_content(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        # Cancel fires after the 2nd chunk — the 3rd/4th must never be seen.
        chunks_seen: list[str] = []

        def chunk_stream() -> Any:
            for text in ["one", "two", "three", "four"]:
                chunks_seen.append(text)
                yield _cc_chunk(content=text)

        mock_client.chat.completions.create.return_value = chunk_stream()

        call_count = {"n": 0}

        def is_cancelled() -> bool:
            call_count["n"] += 1
            return call_count["n"] > 2

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
            is_cancelled=is_cancelled,
        )

        assert result.message.content == "onetwo"
        assert result.stop_reason == "cancelled"
        assert chunks_seen == ["one", "two", "three"]  # generator advanced once more, chunk never processed

    @patch("agent_harness.providers.openai_provider._get_client")
    def test_no_is_cancelled_callback_does_not_raise(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([_cc_chunk(content="hi")])

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            model="qwen3-4b-thinking-2507",
            base_url="http://localhost:1234/v1",
            stream=True,
        )
        assert result.message.content == "hi"
        assert result.stop_reason == "end_turn"
