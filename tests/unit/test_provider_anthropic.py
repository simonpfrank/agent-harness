"""Tests for agent_harness.providers.anthropic."""

from unittest.mock import MagicMock, patch

import anthropic

from agent_harness.providers.anthropic import (
    _to_anthropic_messages,
    _to_anthropic_tools,
    _to_response,
    chat,
)
from agent_harness.types import Attachment, Message, ToolCall, ToolResult


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

    def test_tool_result_without_attachment_has_no_extra_message(self) -> None:
        tr = ToolResult(tool_call_id="tc_1", output="file data")
        msgs = [Message(role="tool", tool_result=tr)]
        _, result = _to_anthropic_messages(msgs)
        assert len(result) == 1

    def test_tool_result_with_image_attachment_emits_separate_message(self) -> None:
        attachment = Attachment(kind="image", media_type="image/png", data="abc123", filename="chart.png")
        tr = ToolResult(tool_call_id="tc_1", output="Viewing chart.png", attachment=attachment)
        msgs = [Message(role="tool", tool_result=tr)]
        _, result = _to_anthropic_messages(msgs)
        assert len(result) == 2
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[1] == {
            "role": "user",
            "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc123"}}],
        }

    def test_tool_result_with_document_attachment_emits_document_block(self) -> None:
        attachment = Attachment(kind="document", media_type="application/pdf", data="pdfdata", filename="r.pdf")
        tr = ToolResult(tool_call_id="tc_1", output="Viewing r.pdf", attachment=attachment)
        msgs = [Message(role="tool", tool_result=tr)]
        _, result = _to_anthropic_messages(msgs)
        assert len(result) == 2
        assert result[1]["content"][0]["type"] == "document"
        assert result[1]["content"][0]["source"]["media_type"] == "application/pdf"

    def test_assistant_with_thinking_blocks_prepended(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo"})
        blocks = [{"type": "thinking", "thinking": "let me think", "signature": "sig123"}]
        msgs = [
            Message(role="assistant", content="Let me read", tool_calls=[tc], thinking_blocks=blocks),
        ]
        _, result = _to_anthropic_messages(msgs)
        content = result[0]["content"]
        assert content[0] == blocks[0]
        assert content[1]["type"] == "text"
        assert content[2]["type"] == "tool_use"

    def test_assistant_with_thinking_blocks_no_tool_calls(self) -> None:
        blocks = [{"type": "redacted_thinking", "data": "opaque"}]
        msgs = [Message(role="assistant", content="hi", thinking_blocks=blocks)]
        _, result = _to_anthropic_messages(msgs)
        content = result[0]["content"]
        assert content[0] == blocks[0]
        assert content[1] == {"type": "text", "text": "hi"}


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

    def test_thinking_response(self) -> None:
        thinking_block = MagicMock(type="thinking", thinking="reasoning...", signature="sig123")
        text_block = MagicMock(type="text", text="the answer")
        mock_resp = MagicMock()
        mock_resp.content = [thinking_block, text_block]
        mock_resp.usage.input_tokens = 100
        mock_resp.usage.output_tokens = 50
        mock_resp.stop_reason = "end_turn"

        response = _to_response(mock_resp)
        assert response.message.content == "the answer"
        assert response.message.thinking == "reasoning..."
        assert response.message.thinking_blocks == [
            {"type": "thinking", "thinking": "reasoning...", "signature": "sig123"}
        ]

    def test_redacted_thinking_response(self) -> None:
        redacted_block = MagicMock(type="redacted_thinking", data="opaque-data")
        text_block = MagicMock(type="text", text="the answer")
        mock_resp = MagicMock()
        mock_resp.content = [redacted_block, text_block]
        mock_resp.usage.input_tokens = 100
        mock_resp.usage.output_tokens = 50
        mock_resp.stop_reason = "end_turn"

        response = _to_response(mock_resp)
        assert response.message.content == "the answer"
        assert response.message.thinking is None
        assert response.message.thinking_blocks == [{"type": "redacted_thinking", "data": "opaque-data"}]

    def test_no_thinking_blocks_leaves_fields_none(self) -> None:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text="hi")]
        mock_resp.usage.input_tokens = 1
        mock_resp.usage.output_tokens = 1
        mock_resp.stop_reason = "end_turn"

        response = _to_response(mock_resp)
        assert response.message.thinking is None
        assert response.message.thinking_blocks is None


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

    @patch("agent_harness.providers.anthropic._get_client")
    def test_thinking_sets_create_kwargs(self, mock_get_client: MagicMock) -> None:
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
            max_tokens=4096,
            thinking={"budget_tokens": 2000},
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2000}

    def test_thinking_budget_too_small_raises(self) -> None:
        try:
            chat([Message(role="user", content="hi")], tools=[], thinking={"budget_tokens": 100})
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "1024" in str(exc)

    def test_thinking_budget_exceeds_max_tokens_raises(self) -> None:
        try:
            chat(
                [Message(role="user", content="hi")],
                tools=[],
                max_tokens=1500,
                thinking={"budget_tokens": 2000},
            )
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "max_tokens" in str(exc)

    def test_thinking_with_temperature_raises(self) -> None:
        try:
            chat(
                [Message(role="user", content="hi")],
                tools=[],
                thinking={"budget_tokens": 2000},
                temperature=0.5,
            )
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "temperature" in str(exc).lower() or "thinking" in str(exc).lower()

    def test_thinking_with_top_p_raises(self) -> None:
        try:
            chat(
                [Message(role="user", content="hi")],
                tools=[],
                thinking={"budget_tokens": 2000},
                top_p=0.9,
            )
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "top_p" in str(exc).lower() or "thinking" in str(exc).lower()


class TestChatStreaming:
    @patch("agent_harness.providers.anthropic._get_client")
    def test_streams_text_deltas(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        text_delta_event = MagicMock(type="content_block_delta")
        text_delta_event.delta = MagicMock(type="text_delta", text="Hel")
        text_delta_event2 = MagicMock(type="content_block_delta")
        text_delta_event2.delta = MagicMock(type="text_delta", text="lo")

        final_text_block = MagicMock(type="text", text="Hello")
        final_message = MagicMock()
        final_message.content = [final_text_block]
        final_message.usage.input_tokens = 10
        final_message.usage.output_tokens = 5
        final_message.stop_reason = "end_turn"

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter([text_delta_event, text_delta_event2])
        mock_stream.get_final_message.return_value = final_message
        mock_client.messages.stream.return_value = mock_stream

        received: list[tuple[str, str]] = []

        def on_delta(agent_id: str, chunk: str) -> None:
            received.append((agent_id, chunk))

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            stream=True,
            on_delta=on_delta,
        )
        assert result.message.content == "Hello"
        assert received == [("default", "Hel"), ("default", "lo")]
        mock_client.messages.stream.assert_called_once()
        mock_client.messages.create.assert_not_called()

    @patch("agent_harness.providers.anthropic._get_client")
    def test_streams_thinking_deltas(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        thinking_delta_event = MagicMock(type="content_block_delta")
        thinking_delta_event.delta = MagicMock(type="thinking_delta", thinking="pondering")

        final_message = MagicMock()
        final_message.content = [MagicMock(type="text", text="ok")]
        final_message.usage.input_tokens = 10
        final_message.usage.output_tokens = 5
        final_message.stop_reason = "end_turn"

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter([thinking_delta_event])
        mock_stream.get_final_message.return_value = final_message
        mock_client.messages.stream.return_value = mock_stream

        received: list[tuple[str, str]] = []

        def on_thinking_delta(agent_id: str, chunk: str) -> None:
            received.append((agent_id, chunk))

        chat(
            [Message(role="user", content="hi")],
            tools=[],
            stream=True,
            thinking={"budget_tokens": 2000},
            on_thinking_delta=on_thinking_delta,
        )
        assert received == [("default", "pondering")]

    @patch("agent_harness.providers.anthropic._get_client")
    def test_stream_without_callbacks_still_returns_response(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        text_delta_event = MagicMock(type="content_block_delta")
        text_delta_event.delta = MagicMock(type="text_delta", text="hi")

        final_message = MagicMock()
        final_message.content = [MagicMock(type="text", text="hi")]
        final_message.usage.input_tokens = 1
        final_message.usage.output_tokens = 1
        final_message.stop_reason = "end_turn"

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter([text_delta_event])
        mock_stream.get_final_message.return_value = final_message
        mock_client.messages.stream.return_value = mock_stream

        result = chat([Message(role="user", content="hi")], tools=[], stream=True)
        assert result.message.content == "hi"

    @patch("agent_harness.providers.anthropic._get_client")
    def test_cancellation_stops_early_and_returns_locally_accumulated_partial_content(
        self, mock_get_client: MagicMock,
    ) -> None:
        """Confirmed live (2026-08-23): `get_final_message()` on an
        early-broken stream keeps consuming the rest of the stream
        internally (~same total wait as never cancelling at all). The
        cancelled path must build its Response from locally-accumulated
        deltas instead, and must never call get_final_message()."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        events = []
        for text in ["one", "two", "three", "four"]:
            event = MagicMock(type="content_block_delta")
            event.delta = MagicMock(type="text_delta", text=text)
            events.append(event)

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter(events)
        mock_client.messages.stream.return_value = mock_stream

        call_count = {"n": 0}

        def is_cancelled() -> bool:
            call_count["n"] += 1
            return call_count["n"] > 2

        result = chat(
            [Message(role="user", content="hi")],
            tools=[],
            stream=True,
            is_cancelled=is_cancelled,
        )

        assert result.message.content == "onetwo"
        assert result.stop_reason == "cancelled"
        mock_stream.get_final_message.assert_not_called()

    @patch("agent_harness.providers.anthropic._get_client")
    def test_no_is_cancelled_callback_uses_get_final_message_as_before(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        text_delta_event = MagicMock(type="content_block_delta")
        text_delta_event.delta = MagicMock(type="text_delta", text="hi")

        final_message = MagicMock()
        final_message.content = [MagicMock(type="text", text="hi")]
        final_message.usage.input_tokens = 1
        final_message.usage.output_tokens = 1
        final_message.stop_reason = "end_turn"

        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.__iter__.return_value = iter([text_delta_event])
        mock_stream.get_final_message.return_value = final_message
        mock_client.messages.stream.return_value = mock_stream

        result = chat([Message(role="user", content="hi")], tools=[], stream=True)
        assert result.message.content == "hi"
        mock_stream.get_final_message.assert_called_once()
