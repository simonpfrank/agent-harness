"""Tests for agent_harness.context."""

from agent_harness.context import _message_tokens, estimate_tokens, get_context_limit, trim_messages
from agent_harness.types import Attachment, Message, ToolResult


class TestEstimateTokens:
    def test_simple_string(self) -> None:
        assert estimate_tokens("hello world") > 0

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_approximation(self) -> None:
        # ~4 chars per token is the rough estimate
        text = "a" * 400
        tokens = estimate_tokens(text)
        assert 80 <= tokens <= 120


class TestGetContextLimit:
    def test_known_model(self) -> None:
        limit = get_context_limit("anthropic", "claude-haiku-4-5-20251001")
        assert limit > 0

    def test_supported_openai_model_has_explicit_limit(self) -> None:
        assert get_context_limit("openai", "gpt-5.6-luna") == 400_000

    def test_unknown_model_returns_default(self) -> None:
        limit = get_context_limit("unknown", "unknown-model")
        assert limit > 0


class TestMessageTokens:
    def test_attachment_data_contributes_to_estimate(self) -> None:
        without = Message(role="tool", tool_result=ToolResult(tool_call_id="tc", output="Viewing chart.png"))
        with_attachment = Message(
            role="tool",
            tool_result=ToolResult(
                tool_call_id="tc",
                output="Viewing chart.png",
                attachment=Attachment(kind="image", media_type="image/png", data="a" * 4000, filename="chart.png"),
            ),
        )
        assert _message_tokens(with_attachment) > _message_tokens(without)


class TestTrimMessages:
    def test_under_limit_unchanged(self) -> None:
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        trimmed = trim_messages(msgs, max_tokens=100_000)
        assert len(trimmed) == 3

    def test_system_always_preserved(self) -> None:
        msgs = [
            Message(role="system", content="You are helpful"),
        ]
        # Add many messages to exceed limit
        for i in range(100):
            msgs.append(Message(role="user", content=f"message {i} " * 100))
            msgs.append(Message(role="assistant", content=f"reply {i} " * 100))
        trimmed = trim_messages(msgs, max_tokens=1000)
        assert trimmed[0].role == "system"
        assert trimmed[0].content == "You are helpful"
        assert len(trimmed) < len(msgs)

    def test_keeps_recent_messages(self) -> None:
        msgs = [
            Message(role="system", content="sys"),
        ]
        for i in range(50):
            msgs.append(Message(role="user", content=f"msg {i} " * 50))
            msgs.append(Message(role="assistant", content=f"reply {i} " * 50))
        trimmed = trim_messages(msgs, max_tokens=2000)
        # Last message should be preserved
        assert trimmed[-1].content == msgs[-1].content

    def test_no_messages_returns_empty(self) -> None:
        assert trim_messages([], max_tokens=1000) == []
